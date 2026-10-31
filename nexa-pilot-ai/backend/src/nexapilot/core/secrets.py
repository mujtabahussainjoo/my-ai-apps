"""Secret storage abstraction.

Secrets (API keys, OAuth client secrets, refresh tokens) are stored in the
operating system credential vault via ``keyring``. A restricted file backend and
an in-memory backend exist for environments without a Secret Service (CI, headless
containers); the file backend is explicitly degraded security and is reported as
such by :func:`describe_backend`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from nexapilot.core.errors import NexaPilotError
from nexapilot.core.logging import get_logger

SERVICE_NAME = "nexapilot"

log = get_logger(__name__)


class SecretStore(Protocol):
    """Minimal secret-store contract used across the application."""

    def get(self, reference: str) -> str | None: ...

    def set(self, reference: str, value: str) -> None: ...

    def delete(self, reference: str) -> bool: ...

    def list_references(self) -> list[str]: ...


class SecretStoreError(NexaPilotError):
    code = "secret_store_error"
    http_status = 500


class MemorySecretStore:
    """In-memory store. Used by tests and by the ``memory`` backend setting."""

    backend_name = "memory"
    security = "ephemeral"

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, reference: str) -> str | None:
        with self._lock:
            return self._values.get(reference)

    def set(self, reference: str, value: str) -> None:
        with self._lock:
            self._values[reference] = value

    def delete(self, reference: str) -> bool:
        with self._lock:
            return self._values.pop(reference, None) is not None

    def list_references(self) -> list[str]:
        with self._lock:
            return sorted(self._values)


class KeyringSecretStore:
    """OS credential vault backend (Windows Credential Manager, macOS Keychain, Secret Service)."""

    backend_name = "keyring"
    security = "os-vault"

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service_name = service_name
        self._impl: Any | None = None

    def _backend(self) -> Any:
        if self._impl is None:
            try:
                import keyring
                from keyring.backends.fail import Keyring as FailKeyring
            except Exception as exc:  # pragma: no cover - import guard
                raise SecretStoreError("keyring backend unavailable") from exc

            try:
                backend = keyring.get_keyring()
            except Exception as exc:  # pragma: no cover - environment guard
                raise SecretStoreError("keyring backend unavailable") from exc

            if isinstance(backend, FailKeyring):
                raise SecretStoreError("no usable OS credential vault detected")
            self._impl = keyring
        return self._impl

    def get(self, reference: str) -> str | None:
        backend = self._backend()
        try:
            value: str | None = backend.get_password(self._service_name, reference)
            return value
        except Exception as exc:  # pragma: no cover - platform guard
            raise SecretStoreError("failed to read secret from OS vault") from exc

    def set(self, reference: str, value: str) -> None:
        backend = self._backend()
        try:
            backend.set_password(self._service_name, reference, value)
        except Exception as exc:  # pragma: no cover - platform guard
            raise SecretStoreError("failed to write secret to OS vault") from exc

    def delete(self, reference: str) -> bool:
        backend = self._backend()
        try:
            backend.delete_password(self._service_name, reference)
            return True
        except Exception:
            return False

    def list_references(self) -> list[str]:
        # The OS vault cannot be enumerated portably; the application keeps its own
        # index of references in the database.
        return []

    def available(self) -> bool:
        """Probe the vault with a throwaway entry so startup can fall back safely."""
        try:
            backend = self._backend()
            probe = "__nexapilot_probe__"
            backend.set_password(self._service_name, probe, "probe")
            backend.delete_password(self._service_name, probe)
            return True
        except Exception:
            return False


class FileSecretStore:
    """Fallback store writing to a 0600 file. Degraded security, opt-in only."""

    backend_name = "file"
    security = "degraded"

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretStoreError("failed to read secret file") from exc
        if not isinstance(data, dict):
            raise SecretStoreError("secret file is malformed")
        return {str(key): str(value) for key, value in data.items()}

    def _write(self, values: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self._path)

    def get(self, reference: str) -> str | None:
        with self._lock:
            return self._read().get(reference)

    def set(self, reference: str, value: str) -> None:
        with self._lock:
            values = self._read()
            values[reference] = value
            self._write(values)

    def delete(self, reference: str) -> bool:
        with self._lock:
            values = self._read()
            existed = values.pop(reference, None) is not None
            self._write(values)
            return existed

    def list_references(self) -> list[str]:
        with self._lock:
            return sorted(self._read())


def build_secret_store(backend: str, *, data_dir: Path | None = None) -> SecretStore:
    """Instantiate the configured secret store backend.

    A requested OS vault that is unavailable (headless Linux, CI) falls back to the
    0600 file store so the app still works; the degradation is reported to the UI.
    """
    if backend == "memory":
        return MemorySecretStore()
    if backend == "file":
        base = data_dir or _default_secret_dir()
        return FileSecretStore(base / "secrets.json")
    vault = KeyringSecretStore()
    if vault.available():
        return vault
    log.warning("secrets.vault_unavailable", fallback="file")
    base = data_dir or _default_secret_dir()
    return FileSecretStore(base / "secrets.json")


def _default_secret_dir() -> Path:
    from nexapilot.core.paths import data_dir as app_data_dir

    return app_data_dir()


def describe_backend(backend: str | SecretStore) -> dict[str, str]:
    if not isinstance(backend, str):
        backend = str(getattr(backend, "backend_name", "unknown"))
    if backend == "keyring":
        return {
            "backend": "keyring",
            "security": "os-vault",
            "note": "Secrets are stored in the operating system credential vault.",
        }
    if backend == "file":
        return {
            "backend": "file",
            "security": "degraded",
            "note": (
                "Secrets are stored in a 0600-permission local file. This is a degraded "
                "fallback for systems without an OS credential vault."
            ),
        }
    return {"backend": "memory", "security": "ephemeral", "note": "Secrets are not persisted."}


def redact_references(references: Iterable[str]) -> list[str]:
    """Secret *references* are not secrets; they are safe to display."""
    return sorted(references)
