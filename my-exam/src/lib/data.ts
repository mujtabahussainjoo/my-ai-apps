import { query, queryOne } from "@/lib/db";
import { getCurrentUser } from "@/lib/auth";

type ExamRow = {
  id: string;
  title: string;
  description: string | null;
  targetDate: string | Date | null;
  color: string;
  topicCount: string;
  questionCount: string;
  materialCount: string;
  mockCount: string;
  totalWeightage: string;
};

export type Exam = {
  id: string;
  title: string;
  description: string | null;
  targetDate: Date | string | null;
  color: string;
  topicCount: number;
  questionCount: number;
  materialCount: number;
  mockCount: number;
  totalWeightage: number;
};

type TopicRow = {
  id: string;
  examId: string;
  name: string;
  weightage: number;
  description: string | null;
  sortOrder: number;
};

export async function listExams(): Promise<Exam[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const rows = await query<ExamRow>(
    `SELECT e.id, e.title, e.description, e.target_date AS "targetDate", e.color,
            (SELECT count(*)::text FROM topics t WHERE t.exam_id = e.id) AS "topicCount",
            (SELECT count(*)::text FROM questions q WHERE q.exam_id = e.id) AS "questionCount",
            (SELECT count(*)::text FROM materials m WHERE m.exam_id = e.id) AS "materialCount",
            (SELECT count(*)::text FROM quiz_sessions qs WHERE qs.exam_id = e.id AND qs.mode = 'mock') AS "mockCount",
            (SELECT COALESCE(sum(t.weightage), 0)::text FROM topics t WHERE t.exam_id = e.id) AS "totalWeightage"
     FROM exams e
     WHERE e.user_id = $1
     ORDER BY e.created_at DESC`,
    [user.id]
  );
  return rows.map((r) => ({
    id: r.id,
    title: r.title,
    description: r.description,
    targetDate: r.targetDate,
    color: r.color,
    topicCount: Number(r.topicCount),
    questionCount: Number(r.questionCount),
    materialCount: Number(r.materialCount),
    mockCount: Number(r.mockCount),
    totalWeightage: Number(r.totalWeightage),
  }));
}

export async function getExam(id: string): Promise<Exam | null> {
  const user = await getCurrentUser();
  if (!user) return null;
  const rows = await listExams();
  return rows.find((e) => e.id === id) ?? null;
}

export async function listTopics(examId: string): Promise<TopicRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const owns = await query(
    "SELECT id FROM exams WHERE id = $1 AND user_id = $2",
    [examId, user.id]
  );
  if (owns.length === 0) return [];
  return query<TopicRow>(
    `SELECT id, exam_id AS "examId", name, weightage, description, sort_order AS "sortOrder"
     FROM topics WHERE exam_id = $1 ORDER BY sort_order ASC, created_at ASC`,
    [examId]
  );
}

export type MaterialRow = {
  id: string;
  title: string;
  type: string;
  source: string | null;
  status: string;
  chunkCount: string;
  content: string | null;
  createdAt: Date;
};

export async function listMaterials(examId?: string): Promise<MaterialRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const params: unknown[] = [user.id];
  let where = "m.user_id = $1";
  if (examId) {
    params.push(examId);
    where += ` AND m.exam_id = $2`;
  }
  return query<MaterialRow>(
    `SELECT m.id, m.title, m.type, m.source, m.status,
            (SELECT count(*)::text FROM chunks c WHERE c.material_id = m.id) AS "chunkCount",
            (SELECT left(c.content, 1400) FROM chunks c WHERE c.material_id = m.id ORDER BY c.position LIMIT 1) AS content,
            m.created_at AS "createdAt"
     FROM materials m WHERE ${where} ORDER BY m.created_at DESC`,
    params
  );
}

export type QuestionRow = {
  id: string;
  type: string;
  category: string | null;
  prompt: string;
  answer: string | null;
  explanation: string | null;
  source: string;
  examId: string | null;
  examTitle: string | null;
  topicId: string | null;
  topicName: string | null;
  choices: { text: string; correct: boolean }[] | null;
  createdAt: Date;
};

export async function listQuestions(opts: {
  examId?: string;
  topicId?: string;
  type?: string;
  q?: string;
  limit?: number;
}): Promise<QuestionRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const clauses = ["q.user_id = $1"];
  const params: unknown[] = [user.id];
  if (opts.examId) {
    params.push(opts.examId);
    clauses.push(`q.exam_id = $${params.length}`);
  }
  if (opts.topicId) {
    params.push(opts.topicId);
    clauses.push(`q.topic_id = $${params.length}`);
  }
  if (opts.type) {
    params.push(opts.type);
    clauses.push(`q.type = $${params.length}`);
  }
  if (opts.q) {
    params.push(`%${opts.q}%`);
    clauses.push(`(q.prompt ILIKE $${params.length} OR q.answer ILIKE $${params.length})`);
  }
  params.push(opts.limit ?? 500);
  return query<QuestionRow>(
    `SELECT q.id, q.type, q.category, q.prompt, q.answer, q.explanation, q.source,
            q.exam_id AS "examId", e.title AS "examTitle",
            q.topic_id AS "topicId", t.name AS "topicName",
            q.choices, q.created_at AS "createdAt"
     FROM questions q
     LEFT JOIN exams e ON e.id = q.exam_id
     LEFT JOIN topics t ON t.id = q.topic_id
     WHERE ${clauses.join(" AND ")}
     ORDER BY q.created_at DESC
     LIMIT $${params.length}`,
    params
  );
}

export async function countQuestionsForExam(examId: string): Promise<number> {
  const [row] = await query<{ c: string }>(
    "SELECT count(*)::text AS c FROM questions WHERE exam_id = $1",
    [examId]
  );
  return Number(row?.c ?? 0);
}

export type QuizSessionRow = {
  id: string;
  mode: string;
  title: string;
  numQuestions: number;
  score: number;
  total: number;
  questions: unknown[] | string;
  answers: unknown[] | string;
  examId: string | null;
  topicId: string | null;
  startedAt: Date;
  completedAt: Date | null;
  durationSec: number | null;
};

export async function getQuizSession(id: string): Promise<QuizSessionRow | null> {
  const user = await getCurrentUser();
  if (!user) return null;
  return queryOne<QuizSessionRow>(
    `SELECT id, mode, title, num_questions AS "numQuestions", score, total,
            questions, answers, exam_id AS "examId", topic_id AS "topicId",
            started_at AS "startedAt", completed_at AS "completedAt", duration_sec AS "durationSec"
     FROM quiz_sessions WHERE id = $1 AND user_id = $2`,
    [id, user.id]
  );
}

export async function getInterviewSession(id: string): Promise<QuizSessionRow | null> {
  const user = await getCurrentUser();
  if (!user) return null;
  return queryOne<QuizSessionRow>(
    `SELECT id, mode, title, num_questions AS "numQuestions", score, total,
            questions, answers, exam_id AS "examId", topic_id AS "topicId",
            started_at AS "startedAt", completed_at AS "completedAt", duration_sec AS "durationSec"
     FROM quiz_sessions WHERE id = $1 AND user_id = $2 AND mode = 'interview'`,
    [id, user.id]
  );
}

export async function listSessions(mode?: string, limit = 20): Promise<QuizSessionRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const params: unknown[] = [user.id, limit];
  let where = "qs.user_id = $1";
  if (mode) {
    params.push(mode);
    where += " AND qs.mode = $3";
  }
  return query<QuizSessionRow>(
    `SELECT id, mode, title, num_questions AS "numQuestions", score, total,
            questions, answers, exam_id AS "examId", topic_id AS "topicId",
            started_at AS "startedAt", completed_at AS "completedAt", duration_sec AS "durationSec"
     FROM quiz_sessions qs WHERE ${where}
     ORDER BY qs.created_at DESC LIMIT $2`,
    params
  );
}

export type FlashcardRow = {
  id: string;
  examId: string | null;
  examTitle: string | null;
  topicId: string | null;
  topicName: string | null;
  front: string;
  back: string;
  box: number;
  reps: number;
  lapses: number;
  dueAt: Date;
};

export async function listFlashcards(opts: {
  examId?: string;
  dueOnly?: boolean;
  limit?: number;
}): Promise<FlashcardRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const clauses = ["f.user_id = $1"];
  const params: unknown[] = [user.id];
  if (opts.examId) {
    params.push(opts.examId);
    clauses.push(`f.exam_id = $${params.length}`);
  }
  if (opts.dueOnly) {
    clauses.push("f.due_at <= now()");
  }
  params.push(opts.limit ?? 1000);
  return query<FlashcardRow>(
    `SELECT f.id, f.exam_id AS "examId", e.title AS "examTitle",
            f.topic_id AS "topicId", t.name AS "topicName",
            f.front, f.back, f.box, f.reps, f.lapses, f.due_at AS "dueAt"
     FROM flashcards f
     LEFT JOIN exams e ON e.id = f.exam_id
     LEFT JOIN topics t ON t.id = f.topic_id
     WHERE ${clauses.join(" AND ")}
     ORDER BY f.due_at ASC
     LIMIT $${params.length}`,
    params
  );
}

export type InterviewFeedback = {
  grade: string;
  score: number;
  strengths: string[];
  weaknesses: string[];
  verdict: string;
  starScore: { situation: number; task: number; action: number; result: number };
};

export async function getInterviewHistory(userId: string, limit = 20) {
  return query<{
    id: string;
    title: string;
    createdAt: Date;
    answers: unknown[] | string;
    numQuestions: number;
  }>(
    `SELECT id, title, created_at AS "createdAt", answers, num_questions AS "numQuestions"
     FROM quiz_sessions
     WHERE user_id = $1 AND mode = 'interview'
     ORDER BY created_at DESC LIMIT $2`,
    [userId, limit]
  );
}

function parseJsonField<T>(value: unknown): T {
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as T;
    } catch {
      return [] as unknown as T;
    }
  }
  return value as T;
}

export function parseQuestions(value: unknown): QuizQuestion[] {
  return parseJsonField<QuizQuestion[]>(value);
}

export function parseAnswers(value: unknown): AnswerEntry[] {
  return parseJsonField<AnswerEntry[]>(value);
}

export type QuizQuestion = {
  id: string;
  type: string;
  category?: string | null;
  prompt: string;
  choices: { text: string; correct: boolean }[] | null;
  answer?: string | null;
  explanation?: string | null;
  topicId?: string | null;
  points: number;
};

export type AnswerEntry = {
  questionId: string;
  topicId?: string | null;
  type?: string;
  chosen?: string | number | null;
  text?: string;
  correct?: boolean;
  points?: number;
  got?: number;
  explanation?: string | null;
  feedback?: InterviewFeedback | null;
};

/** Strips correct answers/model answers so questions are safe to render client-side. */
export function sanitizeQuestions(qs: QuizQuestion[]): QuizQuestion[] {
  return qs.map((q) => ({
    id: q.id,
    type: q.type,
    category: q.category ?? null,
    prompt: q.prompt,
    choices: q.choices?.map((c) => ({ text: c.text, correct: false })) ?? null,
    answer: null,
    explanation: null,
    topicId: q.topicId ?? null,
    points: q.points,
  }));
}