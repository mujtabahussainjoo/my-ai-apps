/**
 * Builds subtopics from the structure of uploaded material.
 *
 * The six top-level topics were named after the uploaded files, but they are too
 * coarse to file a question under: "How LLMs Behave" covers tokens, the context
 * window, sampling and non-determinism, which are four different things to be
 * tested on. Every `##` heading inside a material is one of those things, so the
 * headings become child topics and questions can be filed against them.
 *
 * Idempotent: re-running updates names and never creates a second copy.
 *
 *   npx tsx scripts/seed-subtopics.ts          # dry run, prints the plan
 *   npx tsx scripts/seed-subtopics.ts --apply  # write to the database
 */
import "dotenv/config";
import { Client } from "pg";

const APPLY = process.argv.includes("--apply");

/** Headings that describe the document rather than a testable idea. */
const SKIP = [
  /^big picture$/i,
  /^tiny decision guide/i,
  /^quick recap/i,
  /^question \d+$/i,
  /^scenario \d+$/i,
  /^example \d/i,
  /^what this module really is/i,
  /^answers with simple explanations$/i,
  /^exercise\b/i,
  /^(simple|easy|one simple|put it all together|all together)\b/i,
  /diagram|mental model/i,
  /^recap\b/i,
];

/** "1) Two Ways to Connect" -> "Two Ways to Connect" */
function clean(heading: string): string {
  return heading
    .replace(/^\d+[).]\s*/, "")
    .replace(/\s*\(layman version\)\s*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function isSubtopic(heading: string): boolean {
  const h = clean(heading);
  if (h.length < 8 || h.length > 70) return false;
  return !SKIP.some((re) => re.test(h));
}

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  const db = new Client({ connectionString: url });
  await db.connect();

  // There is no unique constraint on topic names, so without this a rerun would
  // create a second copy of every subtopic and orphan questions pointing at the
  // old ids. Safe to add now: no subtopics exist yet.
  await db.query(`CREATE UNIQUE INDEX IF NOT EXISTS uniq_subtopic_name
                    ON topics (exam_id, parent_id, lower(name))
                    WHERE parent_id IS NOT NULL`);

  const { rows: materials } = await db.query<{ id: string; exam_id: string; title: string; content: string }>(
    "SELECT id, exam_id, title, content FROM materials ORDER BY created_at"
  );
  const { rows: parents } = await db.query<{ id: string; exam_id: string; name: string }>(
    "SELECT id, exam_id, name FROM topics WHERE parent_id IS NULL"
  );

  let created = 0;
  let skipped = 0;
  /** parent topic id -> the subtopic names we want under it. */
  const desired = new Map<string, Set<string>>();

  for (const material of materials) {
    // "1. Orientation" (material) should sit under "Orientation" (topic).
    const bare = material.title.replace(/^\d+[.)]\s*/, "").trim();
    // Materials often have exam_id = NULL (they are filed under a knowledge base
    // instead), so the parent topic's exam is what the subtopic must inherit.
    const pool = parents.filter((p) => !material.exam_id || p.exam_id === material.exam_id);
    const parent =
      pool.find((p) => p.name.toLowerCase() === bare.toLowerCase()) ??
      pool.find((p) => p.name.toLowerCase().includes(bare.toLowerCase()));
    if (!parent) {
      console.log(`  ! no top-level topic matches material "${material.title}" - skipped`);
      continue;
    }

    const headings = [...String(material.content).matchAll(/^#{2,3}\s+(.+)$/gm)].map((m) => m[1].trim());
    const names = headings.filter(isSubtopic).map(clean);
    const unique = [...new Set(names)];
    skipped += headings.length - unique.length;
    desired.set(parent.id, new Set(unique.map((n) => n.toLowerCase())));

    console.log(`\n${material.title}  ->  ${parent.name}`);
    for (const [i, name] of unique.entries()) {
      if (!APPLY) {
        console.log(`   ? ${name}`);
        continue;
      }
      await db.query(
        `INSERT INTO topics (exam_id, name, parent_id, sort_order, weightage)
         VALUES ($1, $2, $3, $4, $5)
         ON CONFLICT (exam_id, parent_id, lower(name)) WHERE parent_id IS NOT NULL
         DO UPDATE SET sort_order = EXCLUDED.sort_order`,
        [parent.exam_id, name, parent.id, i, 1]
      );
      console.log(`   + ${name}`);
      created++;
    }
  }

  if (!APPLY) {
    console.log(`\nDRY RUN - nothing was written. Rerun with --apply to create the subtopics.`);
    await db.end();
    return;
  }

  // Drop subtopics left over from headings that are now filtered out. Must skip
  // anything still wanted, and anything a question points at.
  const { rows: candidates } = await db.query<{ id: string; name: string; parent_id: string }>(
    `SELECT id, name, parent_id FROM topics WHERE parent_id IS NOT NULL`
  );
  for (const c of candidates) {
    if (desired.get(c.parent_id)?.has(c.name.toLowerCase())) continue;
    const used = await db.query(`SELECT 1 FROM questions WHERE topic_id = $1 LIMIT 1`, [c.id]);
    if (used.rowCount) continue; // a question relies on it
    await db.query("DELETE FROM topics WHERE id = $1", [c.id]);
    console.log(`   - ${c.name} (no longer a subtopic)`);
  }

  const { rows: counts } = await db.query<{ n: number }>(
    "SELECT count(*)::int n FROM topics WHERE parent_id IS NOT NULL"
  );

  console.log(`\n${APPLY ? "APPLIED" : "DRY RUN - rerun with --apply to write"}`);
  console.log(`subtopics now: ${counts[0].n} (new this run: ${created}, headings filtered out: ${skipped})`);
  await db.end();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
