import { useEffect, useState } from "react";

import { Callout, Card, EmptyState, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { relativeTime, titleCase } from "../lib/format";
import type { Account, ToolInfo } from "../lib/types";
import { describeError, useApp } from "../state/store";

const PERMISSION_GROUPS: Array<{ label: string; permissions: string[]; note: string }> = [
  {
    label: "Web research",
    permissions: ["web:search"],
    note: "Fetches pages with SSRF protection; never bypasses paywalls or access controls.",
  },
  {
    label: "Email",
    permissions: ["email:read", "email:send", "email:modify"],
    note: "Reading is scoped per account; send, forward and delete always require approval.",
  },
  {
    label: "Calendar",
    permissions: ["calendar:read", "calendar:write"],
    note: "Creating events requires approval; inferred events keep their provenance.",
  },
  {
    label: "Travel",
    permissions: ["travel:search"],
    note: "Discovery only. Booking and payment are never automatic.",
  },
  {
    label: "Finance",
    permissions: ["finance:read", "finance:trade"],
    note: "Quotes show source and delay; each order needs a fresh approval.",
  },
  {
    label: "Coding",
    permissions: ["fs:read", "fs:write", "shell:exec"],
    note: "Confined to the chosen workspace with an allowlisted command set.",
  },
];

export function AccountsPage() {
  const { accounts, notify, refresh } = useApp();
  const [tools, setTools] = useState<ToolInfo[]>([]);

  useEffect(() => {
    void api
      .tools()
      .then(setTools)
      .catch(() => setTools([]));
  }, []);

  const disconnect = async (account: Account) => {
    try {
      await api.disconnectAccount(account.id);
      notify("info", `${account.label || account.email} disconnected.`);
      await refresh();
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Connected accounts"
        subtitle="Least-privilege scopes, per-account tokens, and a way to revoke access at any time."
      />

      <Card title="Accounts">
        {accounts.length ? (
          <ul className="list">
            {accounts.map((account) => (
              <li key={account.id}>
                <div>
                  <strong>{account.label || account.email || account.id}</strong>
                  <div className="muted small">
                    {titleCase(account.provider)} · {account.email} · {account.auth_mode || "oauth"} ·
                    synced {relativeTime(account.last_sync_at)}
                  </div>
                  {account.scopes.length ? (
                    <div className="scopes">
                      {account.scopes.map((scope) => (
                        <span key={scope} className="badge mono small">
                          {scope}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {account.error ? <p className="error-text small">{account.error}</p> : null}
                </div>
                <div className="row">
                  <span className={`badge ${account.status === "connected" ? "badge-low" : "badge-high"}`}>
                    {account.status}
                  </span>
                  <button type="button" className="btn danger small" onClick={() => void disconnect(account)}>
                    Disconnect
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No accounts connected">
            Add email or calendar accounts from the Email page. Tokens are stored in the OS credential
            vault and can be removed here at any time.
          </EmptyState>
        )}
      </Card>

      <Card title="Permission model">
        <div className="grid two">
          {PERMISSION_GROUPS.map((group) => (
            <div key={group.label} className="permission-group">
              <strong>{group.label}</strong>
              <div className="row wrap">
                {group.permissions.map((permission) => (
                  <span key={permission} className="badge mono small">
                    {permission}
                  </span>
                ))}
              </div>
              <p className="muted small">{group.note}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Tools that always ask">
        {tools.filter((tool) => tool.requires_approval).length ? (
          <table className="table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Action</th>
                <th>Risk</th>
                <th>Permissions</th>
              </tr>
            </thead>
            <tbody>
              {tools
                .filter((tool) => tool.requires_approval)
                .map((tool) => (
                  <tr key={tool.name}>
                    <td className="mono">{tool.name}</td>
                    <td className="mono small">{tool.approval_action}</td>
                    <td>
                      <span className={`badge badge-${tool.risk}`}>{tool.risk}</span>
                    </td>
                    <td className="mono small">{tool.permissions.join(", ")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">Tool metadata unavailable.</p>
        )}
        <Callout kind="info" title="Approvals are enforced in code">
          The gate lives in the agent loop and the tool endpoint, not in the prompt. A model cannot
          talk its way past it.
        </Callout>
      </Card>
    </div>
  );
}
