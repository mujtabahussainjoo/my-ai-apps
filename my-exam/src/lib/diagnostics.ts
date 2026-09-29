/**
 * A user-visible record of what the AI layer actually did and why it failed.
 *
 * Errors used to exist only in the terminal, which meant a generation that
 * returned 1 of 15 questions could only be explained by guessing. Every
 * notable AI event is written here so the Settings page can show the real
 * reason — including the reject breakdown and truncation warnings that are
 * invisible in the UI.
 *
 * Recording must never break the feature it is describing, so every failure
 * here is swallowed.
 */
import { query } from "@/lib/db";

export type DiagLevel = "info" | "warn" | "error";
export type DiagKind = "generate" | "ai-config" | "upload" | "system";

export type DiagEvent = {
  id: string;
  level: DiagLevel;
  kind: DiagKind;
  message: string;
  details: Record<string, unknown>;
  createdAt: string;
};

const MAX_MESSAGE = 2000;

/** Trim anything unbounded so one bad payload cannot bloat the table. */
function clip(value: unknown): unknown {
  if (typeof value === "string") return value.slice(0, MAX_MESSAGE);
  if (Array.isArray(value)) return value.slice(0, 50).map(clip);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>).slice(0, 30)) {
      out[k] = clip(v);
    }
    return out;
  }
  return value;
}

export async function recordEvent(
  userId: string | null | undefined,
  level: DiagLevel,
  kind: DiagKind,
  message: string,
  details: Record<string, unknown> = {}
): Promise<void> {
  if (!userId) return;
  try {
    await query(
      `INSERT INTO diagnostic_events (user_id, level, kind, message, details)
       VALUES ($1, $2, $3, $4, $5::jsonb)`,
      [userId, level, kind, message.slice(0, MAX_MESSAGE), JSON.stringify(clip(details))]
    );
  } catch {
    // Diagnostics are best-effort; never fail a generation because logging did.
  }
}

export async function listEvents(
  userId: string,
  opts: { limit?: number; level?: DiagLevel | "all" } = {}
): Promise<DiagEvent[]> {
  const limit = Math.min(Math.max(opts.limit ?? 100, 1), 500);
  const rows = await query<{
    id: string;
    level: DiagLevel;
    kind: DiagKind;
    message: string;
    details: Record<string, unknown>;
    created_at: Date;
  }>(
    `SELECT id, level, kind, message, details, created_at
       FROM diagnostic_events
      WHERE user_id = $1 AND ($2::text IS NULL OR level = $2)
      ORDER BY created_at DESC, id DESC
      LIMIT $3`,
    [userId, opts.level && opts.level !== "all" ? opts.level : null, limit]
  );
  return rows.map((r) => ({
    id: String(r.id),
    level: r.level,
    kind: r.kind,
    message: r.message,
    details: (r.details ?? {}) as Record<string, unknown>,
    createdAt: r.created_at instanceof Date ? r.created_at.toISOString() : String(r.created_at),
  }));
}

export async function clearEvents(userId: string): Promise<void> {
  await query(`DELETE FROM diagnostic_events WHERE user_id = $1`, [userId]);
}

/** Counts for the last day, for the summary cards. */
export async function eventSummary(
  userId: string
): Promise<{ info: number; warn: number; error: number }> {
  const rows = await query<{ level: DiagLevel; n: number }>(
    `SELECT level, count(*)::int n FROM diagnostic_events
      WHERE user_id = $1 AND created_at > now() - interval '1 day'
      GROUP BY level`,
    [userId]
  );
  const out = { info: 0, warn: 0, error: 0 };
  for (const r of rows) out[r.level] = r.n;
  return out;
}
