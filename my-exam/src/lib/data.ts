import { query, queryOne } from "@/lib/db";
import { getCurrentUser, scoped, isAdmin, requireAdmin } from "@/lib/auth";

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
  ownerEmail?: string | null;
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
  ownerEmail?: string | null;
};

type TopicRow = {
  id: string;
  examId: string;
  name: string;
  weightage: number;
  description: string | null;
  sortOrder: number;
  parentId: string | null;
};

export type TopicNode = TopicRow & { children: TopicNode[] };

export async function listExams(): Promise<Exam[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const admin = isAdmin(user);
  const where = admin
    ? "TRUE"
    : `(e.user_id = $1 OR e.id IN (SELECT exam_id FROM content_grants WHERE user_id = $1 AND exam_id IS NOT NULL))`;
  const params = admin ? [] : [user.id];
  const rows = await query<ExamRow>(
    `SELECT e.id, e.title, e.description, e.target_date AS "targetDate", e.color,
            u.email AS "ownerEmail",
            (SELECT count(*)::text FROM topics t WHERE t.exam_id = e.id) AS "topicCount",
            (SELECT count(*)::text FROM questions q WHERE q.exam_id = e.id) AS "questionCount",
            (SELECT count(*)::text FROM materials m
              WHERE m.exam_id = e.id
                 OR m.knowledge_base_id IN (SELECT knowledge_base_id FROM exam_knowledge_bases WHERE exam_id = e.id)
            ) AS "materialCount",
            (SELECT count(*)::text FROM quiz_sessions qs WHERE qs.exam_id = e.id AND qs.mode = 'mock') AS "mockCount",
            -- Only leaf topics hold weight, so a domain and its skills are not
            -- counted twice against the 100%.
            (SELECT COALESCE(sum(t.weightage), 0)::text
               FROM topics t
              WHERE t.exam_id = e.id
                AND NOT EXISTS (SELECT 1 FROM topics c WHERE c.parent_id = t.id)
            ) AS "totalWeightage"
     FROM exams e
     LEFT JOIN users u ON u.id = e.user_id
     WHERE ${where}
     ORDER BY e.created_at DESC`,
    params
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
    ownerEmail: r.ownerEmail ?? null,
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
  if (!isAdmin(user)) {
    const owns = await query(
      `SELECT id FROM exams WHERE id = $1 AND
         (user_id = $2 OR id IN (SELECT exam_id FROM content_grants WHERE user_id = $2 AND exam_id IS NOT NULL))`,
      [examId, user.id]
    );
    if (owns.length === 0) return [];
  }
  return query<TopicRow>(
    `SELECT id, exam_id AS "examId", name, weightage, description, sort_order AS "sortOrder", parent_id AS "parentId"
     FROM topics WHERE exam_id = $1 ORDER BY sort_order ASC, created_at ASC`,
    [examId]
  );
}

/** Flat topic plus its full list of descendant (subtopic) ids. */
async function topicWithDescendants(topicId: string): Promise<string[]> {
  const rows = await query<{ id: string }>(
    `WITH RECURSIVE tsel AS (
       SELECT id FROM topics WHERE id = $1
       UNION ALL
       SELECT t.id FROM topics t JOIN tsel ON t.parent_id = tsel.id
     )
     SELECT id FROM tsel`,
    [topicId]
  );
  return rows.map((r) => r.id);
}

/** Topics of an exam as a nested tree (top-level topics with subtopics). */
export async function listTopicTree(examId: string): Promise<TopicNode[]> {
  const flat = await listTopics(examId);
  const byId = new Map<string, TopicNode>();
  for (const t of flat) byId.set(t.id, { ...t, children: [] });
  const roots: TopicNode[] = [];
  for (const t of flat) {
    const node = byId.get(t.id)!;
    if (t.parentId && byId.has(t.parentId)) byId.get(t.parentId)!.children.push(node);
    else roots.push(node);
  }
  return roots;
}

export type MaterialRow = {
  id: string;
  title: string;
  type: string;
  source: string | null;
  status: string;
  knowledgeBaseId: string | null;
  knowledgeBaseName: string | null;
  chunkCount: string;
  content: string | null;
  createdAt: Date;
  ownerEmail?: string | null;
};

export type KnowledgeBaseRow = {
  id: string;
  name: string;
  description: string | null;
  docCount: number;
  chunkCount: number;
  createdAt: Date;
  ownerEmail?: string | null;
};

/** Lists the user's named knowledge bases (libraries) with doc/chunk counts. */
export async function listKnowledgeBases(): Promise<KnowledgeBaseRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const rows = await query<{
    id: string;
    name: string;
    description: string | null;
    docCount: string;
    chunkCount: string;
    createdAt: Date;
    ownerEmail?: string | null;
  }>(
    `SELECT kb.id, kb.name, kb.description,
            u.email AS "ownerEmail",
            (SELECT count(*)::text FROM materials m WHERE m.knowledge_base_id = kb.id) AS "docCount",
            (SELECT count(*)::text FROM chunks c
               JOIN materials m ON m.id = c.material_id
              WHERE m.knowledge_base_id = kb.id) AS "chunkCount",
            kb.created_at AS "createdAt"
     FROM knowledge_bases kb
     LEFT JOIN users u ON u.id = kb.user_id
     WHERE ${scoped(user, "kb.user_id")}
     ORDER BY kb.created_at DESC`,
    [user.id]
  );
  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    description: r.description,
    docCount: Number(r.docCount),
    chunkCount: Number(r.chunkCount),
    createdAt: r.createdAt,
    ownerEmail: r.ownerEmail ?? null,
  }));
}

export async function listMaterials(opts: {
  examId?: string;
  knowledgeBaseId?: string;
} = {}): Promise<MaterialRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const adminUser = isAdmin(user);
  const params: unknown[] = [];
  const clauses: string[] = [];
  if (!adminUser) {
    params.push(user.id);
    clauses.push(
      `(m.user_id = $${params.length} OR m.exam_id IN (SELECT exam_id FROM content_grants WHERE user_id = $${params.length} AND exam_id IS NOT NULL))`
    );
  }
  if (opts.examId) {
    params.push(opts.examId);
    // An exam's study material is everything filed directly against it plus
    // everything in the knowledge bases linked to it. Without the second half a
    // course shared between two exams would have to be duplicated per exam.
    clauses.push(
      `(m.exam_id = $${params.length} OR m.knowledge_base_id IN (
          SELECT knowledge_base_id FROM exam_knowledge_bases WHERE exam_id = $${params.length}))`
    );
  }
  if (opts.knowledgeBaseId) {
    params.push(opts.knowledgeBaseId);
    clauses.push(`m.knowledge_base_id = $${params.length}`);
  }

  return query<MaterialRow>(
    `SELECT m.id, m.title, m.type, m.source, m.status,
            m.knowledge_base_id AS "knowledgeBaseId", kb.name AS "knowledgeBaseName",
            u.email AS "ownerEmail",
(SELECT count(*)::text FROM chunks c WHERE c.material_id = m.id) AS "chunkCount",
             (SELECT left(string_agg(c.content, E'\n\n' ORDER BY c.position), 12000)
                FROM chunks c WHERE c.material_id = m.id AND c.content <> '') AS content,
            m.created_at AS "createdAt"
     FROM materials m
     LEFT JOIN knowledge_bases kb ON kb.id = m.knowledge_base_id
     LEFT JOIN users u ON u.id = m.user_id
     WHERE ${clauses.join(" AND ") || "TRUE"} ORDER BY m.created_at DESC`,
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
  topicParentName?: string | null;
  choices: { text: string; correct: boolean }[] | null;
  createdAt: Date;
  ownerEmail?: string | null;
};

/** Sentinel "exam id" meaning questions with no exam assigned (general knowledge). */
export const GENERAL_EXAM = "general";

export type QuestionFilter = {
  examId?: string;
  topicId?: string;
  type?: string;
  q?: string;
};

/**
 * Shared WHERE-clause builder for the question bank. Returns null when the user
 * is unauthenticated, or marks `empty` when a topic filter has no descendants
 * (nothing can match, so callers can skip the query).
 */
async function buildQuestionWhere(
  opts: QuestionFilter
): Promise<{ clauses: string[]; params: unknown[]; empty?: boolean } | null> {
  const user = await getCurrentUser();
  if (!user) return null;
  const clauses: string[] = [];
  const params: unknown[] = [];
  if (!isAdmin(user)) {
    params.push(user.id);
    clauses.push(
      `(q.user_id = $${params.length} OR q.exam_id IN (SELECT exam_id FROM content_grants WHERE user_id = $${params.length} AND exam_id IS NOT NULL) OR (q.exam_id IS NULL AND EXISTS (SELECT 1 FROM content_grants WHERE user_id = $${params.length} AND exam_id IS NULL)))`
    );
  }
  if (opts.examId) {
    if (opts.examId === GENERAL_EXAM) {
      clauses.push("q.exam_id IS NULL");
    } else {
      params.push(opts.examId);
      clauses.push(`q.exam_id = $${params.length}`);
    }
  }
  if (opts.topicId) {
    const ids = await topicWithDescendants(opts.topicId);
    if (ids.length === 0) return { clauses, params, empty: true };
    params.push(ids);
    clauses.push(`q.topic_id = ANY($${params.length}::uuid[])`);
  }
  if (opts.type) {
    params.push(opts.type);
    clauses.push(`q.type = $${params.length}`);
  }
  if (opts.q) {
    params.push(`%${opts.q}%`);
    clauses.push(`(q.prompt ILIKE $${params.length} OR q.answer ILIKE $${params.length})`);
  }
  return { clauses, params };
}

const QUESTION_COLUMNS = `q.id, q.type, q.category, q.prompt, q.answer, q.explanation, q.source,
      q.exam_id AS "examId", e.title AS "examTitle",
      q.topic_id AS "topicId", t.name AS "topicName", pt.name AS "topicParentName",
      u.email AS "ownerEmail",
      q.choices, q.created_at AS "createdAt"`;
const QUESTION_JOINS = `LEFT JOIN exams e ON e.id = q.exam_id
     LEFT JOIN topics t ON t.id = q.topic_id
     LEFT JOIN topics pt ON pt.id = t.parent_id
     LEFT JOIN users u ON u.id = q.user_id`;

/** Total number of questions matching the filters (used for pagination). */
export async function countQuestions(opts: QuestionFilter): Promise<number> {
  const where = await buildQuestionWhere(opts);
  if (!where || where.empty) return 0;
  const [row] = await query<{ c: string }>(
    `SELECT count(*)::text AS c FROM questions q WHERE ${where.clauses.join(" AND ") || "TRUE"}`,
    where.params
  );
  return Number(row?.c ?? 0);
}

export async function listQuestions(opts: QuestionFilter & {
  limit?: number;
  offset?: number;
}): Promise<QuestionRow[]> {
  const where = await buildQuestionWhere(opts);
  if (!where || where.empty) return [];
  const { clauses, params } = where;
  const limit = opts.limit ?? 500;
  params.push(limit);
  let sql = `SELECT ${QUESTION_COLUMNS}
     FROM questions q
     ${QUESTION_JOINS}
     WHERE ${clauses.join(" AND ") || "TRUE"}
     ORDER BY q.created_at DESC
     LIMIT $${params.length}`;
  if (opts.offset) {
    params.push(opts.offset);
    sql += ` OFFSET $${params.length}`;
  }
  return query<QuestionRow>(sql, params);
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
  ownerEmail?: string | null;
};

export async function getQuizSession(id: string): Promise<QuizSessionRow | null> {
  const user = await getCurrentUser();
  if (!user) return null;
  return queryOne<QuizSessionRow>(
    `SELECT qs.id, qs.mode, qs.title, qs.num_questions AS "numQuestions", qs.score, qs.total,
            qs.questions, qs.answers, qs.exam_id AS "examId", qs.topic_id AS "topicId",
            qs.started_at AS "startedAt", qs.completed_at AS "completedAt", qs.duration_sec AS "durationSec",
            u.email AS "ownerEmail"
     FROM quiz_sessions qs
     LEFT JOIN users u ON u.id = qs.user_id
     WHERE qs.id = $1 AND ${scoped(user, "qs.user_id", 2)}
     LIMIT 1`,
    [id, user.id]
  );
}

export async function getInterviewSession(id: string): Promise<QuizSessionRow | null> {
  const user = await getCurrentUser();
  if (!user) return null;
  return queryOne<QuizSessionRow>(
    `SELECT qs.id, qs.mode, qs.title, qs.num_questions AS "numQuestions", qs.score, qs.total,
            qs.questions, qs.answers, qs.exam_id AS "examId", qs.topic_id AS "topicId",
            qs.started_at AS "startedAt", qs.completed_at AS "completedAt", qs.duration_sec AS "durationSec",
            u.email AS "ownerEmail"
     FROM quiz_sessions qs
     LEFT JOIN users u ON u.id = qs.user_id
     WHERE qs.id = $1 AND ${scoped(user, "qs.user_id", 2)} AND qs.mode = 'interview'
     LIMIT 1`,
    [id, user.id]
  );
}

export async function listSessions(mode?: string, limit = 20): Promise<QuizSessionRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const params: unknown[] = [user.id, limit];
  let where = scoped(user, "qs.user_id");
  if (mode) {
    params.push(mode);
    where += ` AND qs.mode = $${params.length}`;
  }
  return query<QuizSessionRow>(
    `SELECT qs.id, qs.mode, qs.title, qs.num_questions AS "numQuestions", qs.score, qs.total,
            qs.questions, qs.answers, qs.exam_id AS "examId", qs.topic_id AS "topicId",
            qs.started_at AS "startedAt", qs.completed_at AS "completedAt", qs.duration_sec AS "durationSec",
            u.email AS "ownerEmail"
     FROM quiz_sessions qs
     LEFT JOIN users u ON u.id = qs.user_id
     WHERE ${where}
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
  ownerEmail?: string | null;
};

export async function listFlashcards(opts: {
  examId?: string;
  dueOnly?: boolean;
  limit?: number;
}): Promise<FlashcardRow[]> {
  const user = await getCurrentUser();
  if (!user) return [];
  const clauses = [scoped(user, "f.user_id")];
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
            u.email AS "ownerEmail",
            f.front, f.back, f.box, f.reps, f.lapses, f.due_at AS "dueAt"
     FROM flashcards f
     LEFT JOIN exams e ON e.id = f.exam_id
     LEFT JOIN topics t ON t.id = f.topic_id
     LEFT JOIN users u ON u.id = f.user_id
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
  const user = await getCurrentUser();
  const where = isAdmin(user) ? "TRUE" : "user_id = $1";
  const params: unknown[] = isAdmin(user) ? [limit] : [userId, limit];
  return query<{
    id: string;
    title: string;
    createdAt: Date;
    answers: unknown[] | string;
    numQuestions: number;
    ownerEmail?: string | null;
  }>(
    `SELECT qs.id, qs.title, qs.created_at AS "createdAt", qs.answers, qs.num_questions AS "numQuestions",
            u.email AS "ownerEmail"
     FROM quiz_sessions qs
     LEFT JOIN users u ON u.id = qs.user_id
     WHERE ${where} AND qs.mode = 'interview'
     ORDER BY qs.created_at DESC LIMIT $${isAdmin(user) ? 1 : 2}`,
    params
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

// ---------------------------------------------------------------- settings

export type UserSettingsRow = {
  aiProvider: "local" | "openai";
  aiBaseUrl: string | null;
  aiModel: string | null;
  aiEmbeddingModel: string | null;
  hasApiKey: boolean;
  assistantEnabled: boolean;
};

/** Returns the user's saved AI settings, or null when none are saved yet. */
export async function getUserSettings(userId: string): Promise<UserSettingsRow | null> {
  return queryOne<UserSettingsRow>(
    `SELECT ai_provider AS "aiProvider", ai_base_url AS "aiBaseUrl", ai_model AS "aiModel",
            ai_embedding_model AS "aiEmbeddingModel",
            (ai_api_key IS NOT NULL AND ai_api_key <> '') AS "hasApiKey",
            assistant_enabled AS "assistantEnabled"
     FROM user_settings WHERE user_id = $1`,
    [userId]
  );
}

// ---------------------------------------------------------------- assistant chat

export type ChatSource = { title: string; materialId: string; snippet?: string };

export type ChatMessageRow = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: ChatSource[];
  createdAt: Date;
};

/** Reuses the user's latest chat session, creating one if needed. */
export async function ensureChatSession(userId: string): Promise<string> {
  const session = await queryOne<{ id: string }>(
    "SELECT id FROM chat_sessions WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 1",
    [userId]
  );
  if (session) return session.id;
  const created = await queryOne<{ id: string }>(
    "INSERT INTO chat_sessions (user_id) VALUES ($1) RETURNING id",
    [userId]
  );
  if (!created) throw new Error("Could not create chat session");
  return created.id;
}

/** Loads the user's assistant conversation (creating a session on first visit). */
export async function getChatMessages(
  userId: string
): Promise<{ sessionId: string; messages: ChatMessageRow[] }> {
  const sessionId = await ensureChatSession(userId);
  const rows = await query<
    { id: string; role: string; content: string; sources: unknown; created_at: Date }
  >(
    `SELECT id, role, content, sources, created_at FROM chat_messages
     WHERE session_id = $1 ORDER BY created_at ASC`,
    [sessionId]
  );
  return {
    sessionId,
    messages: rows.map((r) => ({
      id: r.id,
      role: r.role === "assistant" ? "assistant" : "user",
      content: r.content,
      sources: Array.isArray(r.sources)
        ? (r.sources as ChatSource[])
        : (() => {
            try {
              const parsed = typeof r.sources === "string" ? JSON.parse(r.sources) : r.sources;
              return Array.isArray(parsed) ? (parsed as ChatSource[]) : [];
            } catch {
              return [];
            }
          })(),
      createdAt: r.created_at,
    })),
  };
}

// ---------------------------------------------------------------- users (admin)

export type UserRow = {
  id: string;
  email: string;
  name: string;
  role: "admin" | "user";
  approved: boolean;
  createdAt: Date;
  examCount: number;
  questionCount: number;
  lastSeen: Date | null;
};

/** Admin-only: every account with its content totals. Throws FORBIDDEN for non-admins. */
export async function listUsers(): Promise<UserRow[]> {
  await requireAdmin();
  const rows = await query<{
    id: string;
    email: string;
    name: string;
    role: string;
    approved: boolean;
    created_at: Date;
    exam_count: string;
    question_count: string;
    last_seen: Date | null;
  }>(
    `SELECT u.id, u.email, u.name, u.role, u.approved, u.created_at,
            (SELECT count(*)::text FROM exams e WHERE e.user_id = u.id) AS exam_count,
            (SELECT count(*)::text FROM questions q WHERE q.user_id = u.id) AS question_count,
            (SELECT max(created_at) FROM quiz_sessions qs WHERE qs.user_id = u.id) AS last_seen
     FROM users u
     ORDER BY u.created_at ASC`
  );
  return rows.map((r) => ({
    id: r.id,
    email: r.email,
    name: r.name,
    role: r.role === "admin" ? "admin" : "user",
    approved: r.approved,
    createdAt: r.created_at,
    examCount: Number(r.exam_count),
    questionCount: Number(r.question_count),
    lastSeen: r.last_seen,
  }));
}

export type ContentGrants = {
  examIds: string[];
  /** True when the user can see the general-knowledge question bank (questions with no exam). */
  general: boolean;
};

/** Admin-only: which content a user is allowed to see. */
export async function getUserGrants(userId: string): Promise<ContentGrants> {
  await requireAdmin();
  const rows = await query<{ exam_id: string | null }>(
    "SELECT exam_id FROM content_grants WHERE user_id = $1",
    [userId]
  );
  return {
    examIds: rows.filter((r) => r.exam_id).map((r) => r.exam_id as string),
    general: rows.some((r) => r.exam_id === null),
  };
}