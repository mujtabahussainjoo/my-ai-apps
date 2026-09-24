"use server";

import bcrypt from "bcryptjs";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { query, queryOne } from "@/lib/db";
import {
  createSession,
  deleteSessionCookie,
  requireUser,
  setSessionCookie,
} from "@/lib/auth";
import {
  MAX_FILE_BYTES,
  embedAndStoreChunks,
  extractTextFromFile,
  extractTextFromUrl,
} from "@/lib/ingest";
import { AIError, isAiAvailable } from "@/lib/ai";
import { generateFromAI, persistGeneratedQuestions } from "@/lib/generate";
import { interviewFeedbackPrompt } from "@/lib/prompts";
import { chatJson } from "@/lib/ai";
import type { QuizQuestion, AnswerEntry, InterviewFeedback } from "@/lib/data";

export type ActionResult = { ok: true; id?: string; redirect?: string; data?: unknown } | { ok: false; error: string };

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
  const id = str(formData.get("id"));
  const title = str(formData.get("title"));
  if (!id || !title) return { ok: false, error: "Exam id and title are required" };
  const owned = await queryOne("SELECT id FROM exams WHERE id = $1 AND user_id = $2", [id, user.id]);
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
  const owned = await queryOne("SELECT id FROM exams WHERE id = $1 AND user_id = $2", [id, user.id]);
  if (!owned) return { ok: false, error: "Exam not found" };
  await query("DELETE FROM exams WHERE id = $1", [id]);
  revalidatePath("/exams");
  revalidatePath("/dashboard");
  return { ok: true };
}

export async function createTopic(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const examId = str(formData.get("examId"));
  const name = str(formData.get("name"));
  if (!examId || !name) return { ok: false, error: "Topic name is required" };
  const owned = await queryOne("SELECT id FROM exams WHERE id = $1 AND user_id = $2", [examId, user.id]);
  if (!owned) return { ok: false, error: "Exam not found" };
  const weightage = Math.min(100, Math.max(0, Math.round(toInt(formData.get("weightage")))));
  const description = str(formData.get("description"));
  const [r] = await query<{ m: string }>("SELECT COALESCE(max(sort_order), -1)::text AS m FROM topics WHERE exam_id = $1", [examId]);
  const nextOrder = Number(r?.m ?? -1) + 1;
  await query(
    `INSERT INTO topics (exam_id, name, weightage, description, sort_order) VALUES ($1, $2, $3, $4, $5)`,
    [examId, name, weightage, description || null, nextOrder]
  );
  revalidatePath(`/exams/${examId}`);
  revalidatePath("/exams");
  return { ok: true };
}

export async function updateTopic(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const id = str(formData.get("id"));
  const name = str(formData.get("name"));
  const weightage = Math.min(100, Math.max(0, Math.round(toInt(formData.get("weightage")))));
  const description = str(formData.get("description"));
  if (!id || !name) return { ok: false, error: "Missing fields" };
  const t = await queryOne<{ exam_id: string }>(
    `UPDATE topics SET name = $1, weightage = $2, description = $3
     WHERE id = $4 AND exam_id IN (SELECT id FROM exams WHERE user_id = $5)
     RETURNING exam_id`,
    [name, weightage, description || null, id, user.id]
  );
  if (!t) return { ok: false, error: "Topic not found" };
  revalidatePath(`/exams/${t.exam_id}`);
  return { ok: true };
}

export async function deleteTopic(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const t = await queryOne<{ exam_id: string }>(
    `DELETE FROM topics WHERE id = $1 AND exam_id IN (SELECT id FROM exams WHERE user_id = $2) RETURNING exam_id`,
    [id, user.id]
  );
  if (!t) return { ok: false, error: "Topic not found" };
  revalidatePath(`/exams/${t.exam_id}`);
  return { ok: true };
}

// ---------------------------------------------------------------- materials

export async function addMaterial(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const examId = str(formData.get("examId")) || null;
  const kind = str(formData.get("kind")); // text | url | file
  const title = str(formData.get("title"));
  const url = str(formData.get("url"));
  const text = str(formData.get("text"));
  const file = formData.get("file");

  let content = "";
  let source: string | null = null;
  let type = "TEXT";
  let autoTitle = title;

  try {
    if (kind === "url" && url) {
      type = "URL";
      source = url;
      const r = await extractTextFromUrl(url);
      content = r.text;
      autoTitle = title || r.title;
    } else if (kind === "file" && file instanceof File) {
      if (file.size > MAX_FILE_BYTES) {
        return { ok: false, error: "File is too large (max 15MB)" };
      }
      type = "FILE";
      source = file.name;
      const buf = Buffer.from(await file.arrayBuffer());
      content = await extractTextFromFile(buf, file.name);
      autoTitle = title || file.name.replace(/\.[^.]+$/, "");
    } else {
      content = text;
      autoTitle = title || "Pasted notes";
    }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }

  if (content.trim().length < 30) {
    return { ok: false, error: "Not enough content extracted — add more text or a different file/URL" };
  }

  let examIdFinal: string | null = examId;
  if (examId) {
    const owned = await queryOne("SELECT id FROM exams WHERE id = $1 AND user_id = $2", [examId, user.id]);
    if (!owned) examIdFinal = null;
  }

  const material = await queryOne<{ id: string }>(
    `INSERT INTO materials (user_id, exam_id, title, type, source, content)
     VALUES ($1, $2, $3, $4, $5, $6) RETURNING id`,
    [user.id, examIdFinal, autoTitle, type, source, content]
  );
  if (!material) return { ok: false, error: "Could not store material" };

  try {
    await embedAndStoreChunks(material.id, content);
  } catch {
    // embeddings are optional; RAG will just be less effective
  }

  revalidatePath("/materials");
  revalidatePath("/dashboard");
  return { ok: true, id: material.id };
}

export async function deleteMaterial(id: string): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const owned = await queryOne("SELECT id FROM materials WHERE id = $1 AND user_id = $2", [id, user.id]);
  if (!owned) return { ok: false, error: "Material not found" };
  await query("DELETE FROM materials WHERE id = $1", [id]);
  revalidatePath("/materials");
  return { ok: true };
}

// ---------------------------------------------------------------- questions (manual)

export async function addQuestion(prev: unknown, formData: FormData): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
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
    const options = [1, 2, 3, 4].map((i) => str(formData.get(`option${i}`)));
    if (options.some((o) => !o)) return { ok: false, error: "All 4 options are required" };
    const correctIdx = toInt(formData.get("correctIndex"));
    if (correctIdx < 0 || correctIdx > 3) return { ok: false, error: "Pick the correct option" };
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
  const owned = await queryOne("SELECT id FROM questions WHERE id = $1 AND user_id = $2", [id, user.id]);
  if (!owned) return { ok: false, error: "Question not found" };
  await query("DELETE FROM questions WHERE id = $1", [id]);
  revalidatePath("/question-bank");
  return { ok: true };
}

// ---------------------------------------------------------------- AI generation

export async function generateQuestions(input: {
  examId: string | null;
  topicIds: string[];
  type: string;
  count: number;
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const count = Math.min(20, Math.max(1, Math.round(input.count || 5)));
  if (!["mcq", "true_false", "short"].includes(input.type)) {
    return { ok: false, error: "Pick mcq, true/false or short answer" };
  }
  try {
    const rows = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      topicIds: input.topicIds,
      type: input.type as "mcq" | "true_false" | "short",
      count,
    });
    if (rows.length === 0) return { ok: false, error: "AI generated no questions — try again" };
    const created = await persistGeneratedQuestions(user.id, input.examId, rows);
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
  topicIds: string[];
  count: number;
}): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const count = Math.min(30, Math.max(1, Math.round(input.count || 10)));
  try {
    const rows = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      topicIds: input.topicIds,
      type: "flashcard",
      count,
    });
    if (rows.length === 0) return { ok: false, error: "AI generated no flashcards — try again" };
    for (const r of rows) {
      await query(
        `INSERT INTO flashcards (user_id, exam_id, topic_id, front, back, source)
         VALUES ($1, $2, $3, $4, $5, 'ai')`,
        [user.id, input.examId, r.topicId, r.prompt, r.answer]
      );
    }
    revalidatePath("/flashcards");
    return { ok: true, data: { created: rows.length } };
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
  const owned = await queryOne("SELECT id FROM flashcards WHERE id = $1 AND user_id = $2", [id, user.id]);
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
    "SELECT id, box, reps, lapses FROM flashcards WHERE id = $1 AND user_id = $2",
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

function gradeAnswer(question: QuizQuestion, a: SubmittedAnswer): { correct: boolean; got: number } {
  if (question.type === "short") {
    return { correct: a.selfCorrect ?? false, got: a.selfCorrect ? question.points : 0 };
  }
  const correct = question.choices?.find((c) => c.correct) ?? null;
  if (!correct) return { correct: false, got: 0 };
  if (question.type === "mcq") {
    const chosenIdx = typeof a.chosen === "number" ? a.chosen : Number(a.chosen);
    const chosen = question.choices?.[chosenIdx];
    return { correct: chosen?.text === correct.text, got: chosen?.text === correct.text ? question.points : 0 };
  }
  if (question.type === "true_false") {
    const chosenBool = a.chosen === true || a.chosen === "true";
    const correctBool = correct.text.toLowerCase() === "true";
    return { correct: chosenBool === correctBool, got: chosenBool === correctBool ? question.points : 0 };
  }
  return { correct: false, got: 0 };
}

async function buildQuestionPool(
  userId: string,
  examId: string | null
): Promise<QuizQuestion[]> {
  const rows = await query<QuizQuestion & { choices: QuizQuestion["choices"] }>(
    `SELECT id, type, category, prompt, choices, answer, explanation, topic_id AS "topicId", points
     FROM questions
     WHERE user_id = $1 AND ($2::uuid IS NULL OR exam_id = $2) AND type IN ('mcq','true_false','short')
     ORDER BY random()`,
    [userId, examId]
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
  if (input.examId) {
    const owned = await queryOne("SELECT id FROM exams WHERE id = $1 AND user_id = $2", [input.examId, user.id]);
    if (!owned) return { ok: false, error: "Exam not found" };
  }
  const mode = input.mode ?? "quiz";
  const count = Math.min(60, Math.max(1, Math.round(input.count || 10)));

  const pool = await buildQuestionPool(user.id, input.examId);
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
    "SELECT id, questions, started_at FROM quiz_sessions WHERE id = $1 AND user_id = $2 AND completed_at IS NULL",
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

export async function selfGradeAnswer(sessionId: string, questionId: string, correctValue: boolean): Promise<ActionResult> {
  const user = await requireUser().catch(() => null);
  if (!user) return guard();
  const session = await queryOne<{ id: string; answers: unknown }>(
    "SELECT id, answers FROM quiz_sessions WHERE id = $1 AND user_id = $2",
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
  const count = Math.min(50, Math.max(5, Math.round(input.count || 20)));
  const exam = await queryOne<{ id: string; title: string }>(
    "SELECT id, title FROM exams WHERE id = $1 AND user_id = $2",
    [input.examId, user.id]
  );
  if (!exam) return { ok: false, error: "Exam not found" };

  const topics = await query<{ id: string; name: string; weightage: number }>(
    "SELECT id, name, weightage FROM topics WHERE exam_id = $1 ORDER BY sort_order",
    [input.examId]
  );
  const totalWeight = topics.reduce((s, t) => s + t.weightage, 0) || 1;

  const pool = await buildQuestionPool(user.id, input.examId);
  const selected: QuizQuestion[] = [];
  const used = new Set<string>();

  for (const topic of topics) {
    const target = Math.round((count * topic.weightage) / totalWeight);
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
  const orderedByWeight = [...topics].sort((a, b) => b.weightage - a.weightage);
  for (const q of fillPool) {
    if (remaining <= 0) break;
    selected.push(q);
    remaining--;
  }

  // AI top-up if the bank still can't fill the mock
  let aiAdded = 0;
  if (remaining > 0) {
    const topicFor = orderedByWeight.length > 0 ? orderedByWeight[0] : null;
    const missing = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      topicIds: topicFor ? [topicFor.id] : [],
      type: "mcq",
      count: remaining,
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
  return { ok: true, id: session.id, data: { aiAdded } };
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
  const available = await isAiAvailable();
  if (!available) {
    return { ok: false, error: "AI service is not reachable. Start Ollama or configure AI_BASE_URL." };
  }
  try {
    const rows = await generateFromAI({
      userId: user.id,
      examId: input.examId,
      type: "interview",
      count,
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
    "SELECT id, questions, created_at FROM quiz_sessions WHERE id = $1 AND user_id = $2 AND mode = 'interview' AND completed_at IS NULL",
    [sessionId, user.id]
  );
  if (!session) return { ok: false, error: "Interview session not found" };
  const questions = (Array.isArray(session.questions) ? session.questions : JSON.parse(String(session.questions))) as QuizQuestion[];

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
        feedback = await chatJson<InterviewFeedback>(system, userPrompt, { maxTokens: 1200 });
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