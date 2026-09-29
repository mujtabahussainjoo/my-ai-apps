/**
 * Dev server wrapper.
 *
 * Runs `next dev` and, once the server is ready, warm-compiles every app
 * route so the first client-side navigation isn't a slow on-demand
 * Turbopack compile (which surfaces as transient "Failed to fetch" errors
 * in the browser router).
 *
 * The protected routes are compiled with a throwaway signed session for the
 * newest database user. If the database or session secret isn't available,
 * only the public pages are warmed and the server still runs normally.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { config as loadEnv } from "dotenv";
import { Pool } from "pg";
import { SignJWT } from "jose";

loadEnv({ quiet: true });

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const nextCli = path.join(repoRoot, "node_modules", "next", "dist", "bin", "next");

const NAV_ROUTES = [
  "/dashboard",
  "/exams",
  "/materials",
  "/question-bank",
  "/quiz",
  "/mock",
  "/flashcards",
  "/interview",
  "/assistant",
  "/settings",
];

const args = ["dev", ...process.argv.slice(2)];
const child = spawn("node", [nextCli, ...args], {
  cwd: repoRoot,
  stdio: ["inherit", "pipe", "inherit"],
  env: process.env,
});

let buffer = "";
let warmed = false;

child.stdout.setEncoding("utf8");
child.stdout.on("data", (chunk) => {
  process.stdout.write(chunk);
  if (warmed) return;
  buffer += chunk;
  if (buffer.length > 128 * 1024) buffer = buffer.slice(-64 * 1024);
  if (/Ready in/i.test(buffer)) {
    const match = buffer.match(/Local:\s+(https?:\/\/\S+)/i);
    const baseUrl = match?.[1] ?? "http://localhost:3000";
    warmed = true;
    warmUp(baseUrl).catch((err) => {
      console.error("[dev] route warm-up failed:", err.message);
    });
  }
});

child.on("error", (err) => {
  console.error("[dev] failed to start next dev:", err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 0);
  }
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    child.kill(sig);
  });
}

async function warmUp(baseUrl) {
  const routes = [...NAV_ROUTES];
  const token = await makeToken();
  const headers = token ? { Cookie: `exam_session=${token}` } : {};

  console.log(`[dev] warming ${routes.length} routes on ${baseUrl}${token ? " (authenticated)" : ""}...`);

  const results = await runLimited(routes, 4, async (route) => {
    try {
      const res = await fetch(baseUrl + route, {
        headers,
        redirect: "follow",
        signal: AbortSignal.timeout(120_000),
      });
      return { route, status: res.status };
    } catch (err) {
      return { route, status: `ERR ${err.name}` };
    }
  });

  for (const { route, status } of results) {
    console.log(`[dev] ${String(status).padStart(3)} ${route}`);
  }

  const failed = results.filter((r) => typeof r.status === "number" && r.status >= 500);
  if (failed.length > 0) {
    console.warn(`[dev] ${failed.length} route(s) returned a 5xx during warm-up.`);
  }
}

async function makeToken() {
  const dbUrl = process.env.DATABASE_URL;
  const secret = process.env.SESSION_SECRET;
  if (!dbUrl || !secret) {
    console.warn("[dev] DATABASE_URL or SESSION_SECRET missing — only warming public routes.");
    return null;
  }
  const pool = new Pool({ connectionString: dbUrl, max: 2 });
  try {
    const { rows } = await pool.query("SELECT id FROM users ORDER BY created_at DESC LIMIT 1");
    if (rows.length === 0) {
      console.warn("[dev] no users in database — only warming public routes.");
      return null;
    }
    const token = await new SignJWT({ sub: rows[0].id })
      .setProtectedHeader({ alg: "HS256" })
      .setIssuedAt()
      .setExpirationTime("5m")
      .sign(new TextEncoder().encode(secret));
    return token;
  } catch (err) {
    console.warn("[dev] could not create warm-up session:", err.message);
    return null;
  } finally {
    await pool.end();
  }
}

async function runLimited(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return results;
}