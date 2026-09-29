import "dotenv/config";
import { validateGeneratedRow, hasDanglingVisualReference } from "../src/lib/generate";
import { correctIndex, isCorrect } from "../src/lib/grade";
import { MIN_OPTIONS, MAX_OPTIONS } from "../src/lib/generate";
import { query } from "../src/lib/db";

async function main() {
  const rows = await query<{
    id: string;
    type: string;
    source: string;
    prompt: string;
    choices: unknown;
    answer: string | null;
    explanation: string | null;
    category: string | null;
    topic_id: string | null;
  }>(
    `SELECT id, type, source, prompt, choices, answer, explanation, category, topic_id
     FROM questions ORDER BY created_at`
  );

  const broken: { prompt: string; type: string; source: string; reason: string }[] = [];
  const emptyExpl: string[] = [];
  let ungradable = 0;
  let badOptionCount = 0;

  for (const r of rows) {
    const row = {
      topicId: r.topic_id,
      prompt: r.prompt,
      type: r.type,
      choices: r.choices,
      answer: r.answer ?? "",
      explanation: r.explanation ?? "",
      category: r.category,
    };
    const verdict = validateGeneratedRow(row, r.type);
    if (!verdict.ok) broken.push({ prompt: r.prompt, type: r.type, source: r.source, reason: verdict.reason });

    if (r.type === "mcq" && Array.isArray(r.choices)) {
      const opts = r.choices as { correct?: boolean }[];
      const correct = opts.filter((c) => c.correct === true).length;
      if (correct !== 1) ungradable++;
      if (opts.length < MIN_OPTIONS || opts.length > MAX_OPTIONS) {
        badOptionCount++;
        console.log(
          `  - [options] "${r.prompt.slice(0, 70)}" has ${opts.length} options, needs ${MIN_OPTIONS}-${MAX_OPTIONS}`
        );
      }
    }
    if ((r.type === "mcq" || r.type === "true_false") && !(r.explanation ?? "").trim()) {
      emptyExpl.push(r.prompt);
    }
  }

  console.log(`total questions: ${rows.length}`);
  console.log(`\nINCOMPLETE (fail the new gate): ${broken.length}`);
  for (const b of broken) {
    console.log(`  - [${b.type}/${b.source}] ${b.reason}\n      "${b.prompt.slice(0, 95)}"`);
  }
  console.log(`\nMCQs with no single correct option (ungradable, always score 0): ${ungradable}`);
  console.log(`MCQs outside the ${MIN_OPTIONS}-${MAX_OPTIONS} option rule: ${badOptionCount}`);
  console.log(`MCQ/true-false with an empty explanation: ${emptyExpl.length}`);
  for (const p of emptyExpl) console.log(`  - "${p.slice(0, 95)}"`);
  console.log(`\ndangling visual reference (any): ${rows.filter((r) => hasDanglingVisualReference(r.prompt)).length}`);

  // Walk the exact reveal path the practice UI takes for every option, using the
  // same grader the components and the server actions share. A question only
  // gives useful feedback if picking its keyed option reads as correct and every
  // other option reads as incorrect while still surfacing an answer to show.
  let revealBroken = 0;
  for (const r of rows) {
    if (r.type !== "mcq") continue;
    const choices = (r.choices ?? []) as { text: string; correct: boolean }[];
    const key = correctIndex(choices);
    const keyed = key >= 0 ? choices[key] : null;
    const explainable = Boolean((r.explanation ?? "").trim());

    if (key < 0 || !keyed || !explainable) {
      revealBroken++;
      console.log(
        `  - [reveal] "${r.prompt.slice(0, 70)}" key=${key} explanation=${explainable ? "yes" : "MISSING"}`
      );
      continue;
    }
    for (let i = 0; i < choices.length; i++) {
      const graded = isCorrect({ type: r.type, choices }, { chosen: i });
      if (graded !== (i === key)) {
        revealBroken++;
        console.log(
          `  - [reveal] "${r.prompt.slice(0, 60)}" option ${i} graded ${graded ? "correct" : "wrong"} but key is ${key}`
        );
      }
    }
  }
  console.log(`\nquestions whose pick-an-option feedback is broken: ${revealBroken}`);
  process.exit(broken.length + revealBroken + badOptionCount === 0 ? 0 : 1);
}

main().then(() => process.exit(0));
