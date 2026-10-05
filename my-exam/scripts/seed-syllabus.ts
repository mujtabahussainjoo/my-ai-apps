/**
 * Writes the official Claude Certified Developer – Foundations blueprint into
 * every exam that is preparing for CCDV-F, as topics + subtopics with % weightage.
 *
 * The same tree the in-app importer offers as a preset, so seeding here and
 * clicking "Use blueprint" in the UI produce identical results.
 *
 * Idempotent: re-running updates weightage in place instead of creating a
 * second copy of the tree (subtopics are protected by `uniq_subtopic_name`,
 * parents are matched by name).
 *
 *   npx tsx scripts/seed-syllabus.ts          # dry run, prints the plan
 *   npx tsx scripts/seed-syllabus.ts --apply  # write to the database
 */
import "dotenv/config";
import { Client } from "pg";
import {
  normalizeWeights,
  suggestedPresetFor,
  SYLLABUS_PRESETS,
  type SyllabusNode,
} from "../src/lib/syllabus";

const APPLY = process.argv.includes("--apply");

/**
 * Inserts a topic, or updates the one already there. This mirrors upsertTopic()
 * in src/lib/actions.ts — kept in sync deliberately so a seeded tree and an
 * imported tree are byte-identical.
 */
async function upsertTopic(
  db: Client,
  examId: string,
  node: SyllabusNode,
  parentId: string | null,
  order: number
): Promise<string> {
  const existing = await db.query<{ id: string }>(
    parentId === null
      ? `SELECT id FROM topics WHERE exam_id = $1 AND parent_id IS NULL AND lower(name) = lower($2)`
      : `SELECT id FROM topics WHERE exam_id = $1 AND parent_id = $2 AND lower(name) = lower($3)`,
    parentId === null ? [examId, node.name] : [examId, parentId, node.name]
  );

  if (existing.rows[0]) {
    await db.query(
      "UPDATE topics SET weightage = $1, description = $2, sort_order = $3 WHERE id = $4",
      [node.weight, node.note ?? null, order, existing.rows[0].id]
    );
    return existing.rows[0].id;
  }

  const { rows } = await db.query<{ id: string }>(
    `INSERT INTO topics (exam_id, name, weightage, description, sort_order, parent_id)
     VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
    [examId, node.name, node.weight, node.note ?? null, order, parentId]
  );
  return rows[0].id;
}

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  const db = new Client({ connectionString: url });
  await db.connect();

  const { rows: exams } = await db.query<{ id: string; title: string; existing: number }>(
    `SELECT e.id, e.title,
            (SELECT count(*)::int FROM topics t WHERE t.exam_id = e.id) AS existing
       FROM exams e
      ORDER BY e.created_at`
  );

  const targets = exams.filter((e) => suggestedPresetFor(e.title));
  if (targets.length === 0) {
    console.log("No exam title matches the CCDV-F blueprint - nothing to do.");
    await db.end();
    return;
  }

  for (const exam of targets) {
    const preset = SYLLABUS_PRESETS[0];
    // Normalise a fresh copy: normalizeWeights rewrites leaf weights in place.
    const nodes = normalizeWeights(preset.nodes.map((n) => ({ ...n, children: n.children?.map((c) => ({ ...c })) })));
    const leafCount = nodes.reduce(
      (s, n) => s + (n.children?.length ? n.children.length : 1),
      0
    );

    console.log(`\n${exam.title}`);
    console.log(`  ${exam.id}`);
    console.log(`  ${nodes.length} domains, ${leafCount} weighted skills`);
    console.log(`  existing topics on this exam: ${exam.existing}`);

    if (!APPLY) {
      for (const node of nodes) {
        console.log(`    ${node.weight.toString().padStart(5)}%  ${node.name}`);
        for (const child of node.children ?? []) {
          console.log(`           ${child.weight.toString().padStart(5)}%  ${child.name}`);
        }
      }
      continue;
    }

    await db.query("BEGIN");
    try {
      let order = 0;
      for (const node of nodes) {
        const parentId = await upsertTopic(db, exam.id, node, null, order++);
        for (const child of node.children ?? []) {
          await upsertTopic(db, exam.id, child, parentId, order++);
        }
      }
      await db.query("COMMIT");
      console.log("  APPLIED");
    } catch (err) {
      await db.query("ROLLBACK");
      throw err;
    }
  }

  const { rows: totals } = await db.query<{ exam: string; leaves: number; total: number }>(
    `SELECT e.title AS exam,
            count(*) FILTER (WHERE t.parent_id IS NOT NULL
                               AND NOT EXISTS (SELECT 1 FROM topics c WHERE c.parent_id = t.id))::int AS leaves,
            coalesce(sum(t.weightage) FILTER (WHERE t.parent_id IS NOT NULL
                               AND NOT EXISTS (SELECT 1 FROM topics c WHERE c.parent_id = t.id)), 0)::int AS total
       FROM topics t JOIN exams e ON e.id = t.exam_id
      GROUP BY e.title ORDER BY e.title`
  );

  console.log(`\n${APPLY ? "APPLIED" : "DRY RUN - rerun with --apply to write"}`);
  console.table(totals);

  if (!APPLY) {
    for (const t of totals) {
      console.log(`  ${t.exam}: ${t.leaves} weighted skills summing to ${t.total}%`);
    }
  }
  await db.end();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});