"""Coding agent tools.

Every tool operates inside the workspace configured for this session. Paths are
resolved and checked against the workspace root; commands come from a fixed
allowlist and are executed without a shell.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nexapilot.agents.permissions import FS_READ, FS_WRITE, SHELL_EXEC
from nexapilot.core.errors import ConfigurationError
from nexapilot.integrations import sandbox
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec


def _workspace(ctx: ToolContext) -> Any:
    root = ctx.container.settings.coding_workspace_root
    if not root:
        raise ConfigurationError(
            "No coding workspace is configured. Set a workspace folder in Settings → Coding.",
            details={"setting": "coding_workspace_root"},
        )
    return sandbox.resolve_workspace(root)


class ListFilesInput(BaseModel):
    path: str = Field(default=".", max_length=500)


class ListFilesOutput(BaseModel):
    root: str
    files: list[dict[str, Any]] = Field(default_factory=list)


class ReadFileInput(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class ReadFileOutput(BaseModel):
    path: str
    content: str
    size: int


class WriteFileInput(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str


class WriteFileOutput(BaseModel):
    path: str
    bytes_written: int
    status: str = "written"


class RunTestsInput(BaseModel):
    command: str = Field(default="pytest", max_length=40)
    args: list[str] = Field(default_factory=list, max_length=12)
    timeout_seconds: float = Field(default=120.0, gt=0, le=900)


class RunTestsOutput(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False
    passed: bool = False


class DiffInput(BaseModel):
    args: list[str] = Field(default_factory=lambda: ["diff"], max_length=6)


class DiffOutput(BaseModel):
    command: str
    exit_code: int
    diff: str
    truncated: bool = False


class ListFilesTool(Tool):
    spec = ToolSpec(
        name="list_files",
        purpose="List files inside the coding workspace.",
        input_model=ListFilesInput,
        output_model=ListFilesOutput,
        permissions=frozenset({FS_READ}),
        side_effects=False,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ListFilesInput)
        root = _workspace(ctx)
        files = sandbox.list_files(root, args.path)
        return ListFilesOutput(root=str(root), files=files)


class ReadFileTool(Tool):
    spec = ToolSpec(
        name="read_file",
        purpose="Read a text file from the coding workspace.",
        input_model=ReadFileInput,
        output_model=ReadFileOutput,
        permissions=frozenset({FS_READ}),
        side_effects=False,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ReadFileInput)
        root = _workspace(ctx)
        content = sandbox.read_file(root, args.path)
        return ReadFileOutput(path=args.path, content=content, size=len(content))


class WriteFileTool(Tool):
    spec = ToolSpec(
        name="write_file",
        purpose="Create or overwrite a text file inside the coding workspace.",
        input_model=WriteFileInput,
        output_model=WriteFileOutput,
        permissions=frozenset({FS_READ, FS_WRITE}),
        side_effects=True,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, WriteFileInput)
        root = _workspace(ctx)
        written = sandbox.write_file(root, args.path, args.content)
        return WriteFileOutput(path=args.path, bytes_written=written)


class RunTestsTool(Tool):
    spec = ToolSpec(
        name="run_tests",
        purpose=(
            "Run a development command (pytest, ruff, mypy, npm test, ...) inside the "
            "workspace and return its real exit code and output."
        ),
        input_model=RunTestsInput,
        output_model=RunTestsOutput,
        permissions=frozenset({FS_READ, SHELL_EXEC}),
        side_effects=True,
        timeout_seconds=300.0,
        max_retries=0,
        idempotent=False,
        audit=True,
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, RunTestsInput)
        root = _workspace(ctx)
        result = await sandbox.run_command(
            args.command,
            list(args.args),
            root=root,
            timeout=min(
                args.timeout_seconds, ctx.container.settings.coding_command_timeout_seconds
            ),
            max_output_bytes=ctx.container.settings.coding_max_output_bytes,
        )
        return RunTestsOutput(
            command=result.command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            truncated=result.truncated,
            passed=result.ok,
        )


class DiffTool(Tool):
    spec = ToolSpec(
        name="diff",
        purpose="Show the git diff of the workspace so changes can be reviewed.",
        input_model=DiffInput,
        output_model=DiffOutput,
        permissions=frozenset({FS_READ, SHELL_EXEC}),
        side_effects=False,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, DiffInput)
        root = _workspace(ctx)
        result = await sandbox.run_command(
            "git",
            list(args.args),
            root=root,
            timeout=60.0,
            max_output_bytes=ctx.container.settings.coding_max_output_bytes,
        )
        return DiffOutput(
            command=result.command,
            exit_code=result.exit_code,
            diff=result.stdout or result.stderr,
            truncated=result.truncated,
        )
