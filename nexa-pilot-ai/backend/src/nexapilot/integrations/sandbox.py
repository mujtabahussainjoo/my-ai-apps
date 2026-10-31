"""Sandboxed workspace for the coding agent.

The coding agent may only read and write inside a workspace directory the user
selected, and may only run a small allowlist of development commands without a
shell. Both restrictions are enforced in code.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexapilot.core.errors import (
    PermissionDeniedError,
    SandboxViolationError,
    ToolExecutionError,
    ToolTimeoutError,
)
from nexapilot.core.logging import get_logger

log = get_logger(__name__)

MAX_READ_BYTES = 2_000_000
MAX_OUTPUT_BYTES = 256_000

#: Commands the coding agent may execute, mapped to the argument policy.
ALLOWED_COMMANDS: dict[str, dict[str, Any]] = {
    "python": {"max_args": 12, "forbidden_flags": ("-c", "-m", "-p")},
    "python3": {"max_args": 12, "forbidden_flags": ("-c", "-m", "-p")},
    "pytest": {"max_args": 12, "forbidden_flags": ()},
    "ruff": {"max_args": 12, "forbidden_flags": ()},
    "mypy": {"max_args": 12, "forbidden_flags": ()},
    "black": {"max_args": 12, "forbidden_flags": ()},
    "npm": {"max_args": 12, "forbidden_flags": ()},
    "node": {"max_args": 12, "forbidden_flags": ("-e", "--eval")},
    "npx": {"max_args": 12, "forbidden_flags": ()},
    "go": {"max_args": 12, "forbidden_flags": ()},
    "cargo": {"max_args": 12, "forbidden_flags": ()},
    "make": {"max_args": 8, "forbidden_flags": ()},
    "ls": {"max_args": 4, "forbidden_flags": ()},
    "cat": {"max_args": 4, "forbidden_flags": ()},
    "head": {"max_args": 4, "forbidden_flags": ()},
    "tail": {"max_args": 4, "forbidden_flags": ()},
    "grep": {"max_args": 6, "forbidden_flags": ()},
    "rg": {"max_args": 6, "forbidden_flags": ()},
    "find": {
        "max_args": 6,
        "forbidden_flags": (
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-delete",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
        ),
    },
    "git": {
        "max_args": 12,
        # These flags let git read or write outside the workspace.
        "forbidden_flags": (
            "--no-index",
            "--git-dir",
            "--work-tree",
            "--exec-path",
            "--upload-pack",
            "--receive-pack",
            "-C",
            "-c",
        ),
        "allowed_subcommands": {
            "status",
            "diff",
            "log",
            "show",
            "rev-parse",
            "ls-files",
            "blame",
            "branch",
        },
    },
}

#: Environment variables that must never be inherited by sandboxed commands.
BLOCKED_ENV_PREFIXES = (
    "AWS_",
    "AZURE_",
    "GCP_",
    "GOOGLE_",
    "NEXAPILOT_",
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "TAVILY_",
    "BRAVE_",
    "AMADEUS_",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
)


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
        }


def resolve_workspace(root: str | Path) -> Path:
    """Resolve and validate the workspace root."""
    if not root:
        raise PermissionDeniedError("No coding workspace has been configured.")
    path = Path(root).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PermissionDeniedError(
            f"Workspace directory is not accessible: {path}", details={"path": str(path)}
        ) from exc
    if not resolved.is_dir():
        raise PermissionDeniedError(f"Workspace is not a directory: {resolved}")
    return resolved


def resolve_in_workspace(root: Path, relative_path: str, *, must_exist: bool = True) -> Path:
    """Resolve a path inside the workspace, refusing any escape.

    Backslashes are normalised on every platform so Windows-style traversal
    cannot be smuggled through on Linux, and ``~`` is never expanded.
    """
    if not relative_path or relative_path.strip() == "":
        raise SandboxViolationError("A file path is required")
    normalised = relative_path.replace("\\", "/").strip()
    if normalised.startswith("~"):
        raise SandboxViolationError(
            "Paths starting with '~' are not permitted",
            details={"path": relative_path[:200]},
        )
    if Path(normalised).is_absolute():
        raise SandboxViolationError(
            "Absolute paths are not permitted",
            details={"path": relative_path[:200], "workspace": str(root)},
        )
    candidate = (root / normalised).resolve()
    if candidate != root and root not in candidate.parents:
        raise SandboxViolationError(
            "Path is outside the permitted workspace",
            details={"path": relative_path[:200], "workspace": str(root)},
        )
    if must_exist and not candidate.exists():
        raise ToolExecutionError(
            f"File not found: {relative_path}", details={"path": relative_path[:200]}
        )
    return candidate


def _scrubbed_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(BLOCKED_ENV_PREFIXES):
            continue
        env[key] = value
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["NO_COLOR"] = "1"
    env["CI"] = "1"
    return env


def validate_command(command: str, args: list[str]) -> None:
    """Reject anything outside the allowlist."""
    executable = shutil.which(command) or command
    basename = Path(executable).name
    policy = ALLOWED_COMMANDS.get(basename)
    if policy is None:
        raise PermissionDeniedError(
            f"Command '{basename}' is not allowed in the coding workspace",
            details={"command": basename, "allowed": sorted(ALLOWED_COMMANDS)},
        )
    if len(args) > policy["max_args"]:
        raise PermissionDeniedError(
            f"Too many arguments for '{basename}' (max {policy['max_args']})"
        )
    forbidden = policy.get("forbidden_flags", ())
    for arg in args:
        if arg in forbidden:
            raise PermissionDeniedError(
                f"Flag '{arg}' is not allowed for '{basename}'",
                details={"command": basename},
            )
    allowed_subcommands = policy.get("allowed_subcommands")
    if allowed_subcommands is not None and (not args or args[0] not in allowed_subcommands):
        raise PermissionDeniedError(
            f"'{basename}' may only be used with: {', '.join(sorted(allowed_subcommands))}",
            details={"command": basename},
        )


async def run_command(
    command: str,
    args: list[str],
    *,
    root: Path,
    timeout: float = 120.0,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    env_extra: dict[str, str] | None = None,
) -> CommandResult:
    """Run an allowlisted command inside the workspace."""
    validate_command(command, args)
    executable = shutil.which(command)
    if executable is None:
        raise ToolExecutionError(f"Command '{command}' is not installed on this system")

    env = _scrubbed_env()
    if env_extra:
        env.update(env_extra)

    started = asyncio.get_running_loop().time()
    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        cwd=str(root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolTimeoutError(
            f"Command '{command}' timed out after {timeout:.0f}s",
            details={"command": command},
        ) from exc

    duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
    truncated = False
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if len(stdout) > max_output_bytes:
        stdout = stdout[:max_output_bytes]
        truncated = True
    if len(stderr) > max_output_bytes:
        stderr = stderr[:max_output_bytes]
        truncated = True

    return CommandResult(
        command=f"{command} {' '.join(args)}".strip(),
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        truncated=truncated,
    )


def read_file(root: Path, relative_path: str, *, max_bytes: int = MAX_READ_BYTES) -> str:
    target = resolve_in_workspace(root, relative_path)
    if target.is_dir():
        raise ToolExecutionError(f"'{relative_path}' is a directory")
    if target.stat().st_size > max_bytes:
        raise ToolExecutionError(
            f"File is too large to read ({target.stat().st_size} bytes)",
            details={"path": relative_path[:200]},
        )
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolExecutionError(f"Could not read file: {type(exc).__name__}") from exc


def write_file(root: Path, relative_path: str, content: str) -> int:
    target = resolve_in_workspace(root, relative_path, must_exist=False)
    if target.exists() and target.is_dir():
        raise ToolExecutionError(f"'{relative_path}' is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def list_files(root: Path, relative_path: str = ".", *, limit: int = 500) -> list[dict[str, Any]]:
    target = resolve_in_workspace(root, relative_path or ".")
    entries: list[dict[str, Any]] = []
    for path in sorted(target.rglob("*")):
        if path.is_dir():
            continue
        if any(
            part in {".git", "node_modules", "__pycache__", ".venv", "venv"} for part in path.parts
        ):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {
                "path": str(path.relative_to(root)),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )
        if len(entries) >= limit:
            break
    return entries
