import { Pool } from "pg";

declare global {
  var __examPool: Pool | undefined;
}

const globalPool = globalThis as unknown as { __examPool?: Pool };

export const pool =
  globalPool.__examPool ??
  new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 10,
  });

if (process.env.NODE_ENV !== "production") globalPool.__examPool = pool;

export type Row = Record<string, unknown>;

export async function query<T extends Row = Row>(
  text: string,
  params: unknown[] = []
): Promise<T[]> {
  const res = await pool.query<T>(text, params as never[]);
  return res.rows;
}

export async function queryOne<T extends Row = Row>(
  text: string,
  params: unknown[] = []
): Promise<T | null> {
  const res = await pool.query<T>(text, params as never[]);
  return res.rows[0] ?? null;
}

/** Transforms snake_case DB rows into camelCase objects. */
export function camel<T extends Row = Row>(row: T): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    const key = k.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
    out[key] = v;
  }
  return out;
}

export function camels<T extends Row = Row>(rows: T[]): Record<string, unknown>[] {
  return rows.map(camel);
}

export async function now(): Promise<Date> {
  const [r] = await query<{ now: Date }>("SELECT now() AS now");
  return r.now;
}