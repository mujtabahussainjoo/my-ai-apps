import { useCallback, useEffect, useState } from "react";

import { Callout, Card, EmptyState, Field, PageHeader } from "../components/ui";
import { useToolAction } from "../hooks/useToolAction";
import { api } from "../lib/api";
import { relativeTime } from "../lib/format";
import { describeError, useApp } from "../state/store";

interface FileEntry {
  path: string;
  size: number;
  modified_at: number;
}

interface TestOutput {
  command: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
  passed: boolean;
  timed_out: boolean;
  truncated: boolean;
}

const DEV_COMMANDS = ["pytest", "ruff", "mypy", "npm", "node", "go", "cargo", "make"];

export function CodingPage() {
  const { settings, notify, refresh } = useApp();
  const { busy, result, run } = useToolAction();
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [root, setRoot] = useState("");
  const [selected, setSelected] = useState("");
  const [content, setContent] = useState("");
  const [command, setCommand] = useState("pytest");
  const [args, setArgs] = useState("-q");

  const loadFiles = useCallback(async () => {
    try {
      const response = await api.codingFiles(".");
      setFiles(response.files as unknown as FileEntry[]);
      setRoot(response.root);
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  }, [notify]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const open = async (path: string) => {
    const response = await run("read_file", { path });
    if (response?.status === "completed") {
      setSelected(path);
      setContent(String((response.output as { content?: string }).content ?? ""));
    }
  };

  const save = async () => {
    const response = await run("write_file", { path: selected, content });
    if (response?.status === "completed") {
      notify("success", `Saved ${selected}.`);
      await loadFiles();
    }
  };

  const execute = async () => {
    const response = await run("run_tests", {
      command,
      args: args.split(/\s+/).filter(Boolean),
      timeout_seconds: 180,
    });
    if (response?.status === "completed") {
      await refresh();
    }
  };

  const output = ((): TestOutput | null => {
    if (result?.status !== "completed") return null;
    const value = result.output as unknown as TestOutput;
    return typeof value.exit_code === "number" ? value : null;
  })();

  return (
    <div className="page">
      <PageHeader
        title="Coding"
        subtitle="Inspect, edit and test a project inside a restricted workspace."
        actions={
          <button type="button" className="btn ghost" onClick={() => void loadFiles()}>
            Refresh files
          </button>
        }
      />

      {!settings?.coding.workspace_configured ? (
        <Callout kind="warn" title="Choose a workspace">
          Set a workspace folder in Settings → Coding. NexaPilot rejects paths outside it, including
          symlink escapes.
        </Callout>
      ) : (
        <Callout kind="info" title="Restricted by design">
          Commands are limited to a developer allowlist ({DEV_COMMANDS.join(", ")}), paths are confined
          to {root || settings.coding.workspace_root}, and secrets are scrubbed from the environment.
        </Callout>
      )}

      <div className="coder">
        <Card title="Files" className="file-panel">
          {files.length ? (
            <ul className="file-list">
              {files.map((file) => (
                <li key={file.path}>
                  <button
                    type="button"
                    className={file.path === selected ? "active" : ""}
                    onClick={() => void open(file.path)}
                  >
                    <span className="mono">{file.path}</span>
                    <span className="muted small">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No files">The workspace is empty or not readable.</EmptyState>
          )}
        </Card>

        <Card
          title={selected || "Editor"}
          className="editor-panel"
          actions={
            selected ? (
              <button type="button" className="btn primary small" disabled={busy} onClick={() => void save()}>
                Save
              </button>
            ) : null
          }
        >
          {selected ? (
            <>
              <textarea
                className="editor"
                value={content}
                onChange={(event) => setContent(event.target.value)}
                spellCheck={false}
                rows={20}
              />
              <p className="muted small">
                {content.length.toLocaleString()} characters · writes are confirmed with a summary
              </p>
            </>
          ) : (
            <EmptyState title="Select a file">Read a file to inspect or edit it.</EmptyState>
          )}
        </Card>
      </div>

      <Card title="Run checks">
        <div className="row wrap">
          <Field label="Command">
            <select value={command} onChange={(event) => setCommand(event.target.value)}>
              {DEV_COMMANDS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Arguments">
            <input value={args} onChange={(event) => setArgs(event.target.value)} placeholder="-q" />
          </Field>
          <button type="button" className="btn primary" disabled={busy} onClick={() => void execute()}>
            Run
          </button>
        </div>

        {output ? (
          <div className="test-output">
            <div className="row">
              <span className={`badge ${output.exit_code === 0 ? "badge-low" : "badge-high"}`}>
                exit {output.exit_code}
              </span>
              <span className="muted small">
                {output.duration_ms} ms{output.truncated ? " · output truncated" : ""}
                {output.timed_out ? " · timed out" : ""}
              </span>
            </div>
            <pre>{output.stdout || output.stderr || "No output."}</pre>
            {output.stdout && output.stderr ? <pre className="stderr">{output.stderr}</pre> : null}
          </div>
        ) : null}
      </Card>

      {files.length ? (
        <p className="muted small">
          {files.length} files · last workspace scan {relativeTime(new Date().toISOString())}
        </p>
      ) : null}
    </div>
  );
}
