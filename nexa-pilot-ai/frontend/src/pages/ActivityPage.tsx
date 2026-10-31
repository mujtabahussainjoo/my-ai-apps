import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "../components/ApprovalCard";
import { EmptyState, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { relativeTime, shortDate, truncate } from "../lib/format";
import type { ActivityEntry, Approval, ToolInfo } from "../lib/types";
import { describeError, useApp } from "../state/store";

export function ActivityPage() {
  const { approvals, notify, refresh, refreshApprovals } = useApp();
  const [entries, setEntries] = useState<ActivityEntry[]>([]);
  const [history, setHistory] = useState<Approval[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [busy, setBusy] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const [activity, decided, toolList] = await Promise.all([
        api.activity(100),
        api.approvals("executed"),
        api.tools(),
      ]);
      setEntries(activity);
      setHistory(decided);
      setTools(toolList.filter((tool) => tool.requires_approval));
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (approval: Approval, approved: boolean) => {
    setBusy(approval.id);
    try {
      await api.decideApproval(approval.id, approved);
      if (approved) {
        await api.resumeApproval(approval.id);
        notify("success", "Approved action executed.");
      } else {
        notify("info", "Action rejected.");
      }
      await Promise.all([refresh(), refreshApprovals(), load()]);
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Activity"
        subtitle="Every run and every approval is recorded, including errors and cancellations."
        actions={
          <button type="button" className="btn ghost" onClick={() => void load()}>
            Refresh
          </button>
        }
      />

      <section className="card">
        <header className="card-header">
          <h2>Pending approvals</h2>
          <span className="badge">{approvals.length}</span>
        </header>
        {approvals.length ? (
          <div className="stack">
            {approvals.map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                busy={busy === approval.id}
                onDecide={(approved) => void decide(approval, approved)}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="Nothing waiting">Actions that need your consent appear here.</EmptyState>
        )}
      </section>

      <section className="card">
        <header className="card-header">
          <h2>Task history</h2>
          <span className="badge">{entries.length}</span>
        </header>
        {entries.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Status</th>
                <th>Model</th>
                <th>Steps</th>
                <th>Started</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.workflow}</td>
                  <td>
                    <span
                      className={`badge ${
                        entry.status === "completed"
                          ? "badge-low"
                          : entry.status === "failed"
                            ? "badge-high"
                            : "badge-warn"
                      }`}
                    >
                      {entry.status}
                    </span>
                  </td>
                  <td className="mono small">{entry.model || "—"}</td>
                  <td>{entry.steps}</td>
                  <td className="small">{shortDate(entry.started_at)}</td>
                  <td className="small error-text">{truncate(entry.error || "", 80)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="No runs yet">Start in Chat or a specialised workflow.</EmptyState>
        )}
      </section>

      <div className="grid two">
        <section className="card">
          <header className="card-header">
            <h2>Executed approvals</h2>
          </header>
          {history.length ? (
            <ul className="list compact">
              {history.map((item) => (
                <li key={item.id}>
                  <div>
                    <strong>{item.title || item.action}</strong>
                    <div className="muted small">
                      {item.action} · {item.target || "no target"} · decided{" "}
                      {relativeTime(item.created_at)}
                    </div>
                  </div>
                  <span className="badge badge-low">executed</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">Approved actions show up here after execution.</p>
          )}
        </section>

        <section className="card">
          <header className="card-header">
            <h2>Always gated</h2>
          </header>
          <ul className="list compact">
            {tools.map((tool) => (
              <li key={tool.name}>
                <div>
                  <strong className="mono">{tool.name}</strong>
                  <div className="muted small">{tool.purpose}</div>
                </div>
                <span className={`badge badge-${tool.risk}`}>{tool.risk}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
