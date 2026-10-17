"use server";

import bcrypt from "bcryptjs";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { recordEvent } from "@/lib/diagnostics";
import { pool, query, queryOne } from "@/lib/db";
import type { PoolClient } from "pg";
import {
  createSession,
  deleteSessionCookie,
  isAdmin,
  requireUser,
  scoped,
  setSessionCookie,
  type SessionUser,
} from "@/lib/auth";
import {
  MAX_FILE_BYTES,
  MAX_UPLOAD_FILES,
  MAX_UPLOAD_TOTAL_BYTES,
  embedAndStoreChunks,
  reindexMaterial,
  extractTextFromFile,
  extractTextFromUrl,
} from "@/lib/ingest";
import { classifyUpload, titleFromPath } from "@/lib/material-path";
import { AIError, SERVER_ACTION_BUDGET_MS, actionDeadline, chatCompletion, chatJson, isAiAvailable, ragSearch, remainingActionMs, testAiConfig, type AIChatMessage, type AIConfig, type AIProvider } from "@/lib/ai";
import { generateFromAI, MAX_GEN, persistGeneratedQuestions } from "@/lib/generate";
import { interviewFeedbackPrompt, assistantSystemPrompt, syllabusExtractPrompt } from "@/lib/prompts";
import {
  allocateByWeight,
  cloneNodes,
  flattenSyllabus,
  getPreset,
  leafTopicIds,
  normalizeWeights,
  parseSyllabusOutline,
  parseWeightedBlueprint,
  sumLeafWeight,
  totalAssignedWeight,
  type SyllabusNode,
  type WeightedTopic,
} from "@/lib/syllabus";
import { ensureChatSession, getUserSettings, parseQuestions, type ChatSource } from "@/lib/data";
import type { QuizQuestion, AnswerEntry, InterviewFeedback } from "@/lib/data";
import { gradeAnswer } from "@/lib/grade";

export type ActionResult =
  | { ok: true; id?: string; redirect?: string; data?: unknown; warning?: string }
  | { ok: false; error: string };

export type ChatActionResult =
  | { ok: true; userMessage: string; reply: string; sources: ChatSource[] }
  | { ok: false; error: string };

function guard(): ActionResult {
  return { ok: false, error: "Not authenticated" };
}

function toInt(v: FormDataEntryValue | null, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function str(v: FormDataEntryValue | null): string {
  return typeof v === "string" ? v.trim() : "";
}

// ---------------------------------------------------------------- auth

export async function registerAction(prev: unknown, formData: FormData): Promise<ActionResult> {
  const name = str(formData.get("name"));
  const email = str(formData.get("email")).toLowerCase();
  const password = str(formData.get("password"));
  if (!name || !email || !password) return { ok: false, error: "All fields are required" };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { ok: false, error: "Enter a valid email address" };
  if (password.length < 8) return { ok: false, error: "Password must be at least 8 characters" };

  const exists = await queryOne("SELECT id FROM users WHERE email = $1", [email]);
  if (exists) return { ok: false, error: "An account with that email already exists" };

  const hash = await bcrypt.hash(password, 10);
  const user = await queryOne<{ id: string }>(
    "INSERT INTO users (email, password_hash, name) VALUES ($1, $2, $3) RETURNING id",
    [email, hash, name]
  );
  if (!user) return { ok: false, error: "Could not create account" };

  const token = await createSession(user.id);
  await setSessionCookie(token);
  revalidatePath("/", "layout");
  redirect("/dashboard");
}

export async function loginAction(prev: unknown, formData: FormData): Promise<ActionResult> {
  const email = str(formData.get("email")).toLowerCase();
  const password = str(formData.get("password"));
  if (!email || !password) return { ok: false, error: "Email and password are required" };

  const user = await queryOne<{ id: string; password_hash: string }>(
    "SELECT id, password_hash FROM users WHERE email = $1",
    [email]
  );
  if (!user) return { ok: false, error: "Invalid email or password" };

  const ok = await bcrypt.compare(password, user.password_hash);
  if (!ok) return { ok: false, error: "Invalid email or password" };

  const token = await createSession(user.id);
  await setSessionCookie(token);
  redirect("/dashboard");
}

export async function logoutAction(): Promise<void> {
  await deleteSessionCookie();
  redirect("/");
}

// ---------------------------------------------------------------- exams & topics

export async function createExam(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const title = str(formData.get("title"));
  if (!title) return { ok: false, error: "Exam title is required" };
  const description = str(formData.get("description"));
  const targetDate = str(formData.get("targetDate")) || null;
  const color = str(formData.get("color")) || "#6366f1";
  const exam = await queryOne<{ id: string }>(
    `INSERT INTO exams (user_id, title, description, target_date, color)
     VALUES ($1, $2, $3, $4::date, $5) RETURNING id`,
    [user.id, title, description || null, targetDate, color]
  );
  revalidatePath("/exams");
  return exam ? { ok: true, id: exam.id } : { ok: false, error: "Could not create exam" };
}

export async function updateExam(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const id = str(formData.get("id"));
  const title = str(formData.get("title"));
  if (!id || !title) return { ok: false, error: "Exam id and title are required" };
  const owned = await queryOne(`SELECT id FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [id, user.id]);
  if (!owned) return { ok: false, error: "Exam not found" };
  await query(
    `UPDATE exams SET title = $1, description = $2, target_date = $3::date, color = $4 WHERE id = $5`,
    [title, str(formData.get("description")) || null, str(formData.get("targetDate")) || null, str(formData.get("color")) || "#6366f1", id]
  );
  revalidatePath("/exams");
  revalidatePath(`/exams/${id}`);
  return { ok: true, redirect: `/exams/${id}` };
}

export async function deleteExam(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const owned = await queryOne(`SELECT id FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [id, user.id]);
  if (!owned) return { ok: false, error: "Exam not found" };
  await query("DELETE FROM exams WHERE id = $1", [id]);
  revalidatePath("/exams");
  revalidatePath("/dashboard");
  return { ok: true };
}

async function topicParentError(
  examId: string,
  parentId: string | null,
  selfId?: string
): Promise<string | null> {
  if (!parentId) return null;
  const parent = await queryOne<{ exam_id: string; parent_id: string | null }>(
    "SELECT exam_id, parent_id FROM topics WHERE id = $1",
    [parentId]
  );
  if (!parent) return "Parent topic not found";
  if (parent.exam_id !== examId) return "Parent topic must be in the same exam";
  if (selfId) {
    let cur = parent.parent_id;
    const guard = new Set<string>();
    while (cur) {
      if (cur === selfId) return "Cannot make a subtopic the parent of its own parent";
      if (guard.has(cur)) break;
      guard.add(cur);
      const up = await queryOne<{ parent_id: string | null }>("SELECT parent_id FROM topics WHERE id = $1", [cur]);
      cur = up?.parent_id ?? null;
    }
  }
  return null;
}

export async function createTopic(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const examId = str(formData.get("examId"));
  const name = str(formData.get("name"));
  if (!examId || !name) return { ok: false, error: "Topic name is required" };
  const owned = await queryOne(`SELECT id FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [examId, user.id]);
  if (!owned) return { ok: false, error: "Exam not found" };
  const parentId = str(formData.get("parentId")) || null;
  const parentErr = await topicParentError(examId, parentId);
  if (parentErr) return { ok: false, error: parentErr };
  const weightage = Math.min(100, Math.max(0, Math.round(toInt(formData.get("weightage")))));
  const description = str(formData.get("description"));
  const [r] = await query<{ m: string }>("SELECT COALESCE(max(sort_order), -1)::text AS m FROM topics WHERE exam_id = $1", [examId]);
  const nextOrder = Number(r?.m ?? -1) + 1;
  await query(
    `INSERT INTO topics (exam_id, name, weightage, description, sort_order, parent_id) VALUES ($1, $2, $3, $4, $5, $6)`,
    [examId, name, weightage, description || null, nextOrder, parentId]
  );
  revalidatePath(`/exams/${examId}`);
  revalidatePath("/exams");
  return { ok: true };
}

export async function updateTopic(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const id = str(formData.get("id"));
  const name = str(formData.get("name"));
  const weightage = Math.min(100, Math.max(0, Math.round(toInt(formData.get("weightage")))));
  const description = str(formData.get("description"));
  if (!id || !name) return { ok: false, error: "Missing fields" };
  const existing = await queryOne<{ exam_id: string }>(
    `SELECT t.exam_id, t.parent_id FROM topics t
     WHERE t.id = $1 AND t.exam_id IN (SELECT id FROM exams WHERE ${scoped(user, "user_id", 2)})`,
    [id, user.id]
  );
  if (!existing) return { ok: false, error: "Topic not found" };
  const parentId = str(formData.get("parentId")) || null;
  const parentErr = await topicParentError(existing.exam_id, parentId, id);
  if (parentErr) return { ok: false, error: parentErr };
  const t = await queryOne<{ exam_id: string }>(
    `UPDATE topics SET name = $1, weightage = $2, description = $3, parent_id = $4
     WHERE id = $5 AND exam_id IN (SELECT id FROM exams WHERE ${scoped(user, "user_id", 6)})
     RETURNING exam_id`,
    [name, weightage, description || null, parentId, id, user.id]
  );
  if (!t) return { ok: false, error: "Topic not found" };
  revalidatePath(`/exams/${t.exam_id}`);
  return { ok: true };
}

export async function deleteTopic(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const t = await queryOne<{ exam_id: string }>(
    `DELETE FROM topics WHERE id = $1 AND exam_id IN (SELECT id FROM exams WHERE user_id = $2) RETURNING exam_id`,
    [id, user.id]
  );
  if (!t) return { ok: false, error: "Topic not found" };
  revalidatePath(`/exams/${t.exam_id}`);
  return { ok: true };
}

// ------------------------------------------------------------ syllabus import

export type SyllabusPreview = {
  nodes: SyllabusNode[];
  /** How the tree was produced, shown above the review list. */
  origin: string;
  /** Weightage as imported, before the app rounds it to whole points. */
  rawTotal: number;
  examName: string | null;
};

function syllabusGuard(user: SessionUser | null): SessionUser | ActionResult {
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  return user;
}

/** Reads a pasted or uploaded syllabus without writing anything. */
export async function previewSyllabus(prev: unknown, formData: FormData): Promise<ActionResult> {
  const maybeUser = await requireUser().catch(() => null);
  const auth = syllabusGuard(maybeUser);
  if ("ok" in auth) return auth;
  const user = auth;

  const examId = str(formData.get("examId"));
  const owned = await queryOne(`SELECT id, title FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [
    examId,
    user.id,
  ]);
  if (!owned) return { ok: false, error: "Exam not found" };

  const existing = await query<{ name: string }>(
    "SELECT name FROM topics WHERE exam_id = $1 ORDER BY sort_order LIMIT 200",
    [examId]
  );

  let text = "";
  let origin = "";

  const presetId = str(formData.get("presetId"));
  if (presetId) {
    const preset = getPreset(presetId);
    if (!preset) return { ok: false, error: "Unknown syllabus preset" };
    const data: SyllabusPreview = {
      nodes: normalizeWeights(cloneNodes(preset.nodes)),
      origin: preset.source,
      rawTotal: sumLeafWeight(preset.nodes),
      examName: preset.label,
    };
    return { ok: true, data };
  }

  const kind = str(formData.get("kind"));
  if (kind === "file") {
    const file = formData.get("file");
    if (!(file instanceof File) || file.size === 0) {
      return { ok: false, error: "Choose a syllabus file first" };
    }
    if (file.size > MAX_FILE_BYTES) {
      return { ok: false, error: "That file is over 15MB — upload a smaller document" };
    }
    try {
      text = await extractTextFromFile(Buffer.from(await file.arrayBuffer()), file.name);
    } catch (err) {
      return { ok: false, error: `Could not read that file: ${err instanceof Error ? err.message : "unknown error"}` };
    }
    origin = file.name;
  } else {
    text = str(formData.get("text"));
    origin = "Pasted text";
  }

  if (text.trim().length < 20) {
    // "Add some syllabus text" is actively misleading when a file was uploaded
    // — it points at the paste box rather than at the file that failed to read.
    return kind === "file"
      ? {
          ok: false,
          error:
            `No readable text came out of "${origin}". If it is a scanned or image-only PDF it has nothing to ` +
            "extract — try the text version, or paste the topic list with its percentages.",
        }
      : { ok: false, error: "Add some syllabus text, or upload the exam guide" };
  }
  if (text.length > 60_000) text = `${text.slice(0, 60_000)}\n[truncated]`;

  // A syllabus that already spells out its percentages is read directly — no
  // model call, so it stays fast, free, and exactly faithful to the document.
  // The blueprint shape is tried first because it is the more specific of the two.
  const parsed = parseWeightedBlueprint(text) ?? parseSyllabusOutline(text);
  if (parsed) {
    const rawTotal = sumLeafWeight(parsed);
    const data: SyllabusPreview = {
      nodes: normalizeWeights(parsed),
      origin: `${origin} · read directly from the document`,
      rawTotal,
      examName: null,
    };
    return { ok: true, data };
  }

  if (!(await isAiAvailable(user.id))) {
    return {
      ok: false,
      error:
        "That document has no percentages I can read, and no AI provider is configured to work them out. " +
        "Set one up in Settings, or paste the syllabus as an outline with percentages (e.g. \"Agents — 25%\").",
    };
  }

  try {
    const { system, user: promptUser } = syllabusExtractPrompt({
      text,
      existingTopicNames: existing.map((t) => t.name),
    });
    const raw = await chatJson<{
      exam?: string | null;
      topics?: unknown;
    }>(user.id, system, promptUser, { temperature: 0.1 });

    const nodes = coerceModelTopics(raw?.topics);
    if (nodes.length === 0) return { ok: false, error: "No topics could be read from that document" };

    // Read the document's own total before normalising, so the reviewer can see
    // how far the source percentages were from 100.
    const rawTotal = sumLeafWeight(nodes);
    const data: SyllabusPreview = {
      nodes: normalizeWeights(nodes),
      origin: `${origin} · extracted with AI`,
      rawTotal,
      examName: typeof raw?.exam === "string" ? raw.exam.slice(0, 160) : null,
    };
    return { ok: true, data };
  } catch (err) {
    await recordEvent(
      user.id,
      "error",
      "generate",
      "Syllabus extraction failed",
      { error: err instanceof Error ? err.message : String(err) }
    ).catch(() => {});
    return { ok: false, error: err instanceof Error ? err.message : "Could not read that syllabus" };
  }
}

/**
 * Validates whatever a model returned into a tree we are willing to write.
 * Depth is capped at two levels because that is all the topics table models.
 */
function coerceModelTopics(value: unknown): SyllabusNode[] {
  if (!Array.isArray(value)) return [];
  const clean = (raw: unknown, depth: number): SyllabusNode | null => {
    if (!raw || typeof raw !== "object") return null;
    const o = raw as Record<string, unknown>;
    const name = typeof o.name === "string" ? o.name.trim().slice(0, 160) : "";
    if (!name) return null;
    const w = Number(o.weight);
    const weight = Number.isFinite(w) ? Math.min(100, Math.max(0, w)) : 0;
    const note = typeof o.note === "string" ? o.note.trim().slice(0, 400) || null : null;

    const rawKids = depth < 1 && Array.isArray(o.children) ? o.children : [];
    const children = rawKids.map((k) => clean(k, depth + 1)).filter((k): k is SyllabusNode => !!k);
    // A grouping heading must not also hold weight, or its share is counted twice.
    return { name, weight: children.length > 0 ? 0 : weight, note, children: children.length ? children : undefined };
  };
  return value.map((v) => clean(v, 0)).filter((n): n is SyllabusNode => !!n);
}

/** Writes a reviewed syllabus into the topics table. */
export async function applySyllabus(prev: unknown, formData: FormData): Promise<ActionResult> {
  const maybeUser = await requireUser().catch(() => null);
  const auth = syllabusGuard(maybeUser);
  if ("ok" in auth) return auth;
  const user = auth;

  const examId = str(formData.get("examId"));
  const owned = await queryOne(`SELECT id FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [
    examId,
    user.id,
  ]);
  if (!owned) return { ok: false, error: "Exam not found" };

  let incoming: SyllabusNode[];
  try {
    const parsed: unknown = JSON.parse(str(formData.get("plan")) || "[]");
    incoming = coerceModelTopics(parsed);
  } catch {
    return { ok: false, error: "The reviewed syllabus could not be read — try importing it again" };
  }
  if (incoming.length === 0) return { ok: false, error: "There are no topics to save" };
  if (incoming.length > 60) {
    return { ok: false, error: `That is ${incoming.length} topics — the limit is 60. Split the syllabus into two exams.` };
  }

  const nodes = normalizeWeights(incoming);
  const mode = str(formData.get("mode")) === "merge" ? "merge" : "replace";
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    if (mode === "replace") {
      // questions.topic_id is ON DELETE SET NULL, so this unlinks the question
      // bank from the old tree rather than deleting any questions.
      await client.query("DELETE FROM topics WHERE exam_id = $1", [examId]);
    }

    let order = 0;
    for (const node of nodes) {
      const parentId = await upsertTopic(client, examId, node, null, mode, order++);
      const children = node.children ?? [];
      for (let i = 0; i < children.length; i++) {
        await upsertTopic(client, examId, children[i], parentId, mode, order++);
        void i;
      }
    }

    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    return { ok: false, error: err instanceof Error ? err.message : "Could not save the syllabus" };
  } finally {
    client.release();
  }

  revalidatePath(`/exams/${examId}`);
  revalidatePath("/exams");
  revalidatePath("/mock");
  revalidatePath("/dashboard");
  return {
    ok: true,
    data: {
      topics: flattenSyllabus(nodes).length,
      total: sumLeafWeight(nodes),
    },
  };
}

/**
 * Inserts a topic, or updates the existing one with the same name. Re-importing a
 * syllabus therefore refreshes weightage in place instead of creating a second
 * copy of every topic and orphaning the questions filed against it.
 */
async function upsertTopic(
  client: PoolClient,
  examId: string,
  node: SyllabusNode,
  parentId: string | null,
  mode: "merge" | "replace",
  order: number
): Promise<string> {
  if (mode === "merge") {
    const { rows } = await client.query(
      `INSERT INTO topics (exam_id, name, weightage, description, sort_order, parent_id)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (exam_id, parent_id, lower(name)) WHERE parent_id IS NOT NULL
       DO UPDATE SET weightage = EXCLUDED.weightage,
                     description = COALESCE(EXCLUDED.description, topics.description),
                     sort_order = EXCLUDED.sort_order
       RETURNING id`,
      [examId, node.name, node.weight, node.note ?? null, order, parentId]
    );
    if (rows[0]) return rows[0].id;
  }

  // Top-level topics have no unique index (subtopics are what collide), so they
  // are matched by name before inserting.
  const existing = await client.query<{ id: string }>(
    parentId === null
      ? `SELECT id FROM topics WHERE exam_id = $1 AND parent_id IS NULL AND lower(name) = lower($2)`
      : `SELECT id FROM topics WHERE exam_id = $1 AND parent_id = $2 AND lower(name) = lower($3)`,
    parentId === null ? [examId, node.name] : [examId, parentId, node.name]
  );
  if (existing.rows[0]) {
    await client.query("UPDATE topics SET weightage = $1, description = $2, sort_order = $3 WHERE id = $4", [
      node.weight,
      node.note ?? null,
      order,
      existing.rows[0].id,
    ]);
    return existing.rows[0].id;
  }

  const { rows } = await client.query<{ id: string }>(
    `INSERT INTO topics (exam_id, name, weightage, description, sort_order, parent_id)
     VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
    [examId, node.name, node.weight, node.note ?? null, order, parentId]
  );
  return rows[0].id;
}

/** Rescales an existing plan so its weights come back to exactly 100. */
export async function balanceTopicWeights(input: { examId: string }): Promise<ActionResult> {
  const maybeUser = await requireUser().catch(() => null);
  const auth = syllabusGuard(maybeUser);
  if ("ok" in auth) return auth;
  const user = auth;

  const owned = await queryOne(`SELECT id FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [
    input.examId,
    user.id,
  ]);
  if (!owned) return { ok: false, error: "Exam not found" };

  const topics = await query<WeightedTopic>(
    `SELECT id, name, weightage, parent_id AS "parentId" FROM topics WHERE exam_id = $1 ORDER BY sort_order`,
    [input.examId]
  );
  if (topics.length === 0) return { ok: false, error: "This exam has no topics yet" };

  const leaves = leafTopicIds(topics);
  const scaling = normalizeWeights(
    topics.filter((t) => leaves.has(t.id)).map((t) => ({ name: t.name, weight: t.weightage }))
  );
  const byName = new Map(scaling.map((n) => [n.name.toLowerCase(), n.weight]));

  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    for (const t of topics) {
      if (!leaves.has(t.id)) continue;
      const weight = byName.get(t.name.toLowerCase());
      if (weight !== undefined && weight !== t.weightage) {
        await client.query("UPDATE topics SET weightage = $1 WHERE id = $2", [weight, t.id]);
      }
    }
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    return { ok: false, error: err instanceof Error ? err.message : "Could not rebalance weightage" };
  } finally {
    client.release();
  }

  revalidatePath(`/exams/${input.examId}`);
  return { ok: true, data: { total: totalAssignedWeight(topics) } };
}


// ---------------------------------------------------------------- materials

export async function createKnowledgeBase(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const name = str(formData.get("name"));
  if (!name) return { ok: false, error: "A name is required" };
  const description = str(formData.get("description")) || null;
  const kb = await queryOne<{ id: string }>(
    "INSERT INTO knowledge_bases (user_id, name, description) VALUES ($1, $2, $3) RETURNING id",
    [user.id, name, description]
  );
  revalidatePath("/materials");
  return kb ? { ok: true, id: kb.id } : { ok: false, error: "Could not create knowledge base" };
}

export async function deleteKnowledgeBase(id: string, opts?: { keepMaterials?: boolean }): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const owned = await queryOne(`SELECT id FROM knowledge_bases WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [id, user.id]);
  if (!owned) return { ok: false, error: "Knowledge base not found" };
  if (!opts?.keepMaterials) {
    await query("DELETE FROM materials WHERE knowledge_base_id = $1", [id]);
  }
  await query("DELETE FROM knowledge_bases WHERE id = $1", [id]);
  revalidatePath("/materials");
  return { ok: true };
}

/** Inserts one material (multi-file uploads call this per doc) and indexes it for RAG. */
async function storeMaterial(
  user: { id: string },
  args: {
    examId: string | null;
    knowledgeBaseId: string | null;
    title: string;
    type: string;
    source: string | null;
    content: string;
  }
): Promise<{ ok: boolean; error?: string; status?: "added" | "unchanged" | "updated" }> {
  // Re-uploading a folder must not leave a second copy of every file behind, so
  // a file already imported from the same path is refreshed instead of inserted.
  if (args.source) {
    const existing = await queryOne<{ id: string; content: string }>(
      `SELECT id, content FROM materials WHERE user_id = $1 AND source = $2 LIMIT 1`,
      [user.id, args.source]
    );
    if (existing) {
      if (existing.content === args.content) return { ok: true, status: "unchanged" };
      await query(
        `UPDATE materials SET title = $1, content = $2, exam_id = $3, knowledge_base_id = $4
         WHERE id = $5`,
        [args.title, args.content, args.examId, args.knowledgeBaseId, existing.id]
      );
      try {
        await reindexMaterial(user.id, existing.id, args.content);
      } catch {
        // embeddings are optional; RAG will just be less effective
      }
      return { ok: true, status: "updated" };
    }
  }

  const material = await queryOne<{ id: string }>(
    `INSERT INTO materials (user_id, exam_id, knowledge_base_id, title, type, source, content)
     VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id`,
    [user.id, args.examId, args.knowledgeBaseId, args.title, args.type, args.source, args.content]
  );
  if (!material) return { ok: false, error: "Could not store material" };
  try {
    await embedAndStoreChunks(user.id, material.id, args.content);
  } catch {
    // embeddings are optional; RAG will just be less effective
  }
  return { ok: true, status: "added" };
}

export async function addMaterials(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const examId = str(formData.get("examId")) || null;
  let knowledgeBaseId = str(formData.get("knowledgeBaseId")) || null;
  const kind = str(formData.get("kind")); // text | url | file
  const titleInput = str(formData.get("title"));

  let examIdFinal: string | null = examId;
  if (examId) {
    const owned = await queryOne(`SELECT id FROM exams WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [examId, user.id]);
    if (!owned) examIdFinal = null;
  }
  if (knowledgeBaseId) {
    const owned = await queryOne(`SELECT id FROM knowledge_bases WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [knowledgeBaseId, user.id]);
    if (!owned) knowledgeBaseId = null;
  }

  let created = 0;
  let alreadyThere = 0;
  const errors: string[] = [];

  if (kind === "file") {
    const files = formData.getAll("files").filter((f): f is File => f instanceof File && f.size > 0);
    if (files.length === 0) return { ok: false, error: "Choose at least one file or folder" };

    // `webkitRelativePath` is a client-only property and never survives the
    // FormData round trip, so the browser sends the paths alongside the files
    // and they are matched back up by position here.
    let paths: string[] = [];
    try {
      const parsed: unknown = JSON.parse(str(formData.get("paths")) || "[]");
      if (Array.isArray(parsed)) paths = parsed.map((p) => String(p));
    } catch {
      paths = [];
    }
    const pathFor = (file: File, index: number): string => paths[index] || file.name;

    if (files.length > MAX_UPLOAD_FILES) {
      return {
        ok: false,
        error: `That is ${files.length} files — the limit is ${MAX_UPLOAD_FILES}. Upload the folder in smaller batches.`,
      };
    }
    const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
    if (totalBytes > MAX_UPLOAD_TOTAL_BYTES) {
      return {
        ok: false,
        error: `That selection is ${(totalBytes / 1024 / 1024).toFixed(0)}MB — the limit is ${MAX_UPLOAD_TOTAL_BYTES / 1024 / 1024}MB per upload.`,
      };
    }

    for (const [index, file] of files.entries()) {
      const path = pathFor(file, index);
      const verdict = classifyUpload(path);
      if (!verdict.ok) {
        errors.push(`Skipped "${path}" (${verdict.reason})`);
        continue;
      }
      if (file.size > MAX_FILE_BYTES) {
        errors.push(`Skipped "${path}" (over 15MB)`);
        continue;
      }
      let content: string;
      try {
        const buf = Buffer.from(await file.arrayBuffer());
        content = await extractTextFromFile(buf, path);
      } catch (err) {
        errors.push(`Skipped "${path}" (${err instanceof Error ? err.message : "could not read"})`);
        continue;
      }
      if (content.trim().length < 30) {
        errors.push(`Skipped "${path}" (no readable text)`);
        continue;
      }
      // Folder uploads keep their folder structure so two files with the same
      // name in different chapters stay distinguishable in the bank.
      const title = titleFromPath(path) || titleInput;
      const res = await storeMaterial(user, {
        examId: examIdFinal ?? null,
        knowledgeBaseId,
        title,
        type: "FILE",
        source: path,
        content,
      });
      if (res.ok) {
        if (res.status === "added") created++;
        else if (res.status === "unchanged") alreadyThere++;
      } else if (res.error) {
        errors.push(res.error);
      }
    }
    if (created === 0 && alreadyThere === 0 && errors.length > 0) {
      return { ok: false, error: `Nothing was added. ${errors.slice(0, 6).join("; ")}` };
    }
  } else if (kind === "url") {
    const url = str(formData.get("url"));
    if (!url) return { ok: false, error: "Website URL is required" };
    let content = "";
    let autoTitle = titleInput;
    try {
      const r = await extractTextFromUrl(url);
      content = r.text;
      autoTitle = titleInput || r.title;
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
    if (content.trim().length < 30) return { ok: false, error: "Not enough content extracted from that URL" };
    const res = await storeMaterial(user, { examId: examIdFinal ?? null, knowledgeBaseId, title: autoTitle, type: "URL", source: url, content });
    if (res.ok) {
      if (res.status === "unchanged") alreadyThere++;
      else created++;
    } else if (res.error) {
      errors.push(res.error);
    }
  } else {
    const text = str(formData.get("text"));
    if (text.trim().length < 30) return { ok: false, error: "Pasted notes are too short — add more text" };
    const res = await storeMaterial(user, {
      examId: examIdFinal ?? null,
      knowledgeBaseId,
      title: titleInput || "Pasted notes",
      type: "TEXT",
      source: null,
      content: text,
    });
    if (res.ok) {
      if (res.status === "unchanged") alreadyThere++;
      else created++;
    } else if (res.error) {
      errors.push(res.error);
    }
  }

  revalidatePath("/materials");
  revalidatePath("/dashboard");
  if (created === 0) {
    return { ok: false, error: errors[0] ?? "Nothing was added — check the content/size limits" };
  }
  // A bare "9 skipped" is unactionable, so the reasons travel back with the
  // result and are also logged, in case the page is closed before they are read.
  if (errors.length > 0) {
    console.warn(`[materials] ${errors.length} file(s) skipped:`, errors);
    // The bare "N skipped" in the UI left no way to find out which files or why.
    await recordEvent(user.id, "warn", "upload", `${errors.length} file(s) skipped during upload`, {
      added: created,
      skipped: errors.length,
      files: errors.slice(0, 50).map((e) => (typeof e === "string" ? e : String(e))),
    });
  }
  const notes = [` · ${errors.length} skipped`];
  if (alreadyThere > 0) notes.push(` · ${alreadyThere} already imported`);
  return {
    ok: true,
    data: { created, note: notes.join(""), skipped: errors, alreadyThere },
  };
}

export async function deleteMaterial(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const owned = await queryOne(`SELECT id FROM materials WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [id, user.id]);
  if (!owned) return { ok: false, error: "Material not found" };
  await query("DELETE FROM materials WHERE id = $1", [id]);
  revalidatePath("/materials");
  return { ok: true };
}

// ---------------------------------------------------------------- questions (manual)

export async function addQuestion(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const examId = str(formData.get("examId")) || null;
  const topicId = str(formData.get("topicId")) || null;
  const type = str(formData.get("type")) || "mcq";
  const category = str(formData.get("category")) || null;
  const prompt = str(formData.get("prompt"));
  if (!prompt) return { ok: false, error: "Question prompt is required" };

  let choices: { text: string; correct: boolean }[] | null = null;
  let answer = str(formData.get("answer"));
  const explanation = str(formData.get("explanation"));

  if (type === "mcq") {
    // 4 or 5 options; a blank 5th is dropped, but a hole in the middle is an error.
    const options = [1, 2, 3, 4, 5].map((i) => str(formData.get(`option${i}`)));
    while (options.length > 0 && !options[options.length - 1]) options.pop();
    if (options.length < 4) return { ok: false, error: "An MCQ needs at least 4 options" };
    if (options.length > 5) return { ok: false, error: "An MCQ can have at most 5 options" };
    if (options.some((o) => !o)) return { ok: false, error: "All options are required — no gaps allowed" };
    if (new Set(options.map((o) => o.toLowerCase())).size !== options.length) {
      return { ok: false, error: "Options must be different from each other" };
    }
    const correctIdx = toInt(formData.get("correctIndex"));
    if (correctIdx < 0 || correctIdx >= options.length) return { ok: false, error: "Pick the correct option" };
    choices = options.map((text, idx) => ({ text, correct: idx === correctIdx }));
    answer = options[correctIdx];
  } else if (type === "true_false") {
    const correct = formData.get("correct") === "true";
    choices = [
      { text: "True", correct },
      { text: "False", correct: !correct },
    ];
    answer = correct ? "True" : "False";
  } else if (type === "short" || type === "interview") {
    if (!answer) return { ok: false, error: "A model answer is required" };
  }

  await query(
    `INSERT INTO questions (user_id, exam_id, topic_id, type, category, prompt, choices, answer, explanation, source)
     VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, 'manual')`,
    [user.id, examId, topicId, type, category, prompt, choices ? JSON.stringify(choices) : null, answer || null, explanation || null]
  );
  revalidatePath("/question-bank");
  revalidatePath(`/exams/${examId ?? ""}`);
  return { ok: true };
}

export async function deleteQuestion(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const owned = await queryOne(`SELECT id FROM questions WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [id, user.id]);
  if (!owned) return { ok: false, error: "Question not found" };
  await query("DELETE FROM questions WHERE id = $1", [id]);
  revalidatePath("/question-bank");
  return { ok: true };
}

/**
 * Files a question under a different topic or subtopic.
 *
 * Automatic filing covers most questions, but a question about, say, storing an
 * API key shares no vocabulary with any subtopic name, so it needs a human.
 */
export async function setQuestionTopic(questionId: string, topicId: string | null): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const owned = await queryOne<{ id: string }>(
    `SELECT id FROM questions WHERE id = $1 AND ${scoped(user, "user_id", 2)}`,
    [questionId, user.id]
  );
  if (!owned) return { ok: false, error: "Question not found" };
  if (topicId) {
    const topic = await queryOne<{ id: string }>("SELECT id FROM topics WHERE id = $1", [topicId]);
    if (!topic) return { ok: false, error: "That topic no longer exists" };
  }
  await query("UPDATE questions SET topic_id = $1 WHERE id = $2", [topicId, questionId]);
  revalidatePath("/question-bank");
  revalidatePath("/exams");
  return { ok: true };
}

// ---------------------------------------------------------------- AI generation

export async function generateQuestions(input: {
  examId: string | null;
  knowledgeBaseId?: string | null;
  topicIds: string[];
  materialId?: string | null;
  type: string;
  count: number;
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const count = Math.min(MAX_GEN, Math.max(1, Math.round(input.count || 10)));
  if (!["mcq", "true_false", "short"].includes(input.type)) {
    return { ok: false, error: "Pick mcq, true/false or short answer" };
  }
  const deadline = actionDeadline();
  try {
    let kbId = input.knowledgeBaseId || null;
    let contextUserId = user.id;
    if (kbId) {
      const kb = await queryOne<{ id: string; user_id: string }>(
        `SELECT id, user_id FROM knowledge_bases WHERE id = $1 AND ${scoped(user, "user_id", 2)}`,
        [kbId, user.id]
      );
      if (!kb) kbId = null;
      // Admin may generate from another user's knowledge base — read their
      // material but still save the results to the admin's own workspace.
      else if (kb.user_id !== user.id) contextUserId = kb.user_id;
    }
    let created = 0;
    const shortfall: { reason: string | null } = { reason: null };
    await generateFromAI({
      userId: contextUserId,
      examId: input.examId,
      knowledgeBaseId: kbId,
      topicIds: input.topicIds,
      materialId: input.materialId,
      forceTopicId: input.topicIds.length === 1 ? input.topicIds[0] : null,
      type: input.type as "mcq" | "true_false" | "short",
      count,
      budgetMs: remainingActionMs(deadline),
      onBatch: async (batch) => {
        created += await persistGeneratedQuestions(user.id, input.examId, batch);
      },
      onShortfall: (info) => {
        shortfall.reason = info.reason;
      },
    });
    if (created === 0) return { ok: false, error: "AI generated no questions — try again" };
    // Asking for 50 and silently getting 4 is worse than saying so: on this
    // hardware each question takes about a minute, and a weak model burns whole
    // batches re-asking things it already produced.
    if (created < count) {
      const why =
        shortfall.reason === "budget"
          ? `it hit the time budget for ${count} questions on this machine`
          : shortfall.reason === "barren"
            ? "the model kept repeating itself"
            : "the model stopped producing usable questions";
      console.warn(`[generateQuestions] asked for ${count}, created ${created}: ${why}`);
      return {
        ok: true,
        data: { created },
        warning: `Created ${created} of ${count} — ${why}. Everything produced was saved. Try a smaller batch, or a faster model.`,
      };
    }
    revalidatePath("/question-bank");
    revalidatePath("/dashboard");
    return { ok: true, data: { created } };
  } catch (err) {
    if (err instanceof AIError) return { ok: false, error: err.message };
    return { ok: false, error: err instanceof Error ? err.message : "Generation failed" };
  }
}

export async function generateFlashcards(input: {
  examId: string | null;
  knowledgeBaseId?: string | null;
  topicIds: string[];
  materialId?: string | null;
  count: number;
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const count = Math.min(MAX_GEN, Math.max(1, Math.round(input.count || 10)));
  const deadline = actionDeadline();
  try {
    let kbId = input.knowledgeBaseId || null;
    let contextUserId = user.id;
    if (kbId) {
      const kb = await queryOne<{ id: string; user_id: string }>(
        `SELECT id, user_id FROM knowledge_bases WHERE id = $1 AND ${scoped(user, "user_id", 2)}`,
        [kbId, user.id]
      );
      if (!kb) kbId = null;
      else if (kb.user_id !== user.id) contextUserId = kb.user_id;
    }
    let created = 0;
    await generateFromAI({
      userId: contextUserId,
      examId: input.examId,
      knowledgeBaseId: kbId,
      topicIds: input.topicIds,
      materialId: input.materialId,
      forceTopicId: input.topicIds.length === 1 ? input.topicIds[0] : null,
      type: "flashcard",
      count,
      budgetMs: remainingActionMs(deadline),
      onBatch: async (batch) => {
        for (const r of batch) {
          await query(
            `INSERT INTO flashcards (user_id, exam_id, topic_id, front, back, source)
             VALUES ($1, $2, $3, $4, $5, 'ai')`,
            [user.id, input.examId, r.topicId, r.prompt, r.answer]
          );
          created++;
        }
      },
    });
    if (created === 0) return { ok: false, error: "AI generated no flashcards — try again" };
    revalidatePath("/flashcards");
    return { ok: true, data: { created } };
  } catch (err) {
    if (err instanceof AIError) return { ok: false, error: err.message };
    return { ok: false, error: err instanceof Error ? err.message : "Generation failed" };
  }
}

// ---------------------------------------------------------------- flashcards

export async function addFlashcard(input: {
  examId: string | null;
  topicId: string | null;
  front: string;
  back: string;
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  if (!input.front || !input.back) return { ok: false, error: "Both sides of the card are required" };
  await query(
    `INSERT INTO flashcards (user_id, exam_id, topic_id, front, back, source) VALUES ($1, $2, $3, $4, $5, 'manual')`,
    [user.id, input.examId, input.topicId, input.front, input.back]
  );
  revalidatePath("/flashcards");
  return { ok: true };
}

export async function deleteFlashcard(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const owned = await queryOne(`SELECT id FROM flashcards WHERE id = $1 AND ${scoped(user, "user_id", 2)}`, [id, user.id]);
  if (!owned) return { ok: false, error: "Card not found" };
  await query("DELETE FROM flashcards WHERE id = $1", [id]);
  revalidatePath("/flashcards");
  return { ok: true };
}

// Leitner intervals: daily, 2d, 5d, 12d, 25d
const LEITNER_INTERVALS = [1, 2, 5, 12, 25];

export async function reviewFlashcard(id: string, correct: boolean): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const card = await queryOne<{ id: string; box: number; reps: number; lapses: number }>(
    `SELECT id, box, reps, lapses FROM flashcards WHERE id = $1 AND ${scoped(user, "user_id", 2)}`,
    [id, user.id]
  );
  if (!card) return { ok: false, error: "Card not found" };

  let box = card.box;
  let lapses = card.lapses;
  if (correct) {
    box = Math.min(4, box + 1);
  } else {
    box = 0;
    lapses += 1;
  }
  const reps = card.reps + 1;
  const interval = LEITNER_INTERVALS[box] ?? 30;

  await query(
    `UPDATE flashcards
     SET box = $1, reps = $2, lapses = $3, interval_days = $4, due_at = now() + ($4 || ' days')::interval, last_reviewed_at = now()
     WHERE id = $5`,
    [box, reps, lapses, interval, id]
  );
  revalidatePath("/flashcards");
  return { ok: true, data: { box: 4 - box } };
}

// ---------------------------------------------------------------- quiz & mock

export type SubmittedAnswer = {
  questionId: string;
  chosen?: string | number | boolean | null;
  text?: string;
  selfCorrect?: boolean;
};

async function buildQuestionPool(
  user: SessionUser,
  examId: string | null
): Promise<QuizQuestion[]> {
  const visibility = isAdmin(user)
    ? scoped(user, "user_id")
    : `(user_id = $1 OR exam_id IN (SELECT exam_id FROM content_grants WHERE user_id = $1 AND exam_id IS NOT NULL)
        OR (exam_id IS NULL AND EXISTS (SELECT 1 FROM content_grants WHERE user_id = $1 AND exam_id IS NULL)))`;
  const rows = await query<QuizQuestion & { choices: QuizQuestion["choices"] }>(
    `SELECT id, type, category, prompt, choices, answer, explanation, topic_id AS "topicId", points
     FROM questions
     WHERE ${visibility} AND ($2::uuid IS NULL OR exam_id = $2) AND type IN ('mcq','true_false','short')
     ORDER BY random()`,
    [user.id, examId]
  );
  return rows;
}

function takeFromBank(pool: QuizQuestion[], count: number): QuizQuestion[] {
  return pool.slice(0, count);
}

export async function createQuiz(input: {
  examId: string | null;
  topicId: string | null;
  mode?: "quiz" | "mock";
  count: number;
  types?: string[];
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (input.examId && !isAdmin(user)) {
    const owned = await queryOne(
      `SELECT id FROM exams WHERE id = $1 AND
         (user_id = $2 OR id IN (SELECT exam_id FROM content_grants WHERE user_id = $2 AND exam_id IS NOT NULL))`,
      [input.examId, user.id]
    );
    if (!owned) return { ok: false, error: "Exam not found" };
  }
  const mode = input.mode ?? "quiz";
  const count = Math.min(60, Math.max(1, Math.round(input.count || 10)));

  const pool = await buildQuestionPool(user, input.examId);
  let filtered = pool;
  if (input.topicId) filtered = pool.filter((q) => q.topicId === input.topicId);
  const requestedTypes = input.types ?? [];
  if (requestedTypes.length > 0) filtered = filtered.filter((q) => requestedTypes.includes(q.type));

  const quiz: QuizQuestion[] = takeFromBank(filtered, count);

  // Top up with AI-generated questions if the bank is too small
  let aiAdded = 0;
  if (quiz.length < count) {
    const shortfall = count - quiz.length;
    const types: Array<"mcq" | "true_false" | "short"> = input.types?.includes("short")
      ? ["mcq", "true_false", "short"]
      : ["mcq", "true_false"];
    const type = types[Math.floor(Math.random() * types.length)];
    const missing = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      topicIds: input.topicId ? [input.topicId] : [],
      type,
      count: shortfall,
    }).catch(() => []);
    aiAdded = missing.length;
    const missingId = crypto.randomUUID();
    for (const row of missing) {
      quiz.push({
        id: missingId + quiz.length,
        type: row.type,
        category: row.category,
        prompt: row.prompt,
        choices: row.choices as QuizQuestion["choices"],
        answer: row.answer,
        explanation: row.explanation,
        topicId: row.topicId,
        points: 1,
      });
    }
    await persistGeneratedQuestions(user.id, input.examId, missing).catch(() => {});
  }

  const title =
    mode === "mock"
      ? "Mock Exam"
      : input.topicId
        ? "Topic practice"
        : input.examId
          ? "Practice quiz"
          : "Mixed practice";
  const session = await queryOne<{ id: string }>(
    `INSERT INTO quiz_sessions (user_id, exam_id, topic_id, mode, title, num_questions, questions)
     VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) RETURNING id`,
    [user.id, input.examId, input.topicId, mode, title, quiz.length, JSON.stringify(quiz)]
  );
  if (!session) return { ok: false, error: "Could not start a session" };
  revalidatePath("/dashboard");
  return { ok: true, id: session.id, data: { aiAdded } };
}

export async function submitQuiz(sessionId: string, answers: SubmittedAnswer[]): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const session = await queryOne<{ id: string; questions: unknown; started_at: Date }>(
    `SELECT id, questions, started_at FROM quiz_sessions WHERE id = $1 AND ${scoped(user, "user_id", 2)} AND completed_at IS NULL`,
    [sessionId, user.id]
  );
  if (!session) return { ok: false, error: "Session not found or already completed" };

  const questions = (Array.isArray(session.questions) ? session.questions : JSON.parse(String(session.questions))) as QuizQuestion[];

  const entries: AnswerEntry[] = questions.map((q) => {
    const a = answers.find((x) => x.questionId === q.id);
    const { correct, got } = gradeAnswer(q, a ?? { questionId: q.id });
    const chosen =
      a?.chosen === true || a?.chosen === false ? String(a.chosen) : (a?.chosen ?? null);
    return {
      questionId: q.id,
      topicId: q.topicId ?? null,
      type: q.type,
      chosen,
      text: a?.text ?? undefined,
      correct,
      points: q.points,
      got,
      explanation: q.explanation ?? null,
      feedback: null,
    };
  });

  const score = entries.reduce((s, e) => s + (e.got ?? 0), 0);
  const total = entries.reduce((s, e) => s + (e.points ?? 1), 0);
  const durationSec = Math.max(
    1,
    Math.round((Date.now() - new Date(session.started_at).getTime()) / 1000)
  );

  await query(
    `UPDATE quiz_sessions SET answers = $1::jsonb, score = $2, total = $3, completed_at = now(), duration_sec = $4 WHERE id = $5`,
    [JSON.stringify(entries), score, total, durationSec, sessionId]
  );
  revalidatePath("/dashboard");
  return { ok: true, id: sessionId };
}

export type AnswerCheck = {
  correct: boolean;
  got: number;
  points: number;
  /** Index of the correct option for mcq, null for other types. */
  correctIndex: number | null;
  /** "true" | "false" for true_false, otherwise the correct option text. */
  correctValue: string | null;
  explanation: string | null;
};

/**
 * Grades a single in-progress answer against the unsanitized question snapshot so
 * the client can show instant feedback. Read-only: final scoring still happens
 * in submitQuiz, so checking an answer never changes the score.
 */
export async function checkAnswer(
  sessionId: string,
  questionId: string,
  chosen: SubmittedAnswer["chosen"]
): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const session = await queryOne<{ questions: unknown }>(
    `SELECT questions FROM quiz_sessions
     WHERE id = $1 AND ${scoped(user, "user_id", 2)} AND completed_at IS NULL`,
    [sessionId, user.id]
  );
  if (!session) return { ok: false, error: "Session not found or already completed" };

  const question = parseQuestions(session.questions).find((q) => q.id === questionId);
  if (!question) return { ok: false, error: "Question is not part of this session" };
  if (question.type === "short") {
    return { ok: false, error: "Short answers are graded by you on the results page" };
  }
  if (question.choices?.find((c) => c.correct) === undefined) {
    return { ok: false, error: "This question has no answer key" };
  }

  const { correct, got } = gradeAnswer(question, { chosen });
  const correctIndex = question.choices.findIndex((c) => c.correct);
  const correctText = correctIndex >= 0 ? (question.choices[correctIndex]?.text ?? null) : null;

  const data: AnswerCheck = {
    correct,
    got,
    points: question.points,
    correctIndex: question.type === "mcq" && correctIndex >= 0 ? correctIndex : null,
    correctValue:
      question.type === "true_false"
        ? (correctText?.toLowerCase() === "true" ? "true" : "false")
        : correctText,
    explanation: question.explanation ?? null,
  };
  return { ok: true, data };
}

export async function selfGradeAnswer(sessionId: string, questionId: string, correctValue: boolean): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const session = await queryOne<{ id: string; answers: unknown }>(
    `SELECT id, answers FROM quiz_sessions WHERE id = $1 AND ${scoped(user, "user_id", 2)}`,
    [sessionId, user.id]
  );
  if (!session) return { ok: false, error: "Session not found" };
  const entries = (Array.isArray(session.answers) ? session.answers : JSON.parse(String(session.answers))) as AnswerEntry[];
  const entry = entries.find((e) => e.questionId === questionId);
  if (!entry) return { ok: false, error: "Answer not found" };
  entry.correct = correctValue;
  entry.got = correctValue ? entry.points ?? 1 : 0;
  const score = entries.reduce((s, e) => s + (e.got ?? 0), 0);
  const total = entries.reduce((s, e) => s + (e.points ?? 1), 0);
  await query(
    "UPDATE quiz_sessions SET answers = $1::jsonb, score = $2, total = $3 WHERE id = $4",
    [JSON.stringify(entries), score, total, sessionId]
  );
  revalidatePath(`/quiz/${sessionId}/result`);
  return { ok: true, data: { score, total } };
}

export async function createMock(input: { examId: string; count: number }): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const deadline = actionDeadline();
  const count = Math.min(50, Math.max(5, Math.round(input.count || 20)));
  const exam = isAdmin(user)
    ? await queryOne<{ id: string; title: string }>("SELECT id, title FROM exams WHERE id = $1", [input.examId])
    : await queryOne<{ id: string; title: string }>(
        `SELECT id, title FROM exams WHERE id = $1 AND
           (user_id = $2 OR id IN (SELECT exam_id FROM content_grants WHERE user_id = $2 AND exam_id IS NOT NULL))`,
        [input.examId, user.id]
      );
  if (!exam) return { ok: false, error: "Exam not found" };

  const topics = await query<WeightedTopic>(
    `SELECT id, name, weightage, parent_id AS "parentId" FROM topics WHERE exam_id = $1 ORDER BY sort_order`,
    [input.examId]
  );
  // Parents are containers, so only the leaves are allocated questions — counting
  // a domain and its skills together would ask for far more than `count`.
  const leaves = topics.filter((t) => leafTopicIds(topics).has(t.id));
  const totalWeight = leaves.reduce((s, t) => s + t.weightage, 0);

  const pool = await buildQuestionPool(user, input.examId);
  const selected: QuizQuestion[] = [];
  const used = new Set<string>();

  // Heaviest topic first, so when a topic's bank runs dry the questions it does
  // have go to the share that matters most instead of being spent on a 1% topic.
  const quota = allocateByWeight(
    leaves.map((t) => t.weightage),
    count
  );
  const ordered = leaves
    .map((topic, i) => ({ topic, target: quota[i] ?? 0 }))
    .sort((a, b) => b.target - a.target || a.topic.name.localeCompare(b.topic.name));

  for (const { topic, target } of ordered) {
    if (target <= 0) continue;
    const topicQs = pool.filter((q) => q.topicId === topic.id && !used.has(q.id));
    const take = Math.min(target, topicQs.length);
    topicQs.slice(0, take).forEach((q) => {
      used.add(q.id);
      selected.push(q);
    });
  }

  // Fill anything still missing, weighted toward the highest-weightage topics
  let remaining = count - selected.length;
  const fillPool = pool.filter((q) => !used.has(q.id));
  for (const q of fillPool) {
    if (remaining <= 0) break;
    selected.push(q);
    remaining--;
  }

  // AI top-up if the bank still can't fill the mock
  let aiAdded = 0;
  if (remaining > 0) {
    const topicFor = ordered.find((o) => o.target > 0)?.topic ?? ordered[0]?.topic ?? null;
    const missing = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      topicIds: topicFor ? [topicFor.id] : [],
      type: "mcq",
      count: remaining,
      budgetMs: remainingActionMs(deadline),
    }).catch(() => []);
    aiAdded = missing.length;
    for (let i = 0; i < missing.length; i++) {
      selected.push({
        id: `m${i}-${crypto.randomUUID()}`,
        type: "mcq",
        category: null,
        prompt: missing[i].prompt,
        choices: missing[i].choices as QuizQuestion["choices"],
        answer: missing[i].answer,
        explanation: missing[i].explanation,
        topicId: missing[i].topicId,
        points: 1,
      });
    }
    await persistGeneratedQuestions(user.id, input.examId, missing).catch(() => {});
  }

  const session = await queryOne<{ id: string }>(
    `INSERT INTO quiz_sessions (user_id, exam_id, topic_id, mode, title, num_questions, questions)
     VALUES ($1, $2, NULL, 'mock', $3, $4, $5::jsonb) RETURNING id`,
    [user.id, input.examId, `Mock Exam · ${exam.title}`, selected.length, JSON.stringify(selected)]
  );
  if (!session) return { ok: false, error: "Could not create mock exam" };
  revalidatePath("/mock");
  revalidatePath("/dashboard");
  // A plan whose topics are all 0% silently produces a uniform random paper, so
  // say so rather than letting the result screen claim a per-topic breakdown.
  const warning =
    totalWeight <= 0 && topics.length > 0
      ? "This exam's topics have no weightage, so this mock was drawn evenly at random. Add % weightage to your topics to weight it properly."
      : aiAdded > 0
        ? `${aiAdded} question${aiAdded === 1 ? " was" : "s were"} generated to fill the paper — your bank did not have enough.`
        : undefined;
  return { ok: true, id: session.id, data: { aiAdded }, warning };
}

export async function submitMock(sessionId: string, answers: SubmittedAnswer[]): Promise<ActionResult> {
  const result = await submitQuiz(sessionId, answers);
  if (result.ok) {
    revalidatePath("/mock");
    revalidatePath(`/mock/${sessionId}/result`);
  }
  return result;
}

// ---------------------------------------------------------------- interview

export async function startInterview(input: {
  examId: string | null;
  role: string;
  difficulty: string;
  count: number;
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const count = Math.min(10, Math.max(1, Math.round(input.count || 5)));
  const deadline = actionDeadline();
  if (input.examId && !isAdmin(user)) {
    const owned = await queryOne(
      `SELECT id FROM exams WHERE id = $1 AND
         (user_id = $2 OR id IN (SELECT exam_id FROM content_grants WHERE user_id = $2 AND exam_id IS NOT NULL))`,
      [input.examId, user.id]
    );
    if (!owned) return { ok: false, error: "Exam not found" };
  }
  const available = await isAiAvailable(user.id);
  if (!available) {
    return { ok: false, error: "AI service is not reachable. Start Ollama or configure AI_BASE_URL." };
  }
  try {
    const rows = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      type: "interview",
      count,
      budgetMs: remainingActionMs(deadline),
    });
    if (rows.length === 0) return { ok: false, error: "Could not generate questions" };
    const snapshot: QuizQuestion[] = rows.map((r, i) => ({
      id: `iv-${i}-${crypto.randomUUID()}`,
      type: "interview",
      category: r.category,
      prompt: r.prompt,
      choices: null,
      answer: r.answer,
      explanation: r.explanation,
      topicId: null,
      points: 1,
    }));
    await persistGeneratedQuestions(user.id, input.examId, rows).catch(() => {});
    const session = await queryOne<{ id: string }>(
      `INSERT INTO quiz_sessions (user_id, exam_id, mode, title, num_questions, questions)
       VALUES ($1, $2, 'interview', $3, $4, $5::jsonb) RETURNING id`,
      [user.id, input.examId, `Interview · ${input.role}`, snapshot.length, JSON.stringify(snapshot)]
    );
    if (!session) return { ok: false, error: "Could not start interview" };
    return { ok: true, id: session.id };
  } catch (err) {
    if (err instanceof AIError) return { ok: false, error: err.message };
    return { ok: false, error: err instanceof Error ? err.message : "Interview generation failed" };
  }
}

export async function submitInterview(sessionId: string, answers: SubmittedAnswer[]): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const session = await queryOne<{ id: string; questions: unknown; created_at: Date }>(
    `SELECT id, questions, created_at FROM quiz_sessions WHERE id = $1 AND ${scoped(user, "user_id", 2)} AND mode = 'interview' AND completed_at IS NULL`,
    [sessionId, user.id]
  );
  if (!session) return { ok: false, error: "Interview session not found" };
  const questions = (Array.isArray(session.questions) ? session.questions : JSON.parse(String(session.questions))) as QuizQuestion[];

  const deadline = actionDeadline();
  const entries: AnswerEntry[] = [];
  for (const q of questions) {
    const a = answers.find((x) => x.questionId === q.id);
    const text = a?.text?.trim() || "";
    let feedback: InterviewFeedback | null = null;
    if (text.length > 10) {
      try {
        const { system, user: userPrompt } = interviewFeedbackPrompt({
          role: "the role",
          question: q.prompt,
          modelAnswer: q.answer ?? undefined,
          userAnswer: text.slice(0, 4000),
        });
        feedback = await chatJson<InterviewFeedback>(user.id, system, userPrompt, {
          maxTokens: 1200,
          timeoutMs: remainingActionMs(deadline),
        });
      } catch {
        feedback = null;
      }
    }
    entries.push({
      questionId: q.id,
      topicId: q.topicId ?? null,
      type: q.type,
      text,
      chosen: null,
      correct: false,
      points: q.points,
      got: 0,
      explanation: q.explanation ?? null,
      feedback,
    });
  }

  await query(
    `UPDATE quiz_sessions SET answers = $1::jsonb, completed_at = now(), duration_sec = $2 WHERE id = $3`,
    [
      JSON.stringify(entries),
      Math.max(1, Math.round((Date.now() - new Date(session.created_at).getTime()) / 1000)),
      sessionId,
    ]
  );
  revalidatePath("/interview");
  revalidatePath(`/interview/${sessionId}/result`);
  return { ok: true, id: sessionId };
}

// ---------------------------------------------------------------- study tracking

export async function logStudy(seconds: number): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const sec = Math.min(24 * 3600, Math.max(10, Math.round(seconds || 0)));
  await query(
    "INSERT INTO study_sessions (user_id, seconds, study_date) VALUES ($1, $2, CURRENT_DATE)",
    [user.id, sec]
  );
  revalidatePath("/dashboard");
  return { ok: true };
}

// ---------------------------------------------------------------- misc

export async function aiStatus(): Promise<ActionResult> {
  const boat = await isAiAvailable();
  return boat ? { ok: true, data: { available: true } } : { ok: true, data: { available: false } };
}

// ---------------------------------------------------------------- user roles (admin)

/** Admin-only: promote or demote an account. Protects against self-lockout. */
export async function setUserRole(userId: string, role: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  if (user.id === userId) return { ok: false, error: "You cannot change your own role" };
  if (role !== "admin" && role !== "user") return { ok: false, error: "Invalid role" };

  const target = await queryOne<{ id: string; role: string }>("SELECT id, role FROM users WHERE id = $1", [userId]);
  if (!target) return { ok: false, error: "User not found" };
  if (target.role === role) return { ok: true };

  if (role === "user") {
    const admins = await query<{ id: string }>("SELECT id FROM users WHERE role = 'admin'");
    if (admins.length <= 1) return { ok: false, error: "Cannot demote the last admin account" };
  }

  await query("UPDATE users SET role = $1 WHERE id = $2", [role, userId]);
  revalidatePath("/users");
  revalidatePath("/", "layout");
  return { ok: true };
}

/** Admin-only: approve or revoke a user's access. Admins bypass approval. */
export async function setUserApproval(userId: string, approved: boolean): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  if (user.id === userId) return { ok: true };
  const target = await queryOne<{ role: string }>("SELECT role FROM users WHERE id = $1", [userId]);
  if (!target) return { ok: false, error: "User not found" };
  if (target.role === "admin") return { ok: true };
  await query("UPDATE users SET approved = $1 WHERE id = $2", [approved, userId]);
  revalidatePath("/users");
  revalidatePath("/", "layout");
  return { ok: true };
}

/** Admin-only: grant or revoke a user's access to an exam (or the general bank when examId is null). */
export async function setContentGrant(
  userId: string,
  examId: string | null,
  granted: boolean
): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  if (!isAdmin(user)) return { ok: false, error: "Admin access required for this action" };
  const target = await queryOne<{ id: string }>("SELECT id FROM users WHERE id = $1", [userId]);
  if (!target) return { ok: false, error: "User not found" };
  if (examId) {
    const exam = await queryOne<{ id: string }>("SELECT id FROM exams WHERE id = $1", [examId]);
    if (!exam) return { ok: false, error: "Exam not found" };
  }
  if (granted) {
    await query(
      "INSERT INTO content_grants (user_id, exam_id, granted_by) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
      [userId, examId, user.id]
    );
  } else {
    await query(
      "DELETE FROM content_grants WHERE user_id = $1 AND exam_id IS NOT DISTINCT FROM $2",
      [userId, examId]
    );
  }
  revalidatePath("/users");
  revalidatePath("/", "layout");
  return { ok: true };
}

// ---------------------------------------------------------------- settings

const MAX_FIELD = 500;

function clampField(v: string): string {
  return v.slice(0, MAX_FIELD);
}

/** Saves the user's AI provider config (OpenAI API-key based or local model). */
export async function saveSettings(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const provider: AIProvider = str(formData.get("provider")) === "openai" ? "openai" : "local";
  const baseUrl = clampField(str(formData.get("baseUrl"))) || null;
  let apiKey = clampField(str(formData.get("apiKey"))) || null;
  const model = clampField(str(formData.get("chatModel"))) || null;
  const embeddingModel = clampField(str(formData.get("embeddingModel"))) || null;
  const assistantEnabled = formData.get("assistantEnabled") === "on";

  // Keep the existing key when the field is left blank (masked placeholder).
  if (!apiKey) {
    const existing = await queryOne<{ ai_api_key: string | null }>(
      "SELECT ai_api_key FROM user_settings WHERE user_id = $1",
      [user.id]
    );
    apiKey = existing?.ai_api_key || null;
  }

  await query(
    `INSERT INTO user_settings (user_id, ai_provider, ai_base_url, ai_api_key, ai_model, ai_embedding_model, assistant_enabled)
     VALUES ($1, $2, $3, $4, $5, $6, $7)
     ON CONFLICT (user_id) DO UPDATE SET
       ai_provider = EXCLUDED.ai_provider,
       ai_base_url = EXCLUDED.ai_base_url,
       ai_api_key = EXCLUDED.ai_api_key,
       ai_model = EXCLUDED.ai_model,
       ai_embedding_model = EXCLUDED.ai_embedding_model,
       assistant_enabled = EXCLUDED.assistant_enabled,
       updated_at = now()`,
    [user.id, provider, baseUrl, apiKey, model, embeddingModel, assistantEnabled]
  );
  revalidatePath("/settings");
  revalidatePath("/assistant");
  return { ok: true };
}

/** Tests connectivity using the values typed into the settings form (without saving). */
export async function testAiConnection(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const provider: AIProvider = str(formData.get("provider")) === "openai" ? "openai" : "local";
  const baseUrl = (clampField(str(formData.get("baseUrl"))) || (provider === "openai" ? "https://api.openai.com/v1" : "http://localhost:11434/v1")).replace(/\/+$/, "");
  let apiKey = clampField(str(formData.get("apiKey")));
  if (!apiKey) {
    const existing = await queryOne<{ ai_api_key: string | null }>(
      "SELECT ai_api_key FROM user_settings WHERE user_id = $1",
      [user.id]
    );
    apiKey = existing?.ai_api_key ?? "";
  }
  const cfg: AIConfig = {
    provider,
    baseUrl,
    apiKey: apiKey || "ollama",
    model: clampField(str(formData.get("chatModel"))) || (provider === "openai" ? "gpt-4o-mini" : "llama3.2"),
    embeddingModel: clampField(str(formData.get("embeddingModel"))) || (provider === "openai" ? "text-embedding-3-small" : "nomic-embed-text"),
  };
  const result = await testAiConfig(cfg);
  await recordEvent(
    user.id,
    result.ok ? "info" : "error",
    "ai-config",
    result.ok ? `Connection to ${cfg.model} succeeded` : `Connection to ${cfg.model} failed: ${result.detail}`,
    { provider, baseUrl: cfg.baseUrl, model: cfg.model, embeddingModel: cfg.embeddingModel, detail: result.detail }
  );
  return result.ok
    ? { ok: true, data: { detail: result.detail } }
    : { ok: false, error: result.detail };
}

// ---------------------------------------------------------------- study assistant

/** Sends a message to the study assistant. Uses hybrid RAG (RRF) context + the user's provider config. */
export async function sendChatMessage(prev: unknown, formData: FormData): Promise<ChatActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return { ok: false, error: "Not authenticated" };
  const message = str(formData.get("message"));
  if (!message) return { ok: false, error: "Message is empty" };
  if (message.length > 8000) return { ok: false, error: "Message is too long (max 8000 characters)" };

  const settings = await getUserSettings(user.id);
  if (settings && !settings.assistantEnabled) {
    return { ok: false, error: "The AI assistant is disabled — enable it in Settings → Assistant." };
  }

  try {
    const sessionId = await ensureChatSession(user.id);
    const history = await query<{ role: string; content: string }>(
      `SELECT role, content FROM chat_messages WHERE session_id = $1 ORDER BY created_at ASC LIMIT 40`,
      [sessionId]
    );

    // Hybrid retrieval fused with Reciprocal Rank Fusion
    const retrieved = await ragSearch(user.id, message, { limit: 6 });
    const ctx = retrieved.map((r, i) => ({ index: i + 1, title: r.title, content: r.content }));

    const messages: AIChatMessage[] = [
      { role: "system", content: assistantSystemPrompt(ctx) },
      ...history.map((h) => ({ role: h.role as "user" | "assistant", content: h.content })),
      { role: "user", content: message },
    ];
    const reply = await chatCompletion(user.id, messages, {
      maxTokens: 1500,
      temperature: 0.4,
      timeoutMs: SERVER_ACTION_BUDGET_MS,
    });

    const sources: ChatSource[] = retrieved.map((r) => ({
      title: r.title,
      materialId: r.materialId,
      snippet: r.content.slice(0, 180),
    }));

    await query(
      "INSERT INTO chat_messages (session_id, role, content, sources) VALUES ($1, 'user', $2, '[]'::jsonb)",
      [sessionId, message]
    );
    await query(
      "INSERT INTO chat_messages (session_id, role, content, sources) VALUES ($1, 'assistant', $2, $3::jsonb)",
      [sessionId, reply, JSON.stringify(sources)]
    );
    await query("UPDATE chat_sessions SET updated_at = now() WHERE id = $1", [sessionId]);

    revalidatePath("/assistant");
    return { ok: true, userMessage: message, reply, sources };
  } catch (err) {
    if (err instanceof AIError) return { ok: false, error: err.message };
    return { ok: false, error: err instanceof Error ? err.message : "The assistant could not respond" };
  }
}

/** Deletes the user's whole assistant conversation. */
export async function clearAssistantChat(): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  await query("DELETE FROM chat_sessions WHERE user_id = $1", [user.id]);
  revalidatePath("/assistant");
  return { ok: true };
}
/** Empties the in-app diagnostics log shown under Settings. */
export async function clearDiagnostics(): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const { clearEvents } = await import("@/lib/diagnostics");
  await clearEvents(user.id);
  revalidatePath("/settings");
  return { ok: true, data: { detail: "Diagnostics log cleared." } };
}
