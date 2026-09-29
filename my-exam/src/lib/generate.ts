import { AIError, chatJsonArray, ragSearch } from "@/lib/ai";
import { matchTopic, type MatchableTopic } from "@/lib/topic-match";
import { findDuplicateCandidates } from "@/lib/dedupe-semantic";
import { recordEvent } from "@/lib/diagnostics";
import { query, queryOne } from "@/lib/db";
import {
  mcqPrompt,
  trueFalsePrompt,
  shortAnswerPrompt,
  flashcardPrompt,
  interviewPrompt,
  type GeneratedMCQ,
  type GeneratedTF,
  type GeneratedShort,
  type GeneratedFlashcard,
  type GeneratedInterview,
} from "@/lib/prompts";

export const MAX_GEN = Number(process.env.MAX_GEN ?? 1000);
// Items per model call. This used to be 50, which asked for 50 questions in a
// single completion capped at 4096 output tokens - roughly 7,500 tokens of
// content, so the response always truncated and a 27-minute run produced zero
// usable questions. Small batches fit the token budget, let each batch be saved
// through onBatch as it lands, and measurably improve quality on weak models.
/**
 * Questions requested per model call. Measured on this machine: a batch of 4
 * over a ~5k-character context returns 4 valid questions in ~66s, while a batch
 * of 8 runs past ten minutes and comes back truncated mid-array, which the
 * salvage turns into objects with no question text and two options. Smaller
 * batches that actually finish beat bigger ones that get thrown away.
 */
const BATCH_SIZE = 4;
/** Consecutive all-rejected batches tolerated before the run gives up. */
const BARREN_LIMIT = 6;
/**
 * Sampling temperature for question generation.
 *
 * At 0.4 a 3B model settles on one phrasing for a concept and then restates it
 * for every later batch, which is what filled the reject log with "repeated a
 * question from this same run". Grounded question writing wants variety more
 * than it wants determinism.
 */
const GEN_TEMPERATURE = 0.8;

export type GenRow = {
  topicId: string | null;
  prompt: string;
  type: string;
  choices: unknown;
  answer: string;
  explanation: string;
  category: string | null;
};

export type GenInput = {
  userId: string;
  examId?: string | null;
  knowledgeBaseId?: string | null;
  topicIds?: string[];
  /** When set, retrieval + prompt focus are restricted to this uploaded
   *  material (chapter/section) — "create Q&A for this title". */
  materialId?: string | null;
  /** When set (e.g. "generate for this subtopic"), every produced row is
   *  assigned to this topic instead of relying on fuzzy name matching. */
  forceTopicId?: string | null;
  type: "mcq" | "true_false" | "short" | "flashcard" | "interview";
  count: number;
  /** Called with each freshly-produced batch so callers can persist results
   *  incrementally and keep partial work even if a large run is interrupted. */
  onBatch?: (rows: GenRow[]) => Promise<void>;
  /** Wall-clock ceiling for the whole request across all batches. Defaults to
   *  75s per requested question, floored at 3 minutes. */
  budgetMs?: number;
  /** Called once when fewer questions were produced than asked for, so the UI
   *  can say why instead of leaving the user to guess. */
  onShortfall?: (info: { requested: number; created: number; reason: "budget" | "barren" | "exhausted" | null }) => void;
};

// --------------------------------------------------------------- quality gate

/**
 * Reference material is a merged blob of chunks from many files, so the model
 * sometimes writes a question that only makes sense next to a diagram or code
 * listing it saw ("what is the main purpose of the diagram?"). A learner
 * answering later has no way to see that content, so those rows are dropped
 * rather than saved. The prompts ask for self-contained questions; this
 * enforces it.
 */

/** A dangling pointer at content the reader cannot see. */
const VISUAL_REFERENCE =
  /\b(?:the|this|these|that|following|above|below|previous|preceding|attached|provided|given|illustrated|depicted|shown)\s+(?:simple\s+|high[- ]level\s+|above\s+|following\s+)?(?:diagram|figure|figs?|flowchart|chart|graph|image|photo|photograph|picture|screenshot|icon|logo|table|listing|snippet|code|program|script|output|trace|command|example|architecture|pipeline)\b|\bas shown in\b|\bas illustrated in\b|\baccording to the (?:figure|diagram|table|chart|image|code)\b|\bthe (?:figure|diagram|table|chart|image|code|listing) (?:above|below|here)\b|\bsee (?:the )?(?:figure|diagram|table|image|code)\b/i;

/** Content the reader can actually see: a fenced block, ASCII art, or a tree. */
const HAS_VISIBLE_CONTENT =
  /```|[┌┐└┘├┤┬┴┼│─┬┴╔╗╚╝═║▼▲◀▶→←⇒]|\+-{3,}|_{3,}/;

/** Raster-only visuals can never be reproduced as text, fenced or not. */
const RASTER_REFERENCE =
  /\b(?:image|images|photo|photograph|picture|screenshot|icon|logo|video|screen recording|scanned)\b/i;

const MIN_PROMPT_CHARS = 15;

/** Answer-key or instruction text that leaked into a question prompt. */
const META_PROMPT = new RegExp(
  [
    // A bare label where the question should be, e.g. "Correct answer: B".
    "^\\s*(correct\\s+answer|right\\s+answer|answer\\s*[:=]|question\\s*[:=]|option\\s+[a-e]\\b)",
    // Or the question asking about its own answer key.
    "\\b(what is the|which is the)?\\s*(correct|right)\\s+answer\\s+(for|to)\\b",
    "\\bwhat is the correct answer\\b",
  ].join("|"),
  "i"
);
/** Every MCQ in the app must offer 4 or 5 options - fewer is too guessable, more is noisy. */
export const MIN_OPTIONS = 4;
export const MAX_OPTIONS = 5;

const STOP_WORDS = new Set([
  "what", "which", "how", "why", "when", "does", "do", "did", "is", "are", "was", "the", "a", "an",
  "of", "in", "to", "for", "and", "or", "that", "this", "these", "those", "it", "its", "you", "your",
  "with", "as", "by", "on", "at", "from", "be", "been", "can", "will", "would", "should", "there",
]);

/** Lowercased content words with simple plural folding, so "unit" matches "units". */
function contentTokens(text: string): Set<string> {
  const out = new Set<string>();
  for (const raw of text.toLowerCase().replace(/[^a-z0-9\s]/g, " ").split(/\s+/)) {
    if (raw.length < 3 || STOP_WORDS.has(raw)) continue;
    out.add(raw.endsWith("ies") ? `${raw.slice(0, -3)}y` : raw.endsWith("s") && !raw.endsWith("ss") ? raw.slice(0, -1) : raw);
  }
  return out;
}

export function isNearDuplicate(a: string, b: string, threshold = 0.7): boolean {
  const ta = contentTokens(a);
  const tb = contentTokens(b);
  if (ta.size === 0 || tb.size === 0) return a.trim().toLowerCase() === b.trim().toLowerCase();
  let shared = 0;
  for (const t of ta) if (tb.has(t)) shared++;
  const jaccard = shared / (ta.size + tb.size - shared);
  // A short question that is fully contained in a longer one is a duplicate too.
  if (jaccard >= threshold) return true;
  const [small, large] = ta.size <= tb.size ? [ta, tb] : [tb, ta];
  let contained = 0;
  for (const t of small) if (large.has(t)) contained++;
  return small.size >= 2 && contained / small.size === 1 && jaccard >= 0.55;
}

function normalize(text: unknown): string {
  return typeof text === "string" ? text.replace(/\r\n/g, "\n").trim() : "";
}

/** True when the text leans on content the reader is not shown. */
export function hasDanglingVisualReference(text: string): boolean {
  if (!VISUAL_REFERENCE.test(text)) return false;
  // A raster visual is never reproducible as text, so a reference to one is
  // broken even when a code fence is present.
  if (RASTER_REFERENCE.test(text)) return true;
  return !HAS_VISIBLE_CONTENT.test(text);
}

/**
 * Rejects option sets that cannot be graded unambiguously: blank options,
 * duplicates, or anything other than exactly one marked-correct choice. An
 * out-of-range correctIndex from the model yields zero correct options, which
 * would otherwise be saved as a question nobody can ever answer correctly.
 */
function validateChoices(choices: unknown): string | null {
  if (!Array.isArray(choices)) return "options missing";
  if (choices.length < MIN_OPTIONS || choices.length > MAX_OPTIONS) {
    return `expected ${MIN_OPTIONS}-${MAX_OPTIONS} options, got ${choices.length}`;
  }
  const parsed = choices.map((c) =>
    normalize(typeof c === "string" ? c : (c as { text?: unknown })?.text)
  );
  if (parsed.some((t) => t.length === 0)) return "an option is blank";
  if (new Set(parsed.map((t) => t.toLowerCase())).size !== parsed.length) {
    return "duplicate options";
  }
  const marked = (choices as { correct?: unknown }[]).filter((c) => c?.correct === true).length;
  if (marked !== 1) return `expected exactly 1 correct option, found ${marked}`;
  return null;
}

export function validateGeneratedRow(row: GenRow, type: string): { ok: true } | { ok: false; reason: string } {
  const prompt = normalize(row.prompt);
  if (prompt.length < MIN_PROMPT_CHARS) return { ok: false, reason: "prompt too short" };
  if (hasDanglingVisualReference(prompt)) return { ok: false, reason: "refers to a diagram/listing it does not include" };

  // The material contains worked examples laid out as "Q ... Correct answer: B",
  // and a small model copies that shape straight into the question field, which
  // used to produce items like "Correct answer: B" sitting in the question bank.
  if (META_PROMPT.test(prompt)) {
    return { ok: false, reason: "prompt is answer-key text, not a question" };
  }
  if (type === "mcq") {
    const bad = validateChoices(row.choices);
    if (bad) return { ok: false, reason: bad };
    if (normalize(row.explanation).length === 0) return { ok: false, reason: "explanation is empty" };
  }
  if (type === "true_false") {
    if (normalize(row.answer).length === 0) return { ok: false, reason: "no true/false answer" };
    const marked = (Array.isArray(row.choices) ? row.choices : []).filter(
      (c) => (c as { correct?: unknown })?.correct === true
    ).length;
    if (marked !== 1) return { ok: false, reason: `expected 1 correct side, found ${marked}` };
    if (normalize(row.explanation).length === 0) return { ok: false, reason: "explanation is empty" };
  }
  if ((type === "short" || type === "flashcard") && normalize(row.answer).length === 0) {
    return { ok: false, reason: "question has no model answer" };
  }
  return { ok: true };
}

async function loadTopics(examId?: string | null): Promise<MatchableTopic[]> {
  if (!examId) return [];
  const topics = await query<{ id: string; name: string; parent_id: string | null; parent_name: string | null }>(
    `SELECT t.id, t.name, t.parent_id, p.name AS parent_name
       FROM topics t LEFT JOIN topics p ON p.id = t.parent_id
      WHERE t.exam_id = $1
      ORDER BY t.sort_order, t.name`,
    [examId]
  );
  return topics.map((t) => ({
    id: t.id,
    name: t.name,
    parentId: t.parent_id,
    parentName: t.parent_name,
  }));
}

/**
 * The prompt budget is derived from the model's context window instead of being
 * hard-coded, because the two drifting apart is what broke generation: at
 * AI_NUM_CTX=4096 a 16k-character material window plus a 4096-token answer
 * request is roughly 8.6k tokens of prompt into a 4k window, so the model was
 * answering a request it could not physically fit and returning truncated JSON
 * that the quality gate then threw away.
 */
const NUM_CTX = Number(process.env.AI_NUM_CTX ?? 4096) || 4096;
/** Rough characters-per-token for mixed markdown/prose; err low, not high. */
const CHARS_PER_TOKEN = 3.5;
/** Room for the system prompt, the avoid-list and chat framing overhead. */
const PROMPT_OVERHEAD_TOKENS = 700;
/** Enough for a full batch of the longest supported question type. */
const OUTPUT_TOKENS = 1600;

const CONTEXT_TOKENS = Math.max(
  512,
  NUM_CTX - PROMPT_OVERHEAD_TOKENS - OUTPUT_TOKENS
);
const MAX_CONTEXT_CHARS = Math.floor(CONTEXT_TOKENS * CHARS_PER_TOKEN);
const MAX_OUTPUT_TOKENS = Math.min(OUTPUT_TOKENS, Math.max(512, NUM_CTX - PROMPT_OVERHEAD_TOKENS - CONTEXT_TOKENS));
/** How much material is gathered before a per-batch window is taken from it. */
const CONTEXT_POOL_CHARS = MAX_CONTEXT_CHARS * 4;
/** Chunks fetched to fill that pool; chunks average ~330 characters. */
const POOL_CHUNKS = 120;

/**
 * Pulls in every ready chunk in document order that RAG didn't surface, so
 * generation can never silently drop part of the source material. Scoped to
 * the same knowledge base / exam rules ragSearch uses.
 */
async function fetchPositionChunks(
  userId: string,
  examId: string | null | undefined,
  knowledgeBaseId: string | null | undefined,
  materialId: string | null | undefined,
  excludeIds: string[]
): Promise<{ title: string; content: string }[]> {
  const clauses = ["m.user_id = $1", "m.status = 'ready'", "c.content <> ''"];
  const params: unknown[] = [userId];
  if (excludeIds.length > 0) {
    clauses.push(`NOT (c.id = ANY($${params.length + 1}))`);
    params.push(excludeIds as never[]);
  }
  if (materialId) {
    clauses.push(`m.id = $${params.length + 1}`);
    params.push(materialId);
  } else if (knowledgeBaseId) {
    clauses.push(`m.knowledge_base_id = $${params.length + 1}`);
    params.push(knowledgeBaseId);
  } else if (examId) {
    clauses.push(`(m.exam_id = $${params.length + 1} OR m.exam_id IS NULL)`);
    params.push(examId);
  }
  return query<{ title: string; content: string }>(
    `SELECT m.title, c.content
     FROM chunks c
     JOIN materials m ON m.id = c.material_id
     WHERE ${clauses.join(" AND ")}
     ORDER BY m.created_at, c.position
     LIMIT 24`,
    params
  );
}

async function buildContext(
  userId: string,
  examId: string | null | undefined,
  knowledgeBaseId: string | null | undefined,
  examTitle: string | null,
  knowledgeBaseName: string | null,
  topicNames: string[],
  materialId?: string | null,
  materialTitle?: string | null
): Promise<string> {
  const queryParts = materialTitle
    ? [materialTitle, ...(examTitle ? [examTitle] : [])]
    : examTitle
      ? [examTitle, ...topicNames]
      : topicNames;
  if (knowledgeBaseName) queryParts.unshift(knowledgeBaseName);
  const queryText = queryParts.join(", ") || "general exam preparation";

  const results = await ragSearch(userId, queryText, {
    knowledgeBaseId: knowledgeBaseId ?? null,
    examId: examId ?? null,
    materialId: materialId ?? null,
    limit: 24,
    minScore: 0.05,
  });

  // Breadth fallback: if semantic/lexical retrieval only surfaced a thin
  // slice, append remaining chunks in document order so no part of the doc
  // is missed — the whole thing is capped to a workable prompt size below.
  const lines: { title: string; content: string }[] = results.map((r) => ({
    title: r.title,
    content: r.content,
  }));
  // Gate this on characters, not chunk count. Counting chunks meant that
  // retrieval returning its full 24 results skipped the fallback and left a
  // ~8k pool — barely one context window, so every batch saw the same page and
  // the model looped. Rotation needs at least two windows to have anything to
  // walk through.
  const retrievedChars = lines.reduce((n, l) => n + l.content.length, 0);
  if (retrievedChars < CONTEXT_POOL_CHARS) {
    const extra = await fetchPositionChunks(
      userId,
      examId,
      knowledgeBaseId,
      materialId,
      results.map((r) => r.chunkId)
    );
    const seen = new Set(results.map((r) => r.chunkId));
    for (const row of extra) {
      if (seen.size >= POOL_CHUNKS) break;
      seen.add(`pos-${seen.size}`);
      lines.push({ title: row.title, content: row.content });
    }
  }

  const out: string[] = [];
  let total = 0;
  for (const { title, content } of lines) {
    const entry = `[${title || "material"}]\n${content}`;
    if (total + entry.length > CONTEXT_POOL_CHARS && out.length > 0) break;
    out.push(entry);
    total += entry.length;
  }
  return out.join("\n\n---\n\n");
}

/**
 * Takes the window of material this batch should focus on.
 *
 * Every batch used to receive byte-for-byte the same 16k characters, so asking
 * for 50 questions produced the same token question over and over: the model was
 * not being unreasonable, it was being shown the same page. Rotating the window
 * across batches walks the model through the rest of the material.
 */
function rotateContext(text: string, batchIndex: number): string {
  if (text.length <= MAX_CONTEXT_CHARS) return text;
  // Non-overlapping slices, not a sliding window. Sliding by a slack of only
  // ~1.7k chars across a 6.3k window meant batch 2 shared ~90% of its text with
  // batch 1, so the model was shown effectively the same page every time and
  // kept answering the same question. Walking the pool in whole windows gives
  // each batch a genuinely different part of the material, and never lets any
  // batch exceed the context window (the first batch used to be uncapped).
  // Full windows only. Taking ceil() left a short trailing slice, so one batch
  // in every pass was starved of context and produced its worst questions.
  const count = Math.max(1, Math.floor(text.length / MAX_CONTEXT_CHARS));
  // Walk from the first window to the last full one, so the batches between
  // them cover the whole pool instead of re-showing the opening page.
  const stride = count > 1 ? (text.length - MAX_CONTEXT_CHARS) / (count - 1) : 0;
  const start = Math.round(stride * (batchIndex % count));
  return text.slice(start, start + MAX_CONTEXT_CHARS);
}

function abbreviated(question: string, options: string[]): string {
  return options.every((o) => o.length < 240) && question.length < 800
    ? options.join("  |  ")
    : "short options";
}

/** The first heading inside a batch's slice of material, used as a focus hint. */
function focusHeading(ctx: string): string | null {
  const heading = ctx.match(/^#{1,3}\s+(.{3,80})$/m)?.[1]?.trim();
  return heading ?? null;
}

async function runEach(
  userId: string,
  type: GenInput["type"],
  ctx: string,
  focus: string | null,
  names: string[],
  fileUnder: (prompt: string) => string | null,
  avoid: string[],
  target: number,
  batchNumber: number,
  remainingMs: number
): Promise<GenRow[]> {
  switch (type) {
    case "mcq": {
      // Naming the section this slice covers stops a small model answering the
      // same four questions every batch, which is what ended runs as barren.
      const topics = focus ? [focus, ...names.filter((n) => n !== focus)] : names;
      const { system, user } = mcqPrompt(ctx, topics, target, avoid);
      const out = await chatJsonArray<GeneratedMCQ>(userId, system, user, {
        maxTokens: MAX_OUTPUT_TOKENS,
        targetCount: target,
        temperature: GEN_TEMPERATURE,
        // Without this each call silently got a fresh 300s floor, so the last
        // batch of a run overran its own deadline: 905s spent on a 750s budget.
        budgetMs: remainingMs,
        onTruncated: (info) =>
          recordEvent(userId, "warn", "generate", "A model reply was cut off by the output cap", {
            ...info,
            batch: batchNumber,
            batchSize: target,
            hint: "Lower BATCH_SIZE or MAX_OUTPUT_TOKENS is the wrong direction; raise the output cap or lower the batch size.",
          }),
      });
      return out.slice(0, target).map((q) => {
        // A malformed item must not throw away the whole batch — an absent
        // options array becomes an empty one and the quality gate rejects it.
        const options = Array.isArray(q.options) ? q.options : [];
        const idx = Number(q.correctIndex);
        const safeIdx = Number.isInteger(idx) && idx >= 0 && idx < options.length ? idx : -1;
        return {
          topicId: fileUnder(q.question),
          prompt: q.question,
          type: "mcq",
          choices: options.map((text, i) => ({ text, correct: i === safeIdx })),
          answer: safeIdx >= 0 ? (options[safeIdx] ?? "") : "",
          explanation: q.explanation ?? "",
          category: null,
        };
      });
    }
    case "true_false": {
      const { system, user } = trueFalsePrompt(ctx, names, target);
      const out = await chatJsonArray<GeneratedTF>(userId, system, user, { maxTokens: MAX_OUTPUT_TOKENS, targetCount: target });
      return out.slice(0, target).map((q) => {
        // Without an explicit boolean there is no answer key. Defaulting to
        // "False" here would save a question whose stored answer is a guess.
        const key = typeof q.answer === "boolean" ? q.answer : null;
        return {
          topicId: fileUnder(q.statement),
          prompt: q.statement,
          type: "true_false",
          choices: key === null
            ? []
            : [
                { text: "True", correct: key },
                { text: "False", correct: !key },
              ],
          answer: key === null ? "" : key ? "True" : "False",
          explanation: q.explanation ?? "",
          category: null,
        };
      });
    }
    case "short": {
      const { system, user } = shortAnswerPrompt(ctx, names, target);
      const out = await chatJsonArray<GeneratedShort>(userId, system, user, { maxTokens: MAX_OUTPUT_TOKENS, targetCount: target });
      return out.slice(0, target).map((q) => ({
        topicId: fileUnder(q.question),
        prompt: q.question,
        type: "short",
        choices: null,
        answer: q.answer ?? "",
        explanation: "",
        category: null,
      }));
    }
    case "flashcard": {
      const { system, user } = flashcardPrompt(ctx, names, target);
      const out = await chatJsonArray<GeneratedFlashcard>(userId, system, user, { maxTokens: MAX_OUTPUT_TOKENS, targetCount: target });
      return out.slice(0, target).map((q) => ({
        topicId: fileUnder(q.front),
        prompt: q.front,
        type: "flashcard",
        choices: null,
        answer: q.back ?? "",
        explanation: "",
        category: null,
      }));
    }
    case "interview": {
      const role = names.join(", ") || "Software Engineer";
      const { system, user } = interviewPrompt({
        role,
        difficulty: "medium",
        categories: ["behavioral", "technical"],
        countPerCategory: 2,
        ctx,
      });
      const out = await chatJsonArray<GeneratedInterview>(userId, system, user, { maxTokens: MAX_OUTPUT_TOKENS, targetCount: target });
      return out.slice(0, target).map((q) => ({
        topicId: null,
        prompt: q.question,
        type: "interview",
        choices: null,
        answer: q.idealAnswer ?? "",
        explanation: `${q.tips ?? ""}\n\nFollow-ups: ${(q.followUps ?? []).join(" / ")}`,
        category: q.category ?? "behavioral",
      }));
    }
    default:
      throw new AIError("Unknown generation type");
  }
}

export async function generateFromAI(input: GenInput): Promise<GenRow[]> {
  const topics = await loadTopics(input.examId);
  const allTopicNames = topics.map((t) => t.name);
  const filteredTopics = topics.filter(
    (t) => !input.topicIds || input.topicIds.length === 0 || input.topicIds.includes(t.id ?? "")
  );

  const materialTitle = input.materialId
    ? (await queryOne<{ title: string }>("SELECT title FROM materials WHERE id = $1", [input.materialId]))?.title ?? null
    : null;

  // Prompt focus: the chosen uploaded title (chapter/section), or the chosen
  // topic/subtopic plus its parent for context.
  let names: string[] = [];
  if (materialTitle) {
    names = [materialTitle];
  } else {
    names = filteredTopics.length > 0 ? filteredTopics.map((t) => t.name) : allTopicNames;
    const focusId = input.topicIds?.[0];
    const focus =
      input.topicIds && input.topicIds.length === 1 && focusId
        ? filteredTopics.find((t) => t.id === focusId) ?? null
        : null;
    if (focus) {
      const parent = focus.parentId ? topics.find((p) => p.id === focus.parentId) : null;
      names = parent && parent.name !== focus.name ? [parent.name, focus.name] : [focus.name];
    }
  }

  const examTitle = input.examId
    ? (await queryOne<{ title: string }>("SELECT title FROM exams WHERE id = $1", [input.examId]))?.title ?? null
    : null;
  const knowledgeBaseName = input.knowledgeBaseId
    ? (await queryOne<{ name: string }>("SELECT name FROM knowledge_bases WHERE id = $1", [input.knowledgeBaseId]))?.name ?? null
    : null;
  const ctx = await buildContext(
    input.userId,
    input.examId,
    input.knowledgeBaseId,
    examTitle,
    knowledgeBaseName,
    names,
    input.materialId,
    materialTitle
  );

  // Candidates for automatic filing: the subtopics of whichever materials are in
  // play, falling back to the whole exam outline. Matching is on the wording of
  // the question itself, because the model's own `topic` field was either absent
  // or a name that did not exist, which is why every question used to save with
  // no topic at all.
  const scopeIds = new Set(filteredTopics.map((t) => t.id));
  const parentIds = new Set(filteredTopics.map((t) => t.parentId).filter((v): v is string => !!v));
  let candidates = topics.filter(
    (t) => (scopeIds.has(t.id) || parentIds.has(t.id)) && (!materialTitle || !filteredTopics.length)
  );
  if (candidates.length === 0) candidates = topics;
  const subtopics = candidates.filter((t) => t.parentId);
  const parents = candidates.filter((t) => !t.parentId);
  /** Subtopic when one is a convincing match, else the exam-level topic. */
  const fileUnder = (prompt: string): string | null => {
    const sub = matchTopic(prompt, subtopics, { minScore: 3 });
    if (sub) return sub;
    const top = matchTopic(prompt, parents, { minScore: 1.2 });
    return top;
  };

  const total = Math.min(MAX_GEN, Math.max(1, Math.round(input.count || 10)));
  const seen = new Set<string>();
  const out: GenRow[] = [];
  const rejected: Record<string, number> = {};

  // Within-batch de-duplication is not enough: the same question gets asked
  // again on the next click, so compare against what is already saved too.
  const existingPrompts = input.userId
    ? (
        await query<{ prompt: string }>(
          `SELECT prompt FROM questions
            WHERE user_id = $1 AND ($2::uuid IS NULL OR exam_id = $2)
            ORDER BY created_at DESC LIMIT 400`,
          [input.userId, input.examId]
        )
      ).map((r) => r.prompt)
    : [];
  const alreadySaved = (prompt: string) => existingPrompts.some((p) => isNearDuplicate(p, prompt));
  let barrenBatches = 0;
  /** The largest context actually handed to a batch, for the diagnostics record. */
  let widestWindow = 0;
  /** Which slice of the material this batch looks at. */
  let batchIndex = 0;
  /**
   * Which window of the pool the next batch reads. Kept separate from the batch
   * number so a barren batch can jump to material that has not been mined yet
   * instead of re-reading the page that just came back empty.
   */
  let windowCursor = 0;
  /** Every prompt produced or already on file, fed back so the model diversifies. */
  const avoid = [...existingPrompts];
  // Each model call has its own budget, so a large request is a loop of them.
  // Without an overall deadline a 50-question run could keep going for an hour;
  // every batch is persisted as it lands, so stopping early still keeps the work.
  const startedAt = Date.now();
  const overallBudgetMs = input.budgetMs ?? Math.max(180_000, total * 75_000);
  /** Why the run ended early, so the caller can explain a shortfall. */
  let stopReason: "budget" | "barren" | "exhausted" | null = null;
  while (out.length < total) {
    if (Date.now() - startedAt > overallBudgetMs) {
      stopReason = "budget";
      console.warn(
        `[generate] stopping after ${out.length}/${total}: hit the ${Math.round(overallBudgetMs / 1000)}s ` +
          `overall time budget. Everything generated so far has been saved.`
      );
      break;
    }
    const target = Math.min(BATCH_SIZE, total - out.length);
    const window = rotateContext(ctx, windowCursor);
    widestWindow = Math.max(widestWindow, window.length);
    // The pool used to reach the first batch uncapped, so a 7969-character
    // context was sent into a 6286-character window and the model degraded into
    // repeats. Record what was actually sent, and say so if it ever overruns.
    if (window.length > MAX_CONTEXT_CHARS) {
      console.warn(
        `[generate] batch ${batchIndex + 1} context is ${window.length} chars, over the ${MAX_CONTEXT_CHARS}-char window`
      );
    }
    const windowNumber = windowCursor + 1;
    const batch = await runEach(
      input.userId,
      input.type,
      window,
      focusHeading(window),
      names,
      fileUnder,
      avoid,
      target,
      windowNumber,
      overallBudgetMs - (Date.now() - startedAt)
    );
    batchIndex++;
    if (batch.length === 0) {
      stopReason = "exhausted";
      break; // model stopped producing usable items
    }
    // A weak model rephrases one question five ways, and token overlap cannot
    // separate "the basic unit of input for Claude" from "the basic unit of text
    // that Claude uses" (0.5 overlap) the way meaning can, so the whole batch is
    // checked at once against everything already produced.
    const batchPrompts = batch.map((r) => String(r.prompt ?? ""));
    const dupes = await findDuplicateCandidates(input.userId, batchPrompts, [
      ...existingPrompts,
      ...out.map((o) => o.prompt),
    ]);
    const fresh: GenRow[] = [];
    for (const [index, row] of batch.entries()) {
      // A single object with no question field used to throw on .trim() and take
      // the whole run down with it; the quality gate rejects it properly instead.
      if (typeof row?.prompt !== "string" || row.prompt.trim() === "") {
        rejected["question text missing"] = (rejected["question text missing"] ?? 0) + 1;
        continue;
      }
      const key = row.prompt.trim().toLowerCase();
      if (seen.has(key)) {
        // Counted, not silently dropped: repeats used to vanish from the tally,
        // which made a run look barren with no explanation.
        rejected["repeated a question from this same run"] =
          (rejected["repeated a question from this same run"] ?? 0) + 1;
        continue;
      }
      seen.add(key);
      if (dupes.has(index) || alreadySaved(row.prompt)) {
        rejected["near-duplicate of a question you already have"] =
          (rejected["near-duplicate of a question you already have"] ?? 0) + 1;
        continue;
      }
      const verdict = validateGeneratedRow(row, input.type);
      if (!verdict.ok) {
        rejected[verdict.reason] = (rejected[verdict.reason] ?? 0) + 1;
        continue;
      }
      avoid.push(row.prompt);
      const fixed = input.forceTopicId ? { ...row, topicId: input.forceTopicId } : row;
      fresh.push(fixed);
      out.push(fixed);
      if (out.length >= total) break;
    }
    if (input.onBatch && fresh.length > 0) await input.onBatch(fresh);
    if (out.length >= total) break;
    // Every item in this batch failed the gate (or repeated): stop instead of
    // asking the model again forever.
    // Repeats used to end the run after two batches. The prompt now lists the
    // questions already produced, so give it a few chances before giving up.
    if (fresh.length === 0) {
      barrenBatches++;
      // Skip ahead so the retry lands on fresh material, not the same page.
      windowCursor = batchIndex;
    }
    if (fresh.length === 0 && barrenBatches >= BARREN_LIMIT) {
      stopReason = "barren";
      console.warn("[generate] model kept repeating itself; stopping early");
      break;
    }
    if (fresh.length > 0) {
      barrenBatches = 0;
      windowCursor = batchIndex;
    }
  }
  const dropped = Object.values(rejected).reduce((a, b) => a + b, 0);
  const detail = Object.entries(rejected)
    .sort((a, b) => b[1] - a[1])
    .map(([reason, n]) => `${reason} (${n})`)
    .join(", ");
  if (dropped > 0) {
    console.warn(`[generate] rejected ${dropped} generated question(s): ${detail}`);
  }

  const kept = out.slice(0, total);
  input.onShortfall?.({ requested: total, created: kept.length, reason: stopReason });

  // Record the real outcome, including what the gate threw away, so a partial
  // run can be explained from the app instead of guessed at from the terminal.
  const elapsedSec = Math.round((Date.now() - startedAt) / 1000);
  const shortfall = total - kept.length;
  const level: "info" | "warn" | "error" = shortfall === 0 ? "info" : kept.length === 0 ? "error" : "warn";
  const reasons: Record<string, string> = {
    budget: `hit the ${Math.round(overallBudgetMs / 1000)}s time budget`,
    barren: "the model kept repeating itself",
    exhausted: "the model stopped producing usable questions",
  };
  const reasonText = stopReason ? reasons[stopReason] : undefined;
  await recordEvent(
    input.userId,
    level,
    "generate",
    shortfall === 0
      ? `Generated all ${total} ${input.type} question(s) in ${elapsedSec}s`
      : `Generated ${kept.length} of ${total} ${input.type} question(s) in ${elapsedSec}s` +
        (reasonText ? ` — ${reasonText}` : ""),
    {
      requested: total,
      created: kept.length,
      reason: stopReason,
      seconds: elapsedSec,
      perQuestionSec: kept.length > 0 ? Math.round(elapsedSec / kept.length) : null,
      rejected: rejected,
      poolChars: ctx.length,
      contextChars: widestWindow,
      contextWindow: MAX_CONTEXT_CHARS,
      distinctWindows: Math.ceil(ctx.length / MAX_CONTEXT_CHARS),
      outputTokens: MAX_OUTPUT_TOKENS,
      numCtx: NUM_CTX,
    }
  );
  if (kept.length === 0) {
    // Returning an empty array here produced a useless "try again" message in
    // the UI while the real reason (everything was rejected, or the model
    // never produced anything) stayed in the server log. Say it out loud.
    const because = Object.keys(rejected).length
      ? `Everything the model produced was rejected (${detail}).`
      : "The model did not return any usable items.";
    throw new AIError(
      `AI generated no questions. ${because} Try generating fewer at a time, or use a stronger/smaller-faster model.`
    );
  }
  return kept;
}

export async function persistGeneratedQuestions(
  userId: string,
  examId: string | null,
  rows: { topicId: string | null; type: string; prompt: string; choices: unknown; answer: string; explanation: string; category: string | null }[]
): Promise<number> {
  for (const r of rows) {
    const choicesJson = r.choices ? JSON.stringify(r.choices) : null;
    await query(
      `INSERT INTO questions (user_id, exam_id, topic_id, type, category, prompt, choices, answer, explanation, source)
       VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, 'ai')`,
      [userId, examId, r.topicId, r.type, r.category, r.prompt, choicesJson, r.answer, r.explanation]
    );
  }
  return rows.length;
}

export function makeQuestionSnapshot(
  row: { id: string; type: string; category: string | null; prompt: string; choices: unknown | null; answer: string | null; explanation: string | null; topic_id: string | null; points: number }
) {
  return {
    id: row.id,
    type: row.type,
    category: row.category,
    prompt: row.prompt,
    choices: row.choices,
    answer: row.answer,
    explanation: row.explanation,
    topicId: row.topic_id,
    points: row.points,
  };
}

export { abbreviated };