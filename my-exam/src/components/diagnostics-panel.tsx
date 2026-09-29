"use client";

import { useActionState, useEffect, useState } from "react";
import { AlertTriangle, CircleAlert, Eraser, Info, Loader2, ShieldCheck } from "lucide-react";
import { clearDiagnostics } from "@/lib/actions";
import type { DiagEvent, DiagLevel } from "@/lib/diagnostics";
import { Card } from "@/components/ui";

const LEVELS: { key: DiagLevel | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "error", label: "Errors" },
  { key: "warn", label: "Warnings" },
  { key: "info", label: "Info" },
];

const LEVEL_STYLE: Record<DiagLevel, { text: string; chip: string; Icon: typeof Info }> = {
  error: { text: "text-rose-400", chip: "bg-rose-500/10 text-rose-300 border-rose-500/20", Icon: CircleAlert },
  warn: { text: "text-amber-400", chip: "bg-amber-500/10 text-amber-300 border-amber-500/20", Icon: AlertTriangle },
  info: { text: "text-emerald-400", chip: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20", Icon: ShieldCheck },
};

/** Keys worth showing even when the value is 0 or null. */
const INTERESTING = new Set([
  "requested", "created", "reason", "seconds", "perQuestionSec", "rejected",
  "numCtx", "contextWindow", "contextChars", "poolChars", "distinctWindows", "outputTokens", "batch", "batchSize",
  "maxTokens", "finishReason", "model", "provider", "added", "skipped", "hint",
]);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");

/**
 * Fixed UTC format built by hand.
 *
 * `toLocaleString()` is the cause of a hydration mismatch here: the server
 * rendered "Sep 27, 10:54:04 AM" (en-US, UTC) while the browser rendered
 * "27 Sept, 16:24:04" (a different locale and timezone). Formatting from
 * `getUTC*` with a hard-coded month table cannot vary by environment, so the
 * server and the browser always agree.
 */
function fmtUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${pad(d.getUTCDate())} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

/**
 * A timestamp that is deterministic during SSR and the first client render,
 * then upgrades to the reader's own locale once mounted. Swapping text after
 * mount is not a hydration mismatch; differing text between server and client
 * render is.
 */
function Timestamp({ iso }: { iso: string }) {
  const [local, setLocal] = useState<string | null>(null);
  useEffect(() => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return;
    setLocal(
      d.toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
      })
    );
  }, [iso]);
  return <time dateTime={iso}>{local ?? fmtUtc(iso)}</time>;
}

function Details({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([k, v]) => INTERESTING.has(k) && v !== null && v !== "");
  if (entries.length === 0) return null;
  return (
    <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-foreground/55">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-1">
          <dt className="text-foreground/40">{k.replace(/([A-Z])/g, " $1").toLowerCase()}</dt>
          <dd className="font-medium text-foreground/75">
            {k === "rejected" && v && typeof v === "object"
              ? Object.entries(v as Record<string, number>)
                  .sort((a, b) => b[1] - a[1])
                  .map(([reason, n]) => `${reason} (${n})`)
                  .join(" · ")
              : typeof v === "object"
                ? JSON.stringify(v)
                : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function DiagnosticsPanel({
  events,
  filter,
  summary,
}: {
  events: DiagEvent[];
  filter: DiagLevel | "all";
  summary: { info: number; warn: number; error: number };
}) {
  const [state, action, pending] = useActionState(clearDiagnostics, null);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Diagnostics</h2>
          <p className="mt-1 text-xs text-foreground/60">
            What the AI layer actually did, including why a run came back short.
            Last 24 hours: {summary.error} error{summary.error === 1 ? "" : "s"},{" "}
            {summary.warn} warning{summary.warn === 1 ? "" : "s"},{" "}
            {summary.info} info.
          </p>
        </div>
        <form action={action}>
          <button type="submit" disabled={pending || events.length === 0} className="btn btn-secondary">
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eraser className="h-4 w-4" />}
            Clear log
          </button>
        </form>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        {LEVELS.map(({ key, label }) => (
          <a
            key={key}
            href={key === "all" ? "/settings" : `/settings?log=${key}`}
            aria-current={filter === key ? "page" : undefined}
            className={`rounded-full border px-2.5 py-1 text-xs transition ${
              filter === key
                ? "border-foreground/30 bg-foreground/10 text-foreground"
                : "border-white/8 text-foreground/55 hover:bg-foreground/5"
            }`}
          >
            {label}
          </a>
        ))}
      </div>

      {events.length === 0 ? (
        <p className="mt-4 rounded-lg border border-dashed border-white/10 px-3 py-6 text-center text-sm text-foreground/45">
          No {filter === "all" ? "" : `${filter} `}events recorded yet. Generate questions or run a
          connection test, then come back here.
        </p>
      ) : (
        <ol className="mt-4 max-h-[32rem] space-y-2 overflow-y-auto pr-1">
          {events.map((e) => {
            const { text, chip, Icon } = LEVEL_STYLE[e.level];
            return (
              <li key={e.id} className="rounded-lg border border-white/8 bg-black/20 px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${chip}`}>
                    <Icon className="h-3 w-3" /> {e.level}
                  </span>
                  <span className="rounded bg-foreground/8 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-foreground/50">
                    {e.kind}
                  </span>
                  <time dateTime={e.createdAt} className="ml-auto text-[11px] text-foreground/40">
                    <Timestamp iso={e.createdAt} />
                  </time>
                </div>
                <p className={`mt-1.5 text-sm ${e.level === "error" ? text : "text-foreground/85"}`}>
                  {e.message}
                </p>
                <Details details={e.details} />
              </li>
            );
          })}
        </ol>
      )}

      {state?.ok && <p className="mt-3 text-xs text-emerald-400">Log cleared.</p>}
    </Card>
  );
}
