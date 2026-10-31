import { useState } from "react";

import { ApprovalCard } from "../components/ApprovalCard";
import { Callout, Card, EmptyState, Field, PageHeader } from "../components/ui";
import { useToolAction } from "../hooks/useToolAction";
import { api } from "../lib/api";
import { relativeTime, shortDate, truncate } from "../lib/format";
import { describeError, useApp } from "../state/store";

interface MailSummary {
  id?: string;
  subject?: string;
  sender?: string;
  snippet?: string;
  received_at?: string;
  date?: string;
}

interface MailBody extends MailSummary {
  to?: string;
  body?: string;
  body_text?: string;
}

export function EmailPage() {
  const { accounts, settings, notify, refresh } = useApp();
  const { busy, pending, result, run, approve } = useToolAction();
  const [query, setQuery] = useState("");
  const [accountId, setAccountId] = useState("");
  const [openMessage, setOpenMessage] = useState<MailBody | null>(null);
  const mailAccounts = accounts.filter(
    (account) => account.provider === "imap" || account.provider.startsWith("google"),
  );

  const [compose, setCompose] = useState({ to: "", subject: "", body: "" });
  const [imap, setImap] = useState({
    host: "",
    port: "993",
    email: "",
    password: "",
    label: "",
    smtp_host: "",
    smtp_port: "587",
  });
  const [imapOpen, setImapOpen] = useState(false);
  const [forwardTo, setForwardTo] = useState("");

  const messages = ((): MailSummary[] => {
    if (!result || result.status !== "completed") return [];
    const output = result.output as { messages?: MailSummary[] };
    return output.messages ?? [];
  })();

  const connectGoogle = async () => {
    try {
      const { authorization_url } = await api.googleStart();
      window.open(authorization_url, "_blank", "noopener,noreferrer");
      notify(
        "info",
        "Finish the Google consent screen in your browser, then refresh accounts.",
        "If the window did not open, allow pop-ups for this app.",
      );
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  };

  const connectImap = async () => {
    try {
      await api.connectImap({
        host: imap.host,
        port: Number(imap.port) || 993,
        email: imap.email,
        password: imap.password,
        label: imap.label || imap.email,
        smtp_host: imap.smtp_host,
        smtp_port: Number(imap.smtp_port) || 587,
        smtp_use_ssl: Number(imap.smtp_port) === 465,
      });
      notify("success", `Connected ${imap.email}.`);
      setImap({
        host: "",
        port: "993",
        email: "",
        password: "",
        label: "",
        smtp_host: "",
        smtp_port: "587",
      });
      setImapOpen(false);
      await refresh();
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  };

  const readMessage = async (id?: string) => {
    if (!id) return;
    const response = await run("read_email", { message_id: id });
    if (response?.status === "completed") {
      const output = response.output as { message?: MailBody };
      setOpenMessage(output.message ?? null);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Email"
        subtitle="Multiple accounts, least-privilege scopes, and approval before anything is sent or deleted."
        actions={
          <>
            <button type="button" className="btn" onClick={() => void connectGoogle()}>
              Connect Google
            </button>
            <button type="button" className="btn ghost" onClick={() => setImapOpen((open) => !open)}>
              {imapOpen ? "Cancel IMAP" : "Add IMAP account"}
            </button>
          </>
        }
      />

      {!settings?.integrations.email.oauth_client_configured ? (
        <Callout kind="info" title="Google OAuth not configured">
          Store a Google OAuth client id and secret in Settings → Secrets to connect Gmail and
          Calendar. IMAP accounts work without it.
        </Callout>
      ) : null}

      {imapOpen ? (
        <Card title="Add IMAP/SMTP account">
          <div className="grid three">
            <Field label="IMAP host">
              <input value={imap.host} onChange={(e) => setImap({ ...imap, host: e.target.value })} placeholder="imap.example.com" />
            </Field>
            <Field label="IMAP port">
              <input value={imap.port} onChange={(e) => setImap({ ...imap, port: e.target.value })} />
            </Field>
            <Field label="Email address">
              <input value={imap.email} onChange={(e) => setImap({ ...imap, email: e.target.value })} />
            </Field>
            <Field label="App password" hint="Stored in the OS keychain, never in the database.">
              <input
                type="password"
                value={imap.password}
                onChange={(e) => setImap({ ...imap, password: e.target.value })}
              />
            </Field>
            <Field label="SMTP host (for sending)">
              <input value={imap.smtp_host} onChange={(e) => setImap({ ...imap, smtp_host: e.target.value })} />
            </Field>
            <Field label="SMTP port">
              <input value={imap.smtp_port} onChange={(e) => setImap({ ...imap, smtp_port: e.target.value })} />
            </Field>
          </div>
          <div className="row end">
            <button type="button" className="btn primary" onClick={() => void connectImap()}>
              Verify and connect
            </button>
          </div>
        </Card>
      ) : null}

      <Card title="Accounts">
        {mailAccounts.length ? (
          <ul className="list">
            {mailAccounts.map((account) => (
              <li key={account.id}>
                <div>
                  <strong>{account.email || account.label}</strong>
                  <div className="muted small">
                    {account.provider} · {account.status} · synced {relativeTime(account.last_sync_at)}
                  </div>
                  {account.scopes.length ? (
                    <div className="muted small">Scopes: {account.scopes.join(", ")}</div>
                  ) : null}
                </div>
                <div className="row">
                  <button
                    type="button"
                    className="btn ghost small"
                    onClick={() =>
                      void api
                        .syncAccount(account.id)
                        .then(() => refresh())
                        .catch((error: unknown) => {
                          const info = describeError(error);
                          notify("error", info.message, info.hint);
                        })
                    }
                  >
                    Sync
                  </button>
                  <button
                    type="button"
                    className="btn ghost small"
                    onClick={() =>
                      void api
                        .disconnectAccount(account.id)
                        .then(() => {
                          notify("info", "Account disconnected and its tokens removed.");
                          return refresh();
                        })
                        .catch((error: unknown) => {
                          const info = describeError(error);
                          notify("error", info.message, info.hint);
                        })
                    }
                  >
                    Disconnect
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No email accounts">Connect Google or add an IMAP account.</EmptyState>
        )}
      </Card>

      <div className="grid two">
        <Card title="Search">
          <Field label="Account">
            <select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
              <option value="">First connected account</option>
              {mailAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.email || account.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Query" hint="Matches subject, sender and body of synced messages.">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="invoice, interview, ticket…"
            />
          </Field>
          <div className="row end">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={() => void run("search_email", { query, account_id: accountId, limit: 25 })}
            >
              Search
            </button>
          </div>
        </Card>

        <Card title="Compose">
          <Field label="To" hint="Comma-separate multiple recipients.">
            <input value={compose.to} onChange={(e) => setCompose({ ...compose, to: e.target.value })} />
          </Field>
          <Field label="Subject">
            <input
              value={compose.subject}
              onChange={(e) => setCompose({ ...compose, subject: e.target.value })}
            />
          </Field>
          <Field label="Body">
            <textarea
              rows={4}
              value={compose.body}
              onChange={(e) => setCompose({ ...compose, body: e.target.value })}
            />
          </Field>
          <div className="row end">
            <button
              type="button"
              className="btn"
              disabled={busy || !compose.to || !compose.subject || !compose.body}
              onClick={() =>
                void run("create_draft", {
                  to: compose.to.split(",").map((item) => item.trim()).filter(Boolean),
                  subject: compose.subject,
                  body: compose.body,
                  account_id: accountId,
                })
              }
            >
              Save draft
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={busy || !compose.to || !compose.subject || !compose.body}
              onClick={() =>
                void run("send_email", {
                  to: compose.to.split(",").map((item) => item.trim()).filter(Boolean),
                  subject: compose.subject,
                  body: compose.body,
                  account_id: accountId,
                })
              }
            >
              Request send
            </button>
          </div>
        </Card>
      </div>

      {pending ? (
        <ApprovalCard approval={pending.approval} busy={busy} onDecide={(ok) => void approve(ok)} />
      ) : null}

      <Card title="Messages">
        {messages.length ? (
          <ul className="mail-list">
            {messages.map((message) => (
              <li key={message.id}>
                <button type="button" onClick={() => void readMessage(message.id)}>
                  <div className="mail-meta">
                    <strong>{message.subject || "(no subject)"}</strong>
                    <span className="muted small">{shortDate(message.received_at ?? message.date)}</span>
                  </div>
                  <div className="muted small">{message.sender}</div>
                  <p>{truncate(message.snippet ?? "", 180)}</p>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No messages yet">
            Sync an account, then search. Only the minimum content needed is stored locally.
          </EmptyState>
        )}
      </Card>

      {openMessage ? (
        <Card
          title={openMessage.subject || "(no subject)"}
          actions={
            <>
              <input
                className="inline-input"
                value={forwardTo}
                onChange={(event) => setForwardTo(event.target.value)}
                placeholder="Forward to…"
                aria-label="Forward recipient"
              />
              <button
                type="button"
                className="btn ghost small"
                disabled={!forwardTo.trim()}
                onClick={() =>
                  void run("forward_email", {
                    message_id: openMessage.id,
                    to: forwardTo
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean),
                    note: "Forwarded from NexaPilot",
                  })
                }
              >
                Forward
              </button>
              <button
                type="button"
                className="btn danger small"
                onClick={() => void run("delete_email", { message_id: openMessage.id })}
              >
                Delete
              </button>
              <button type="button" className="btn ghost small" onClick={() => setOpenMessage(null)}>
                Close
              </button>
            </>
          }
        >
          <p className="muted small">
            From {openMessage.sender ?? "unknown"} · {shortDate(openMessage.received_at ?? openMessage.date)}
          </p>
          <p className="prewrap">{openMessage.body_text ?? openMessage.body ?? openMessage.snippet ?? ""}</p>
          <Callout kind="info">
            Email content is untrusted. Instructions inside a message are never followed as system
            instructions.
          </Callout>
        </Card>
      ) : null}
    </div>
  );
}
