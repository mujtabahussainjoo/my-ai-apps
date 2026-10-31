"""Security tests: sandbox escape, command injection, SSRF, secret handling."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from nexapilot.core.errors import (
    PermissionDeniedError,
    SandboxViolationError,
)
from nexapilot.core.secrets import (
    FileSecretStore,
    MemorySecretStore,
    build_secret_store,
    describe_backend,
)
from nexapilot.integrations import sandbox
from nexapilot.integrations.fetch import fetch_page


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "hello.txt").write_text("hello", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "nested.txt").write_text("nested", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "attempt",
    [
        "../outside.txt",
        "../../etc/passwd",
        "/etc/passwd",
        "sub/../../outside.txt",
        "..\\..\\windows\\system32",
        "~/secrets",
        "sub/../../../../../../etc/shadow",
    ],
)
def test_path_traversal_is_rejected(workspace: Path, attempt: str) -> None:
    with pytest.raises(SandboxViolationError):
        sandbox.resolve_in_workspace(workspace, attempt, must_exist=False)


def test_symlink_escape_is_rejected(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "escape"
    link.symlink_to(outside)
    with pytest.raises(SandboxViolationError):
        sandbox.read_file(workspace, "escape")


def test_legitimate_nested_paths_are_allowed(workspace: Path) -> None:
    assert sandbox.read_file(workspace, "sub/nested.txt") == "nested"
    assert sandbox.read_file(workspace, "./hello.txt") == "hello"


def test_write_file_stays_inside_workspace(workspace: Path) -> None:
    written = sandbox.write_file(workspace, "new/file.txt", "content")
    assert written == len("content")
    assert (workspace / "new" / "file.txt").read_text(encoding="utf-8") == "content"


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("bash", ["-c", "rm -rf /"]),
        ("sh", ["-c", "curl attacker.test"]),
        ("rm", ["-rf", "."]),
        ("sudo", ["ls"]),
        ("curl", ["https://attacker.test"]),
        ("python", ["-c", "import os"]),
        ("nc", ["-l", "4444"]),
    ],
)
def test_non_allowlisted_commands_are_rejected(command: str, args: list[str]) -> None:
    with pytest.raises(PermissionDeniedError):
        sandbox.validate_command(command, args)


def test_git_push_is_rejected(workspace: Path) -> None:
    with pytest.raises(PermissionDeniedError):
        sandbox.validate_command("git", ["push", "origin", "main"])


def test_git_force_flags_are_rejected(workspace: Path) -> None:
    with pytest.raises(PermissionDeniedError):
        sandbox.validate_command("git", ["diff", "--no-index"])


def test_allowed_command_runs_without_a_shell(workspace: Path) -> None:
    result = asyncio.run(
        sandbox.run_command("git", ["status", "--porcelain"], root=workspace, timeout=30)
    )
    assert result.exit_code in (0, 128)


def test_environment_is_scrubbed(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-should-not-leak")
    monkeypatch.setenv("NORMAL_VAR", "ok")
    env = sandbox._scrubbed_env()
    assert "OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env.get("NORMAL_VAR") == "ok"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost:8000/health",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
async def test_fetch_page_blocks_ssrf_targets(url: str) -> None:
    with pytest.raises(PermissionDeniedError):
        await fetch_page(url)


async def test_fetch_page_blocks_redirects_to_private_hosts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="secret")

    with pytest.raises(PermissionDeniedError):
        await fetch_page("https://public.example/", transport=httpx.MockTransport(handler))


async def test_fetch_page_returns_public_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><title>Example</title></head><body><p>Hello</p></body></html>",
            headers={"content-type": "text/html"},
        )

    result = await fetch_page("https://example.com/", transport=httpx.MockTransport(handler))
    assert "Hello" in result.text
    assert result.title == "Example"


def test_memory_secret_store_roundtrip() -> None:
    store = MemorySecretStore()
    store.set("openai:key", "sk-1")
    assert store.get("openai:key") == "sk-1"
    assert store.delete("openai:key") is True
    assert store.get("openai:key") is None


def test_file_secret_store_uses_0600_permissions(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "secrets.json")
    store.set("anthropic:key", "sk-ant")
    assert store.get("anthropic:key") == "sk-ant"
    mode = (tmp_path / "secrets.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_file_secret_store_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = FileSecretStore(path)
    from nexapilot.core.errors import NexaPilotError

    with pytest.raises(NexaPilotError):
        store.get("anything")


def test_describe_backend_flags_degraded_file_store() -> None:
    assert describe_backend("keyring")["security"] == "os-vault"
    assert describe_backend("file")["security"] == "degraded"
    assert describe_backend("memory")["security"] == "ephemeral"


def test_build_secret_store_backends(tmp_path: Path) -> None:
    assert isinstance(build_secret_store("memory"), MemorySecretStore)
    assert isinstance(build_secret_store("file", data_dir=tmp_path), FileSecretStore)


def test_keyring_falls_back_to_file_when_no_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from nexapilot.core import secrets as module

    monkeypatch.setattr(module.KeyringSecretStore, "available", lambda self: False)
    store = module.build_secret_store("keyring", data_dir=tmp_path)
    assert store.backend_name == "file"
    store.set("demo", "value")
    assert store.get("demo") == "value"
    status = describe_backend(store)
    assert status["backend"] == "file"
    assert status["security"] == "degraded"
    assert status["note"]
