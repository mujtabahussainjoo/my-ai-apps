/**
 * Dev-only fix for React's Server Components performance instrumentation.
 *
 * Upstream bug: when a server component is rejected (notFound()/redirect()) or
 * aborted before any children finish rendering, childrenEndTime stays at
 * -Infinity and the failure path calls performance.measure(end: -Infinity),
 * which throws "Failed to execute 'measure' on 'Performance': '<name>' cannot
 * have a negative time stamp" in the browser console (only under next dev with
 * Turbopack). Tracked upstream as vercel/next.js#86060.
 *
 * This runs as `postinstall` so the guard survives `npm ci`/`npm install`.
 * It idempotently adds a `0 <= childrenEndTime` check to the two measure calls
 * that lack it (Errored + Aborted branches) in every compiled
 * react-server-dom-*-client.browser.development.js bundle.
 */
import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const compiledDir = join(__dirname, "..", "node_modules", "next", "dist", "compiled");

// 20-space indent => Errored (rejected) branch; 18-space indent => Aborted branch.
const REPLACEMENTS = [
  [
    "                    if (supportsUserTiming) {\n",
    "                    if (supportsUserTiming && 0 <= childrenEndTime$jscomp$1) {\n",
  ],
  [
    "                  if (supportsUserTiming) {\n",
    "                  if (supportsUserTiming && 0 <= childrenEndTime$jscomp$3) {\n",
  ],
];

const files = [];
if (existsSync(compiledDir)) {
  for (const variant of readdirSync(compiledDir)) {
    const cjsDir = join(compiledDir, variant, "cjs");
    if (!existsSync(cjsDir)) continue;
    for (const name of readdirSync(cjsDir)) {
      if (/client\.browser\.development\.js$/.test(name)) files.push(join(cjsDir, name));
    }
  }
}

if (files.length === 0) {
  console.log("[patch-react-perf] no variant bundles found — nothing to patch.");
  process.exit(0);
}

let patched = 0;
for (const abs of files) {
  const original = readFileSync(abs, "utf8");
  let source = original;

  for (const [from, to] of REPLACEMENTS) {
    if (source.includes(to)) continue; // already patched from a previous run
    if (!source.includes(from)) {
      throw new Error(
        `[patch-react-perf] pattern not found in ${abs}: ${JSON.stringify(from)}. ` +
          "Next version likely changed — update this script."
      );
    }
    source = source.replace(from, to);
  }

  if (source === original) {
    console.log(`[patch-react-perf] already patched: ${abs}`);
    continue;
  }
  writeFileSync(abs, source);
  patched++;
  console.log(`[patch-react-perf] patched: ${abs}`);
}

console.log(`[patch-react-perf] patched ${patched} bundle(s).`);