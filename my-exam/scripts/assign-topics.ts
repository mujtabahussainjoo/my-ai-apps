/**
 * Files existing questions under a subtopic.
 *
 * Every question generated so far was saved with topic_id = NULL, because topic
 * lookup keyed on a model-supplied name that never matched. This backfills them
 * from the question wording.
 *
 *   npx tsx scripts/assign-topics.ts          # dry run
 *   npx tsx scripts/assign-topics.ts --apply  # write
 */
import "dotenv/config";
import { Client } from "pg";
import { rankTopics, type MatchableTopic } from "../src/lib/topic-match";

const APPLY = process.argv.includes("--apply");

async function main() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  const db = new Client({ connectionString: url });
  await db.connect();

  const { rows: topics } = await db.query<{
    id: string;
    name: string;
    parent_id: string | null;
    parent_name: string | null;
    exam_id: string;
  }>(
    `SELECT t.id, t.name, t.parent_id, p.name AS parent_name, t.exam_id
       FROM topics t LEFT JOIN topics p ON p.id = t.parent_id`
  );
  const { rows: questions } = await db.query<{ id: string; prompt: string; exam_id: string | null; topic_id: string | null }>(
    `SELECT id, prompt, exam_id, topic_id FROM questions WHERE topic_id IS NULL ORDER BY created_at`
  );

  console.log(`${questions.length} unfiled question(s), ${topics.length} topics in the outline\n`);

  const byExam = new Map<string, MatchableTopic[]>();
  for (const t of topics) {
    const list = byExam.get(t.exam_id) ?? [];
    list.push({ id: t.id, name: t.name, parentId: t.parent_id, parentName: t.parent_name });
    byExam.set(t.exam_id, list);
  }

  let filed = 0;
  let unmatched = 0;
  for (const q of questions) {
    const outline = byExam.get(q.exam_id ?? "") ?? [];
    const subtopics = outline.filter((t) => t.parentId);
    const parents = outline.filter((t) => !t.parentId);
    // Subtopic only when it is a convincing match; otherwise the exam-level
    // topic, which is still far more useful than leaving it uncategorised.
    const sub = rankTopics(q.prompt, subtopics, { limit: 1, minScore: 3 })[0];
    const top = sub ?? rankTopics(q.prompt, parents, { limit: 1, minScore: 1.2 })[0];
    const label = top ? `${top.name}${sub ? "" : "  (exam level)"}` : "NO MATCH";
    console.log(`${q.prompt.slice(0, 58).replace(/\n/g, " ")}\n   -> ${label}`);
    if (!top) {
      unmatched++;
      continue;
    }
    if (APPLY) await db.query("UPDATE questions SET topic_id = $1 WHERE id = $2", [top.topicId, q.id]);
    filed++;
  }

  console.log(
    `\n${APPLY ? "APPLIED" : "DRY RUN - rerun with --apply"}: filed ${filed}, left unfiled ${unmatched}`
  );
  await db.end();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
