import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "../components/ApprovalCard";
import { Callout, Card, EmptyState, Field, PageHeader } from "../components/ui";
import { useToolAction } from "../hooks/useToolAction";
import { api } from "../lib/api";
import { shortDate, titleCase } from "../lib/format";
import { describeError, useApp } from "../state/store";

interface CalendarEvent {
  id: string;
  title: string;
  start_at: string;
  end_at: string;
  location?: string;
  description?: string;
  source: string;
  confidence?: number;
  account_id?: string;
}

function isoLocal(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function CalendarPage() {
  const { accounts, notify, refresh } = useApp();
  const { busy, pending, run, approve } = useToolAction();
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [form, setForm] = useState({
    title: "",
    start: isoLocal(new Date(Date.now() + 3_600_000)),
    end: isoLocal(new Date(Date.now() + 5_400_000)),
    location: "",
    description: "",
    account_id: "",
  });

  const load = useCallback(async () => {
    const start = new Date();
    const end = new Date(Date.now() + 30 * 86_400_000);
    try {
      setEvents((await api.calendarEvents(start.toISOString(), end.toISOString())) as unknown as CalendarEvent[]);
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const sync = async () => {
    try {
      const response = await api.calendarSync();
      notify("success", "Calendar sync finished.");
      if (response.email_events) {
        notify("info", "Email-derived events were re-evaluated.");
      }
      await Promise.all([load(), refresh()]);
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  };

  const create = async () => {
    const response = await run("create_event", {
      title: form.title,
      start_at: new Date(form.start).toISOString(),
      end_at: new Date(form.end).toISOString(),
      location: form.location,
      description: form.description,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      account_id: form.account_id,
    });
    if (response?.status === "completed") {
      notify("success", "Event created.");
      await load();
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Calendar"
        subtitle="Connected calendars plus events inferred from email, each with provenance and confidence."
        actions={
          <button type="button" className="btn" onClick={() => void sync()}>
            Sync calendars
          </button>
        }
      />

      <Callout kind="info" title="Created events need approval">
        NexaPilot never writes to a calendar silently. Inferred events stay clearly labelled until
        you confirm them.
      </Callout>

      <div className="grid two">
        <Card title="Upcoming (30 days)">
          {events.length ? (
            <ul className="timeline">
              {events.map((event) => (
                <li key={event.id}>
                  <div className="timeline-time">
                    <strong>{new Date(event.start_at).toLocaleDateString()}</strong>
                    <span className="muted small">
                      {new Date(event.start_at).toLocaleTimeString(undefined, {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <div>
                    <strong>{event.title}</strong>
                    {event.location ? <div className="muted small">{event.location}</div> : null}
                    <div className="row wrap">
                      <span className={`badge ${event.source.includes("email") ? "badge-info" : ""}`}>
                        {titleCase(event.source)}
                      </span>
                      {typeof event.confidence === "number" ? (
                        <span className="badge">confidence {Math.round(event.confidence * 100)}%</span>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nothing scheduled">
              Connect a Google account and sync, or let the email agent extract travel, interviews and
              deadlines.
            </EmptyState>
          )}
        </Card>

        <Card title="Create event">
          <Field label="Title">
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <div className="grid two">
            <Field label="Starts">
              <input
                type="datetime-local"
                value={form.start}
                onChange={(e) => setForm({ ...form, start: e.target.value })}
              />
            </Field>
            <Field label="Ends">
              <input
                type="datetime-local"
                value={form.end}
                onChange={(e) => setForm({ ...form, end: e.target.value })}
              />
            </Field>
          </div>
          <Field label="Location">
            <input
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
            />
          </Field>
          <Field label="Calendar account">
            <select
              value={form.account_id}
              onChange={(e) => setForm({ ...form, account_id: e.target.value })}
            >
              <option value="">Default connected account</option>
              {accounts
                .filter((account) => account.provider.startsWith("google"))
                .map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.label || account.email}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Notes">
            <textarea
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Field>
          <div className="row end">
            <button
              type="button"
              className="btn primary"
              disabled={busy || !form.title}
              onClick={() => void create()}
            >
              Request creation
            </button>
          </div>
          <p className="muted small">Timezone: {Intl.DateTimeFormat().resolvedOptions().timeZone}</p>
        </Card>
      </div>

      {pending ? (
        <ApprovalCard approval={pending.approval} busy={busy} onDecide={(ok) => void approve(ok)} />
      ) : null}

      {events.length ? (
        <p className="muted small">Window refreshed {shortDate(new Date().toISOString())}.</p>
      ) : null}
    </div>
  );
}
