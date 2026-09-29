/**
 * Recomputes material titles from their stored source path.
 *
 * Folder uploads store the full relative path in `source` (which is what
 * de-duplicates re-uploads) while `title` is what the user sees. When the title
 * rules change, the already-imported materials keep their old titles until this
 * runs, so it is safe to re-run: titles are always derived, never hand-edited.
 *
 *   npx tsx scripts/retitle-materials.ts          # preview
 *   npx tsx scripts/retitle-materials.ts --apply
 */
import "dotenv/config";
import { titleFromPath } from "../src/lib/material-path";
import { query } from "../src/lib/db";

const APPLY = process.argv.includes("--apply");

async function main() {
  const rows = await query<{ id: string; source: string | null; title: string }>(
    `SELECT id, source, title FROM materials WHERE source IS NOT NULL ORDER BY source`
  );

  let changed = 0;
  const updates: { id: string; title: string }[] = [];

  for (const row of rows) {
    if (!row.source) continue;
    const next = titleFromPath(row.source);
    if (next === row.title) continue;
    changed++;
    updates.push({ id: row.id, title: next });
    if (APPLY) await query(`UPDATE materials SET title = $1 WHERE id = $2`, [next, row.id]);
    console.log(`  ${row.title}\n    -> ${next}`);
  }

  console.log(
    `\n${rows.length} file material(s) checked, ${changed} title(s) ${APPLY ? "updated" : "would change"}.`
  );
  if (!APPLY && changed > 0) console.log("Re-run with --apply to write these titles.");
  process.exit(0);
}

main();
