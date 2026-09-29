-- MyExam schema (idempotent — safe to run repeatedly)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  name          TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',  -- user | admin (admins see every user's content)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Make sure existing installations get the role column (idempotent).
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';
ALTER TABLE users
  ALTER COLUMN role SET DEFAULT 'user';

CREATE TABLE IF NOT EXISTS exams (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  description TEXT,
  target_date DATE,
  color       TEXT NOT NULL DEFAULT '#6366f1',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topics (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exam_id     UUID NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  weightage   INT NOT NULL DEFAULT 0,
  description TEXT,
  sort_order  INT NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Topics nest under a parent topic as subtopics (e.g. LLMs → How LLMs Behave).
ALTER TABLE topics
  ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES topics(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_topics_parent ON topics (parent_id) WHERE parent_id IS NOT NULL;

-- A named library/collection of training docs. Selected from a dropdown when
-- generating questions so retrieval is explicitly scoped to the right material.
CREATE TABLE IF NOT EXISTS knowledge_bases (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS materials (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  exam_id    UUID REFERENCES exams(id) ON DELETE SET NULL,
  title      TEXT NOT NULL,
  type       TEXT NOT NULL DEFAULT 'TEXT',  -- TEXT | URL | FILE
  source     TEXT,                          -- original url or filename
  content    TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'ready', -- processing | ready | failed
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Attach materials to a knowledge base (idempotent for existing databases).
ALTER TABLE materials
  ADD COLUMN IF NOT EXISTS knowledge_base_id UUID REFERENCES knowledge_bases(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  material_id UUID NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  content     TEXT NOT NULL,
  position    INT NOT NULL DEFAULT 0,
  embedding   DOUBLE PRECISION[] NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS questions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  exam_id     UUID REFERENCES exams(id) ON DELETE CASCADE,
  topic_id    UUID REFERENCES topics(id) ON DELETE SET NULL,
  type        TEXT NOT NULL DEFAULT 'mcq',      -- mcq | true_false | short | interview
  category    TEXT,                             -- interview category: behavioral | technical | scenario | hr
  prompt      TEXT NOT NULL,
  choices     JSONB DEFAULT NULL,               -- [{"text": "...", "correct": bool}, ...]
  answer      TEXT,                             -- model answer / explanation for short & interview
  explanation TEXT,
  source      TEXT NOT NULL DEFAULT 'manual',   -- manual | ai
  points      INT NOT NULL DEFAULT 1,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS flashcards (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  exam_id          UUID REFERENCES exams(id) ON DELETE CASCADE,
  topic_id         UUID REFERENCES topics(id) ON DELETE SET NULL,
  front            TEXT NOT NULL,
  back             TEXT NOT NULL,
  box              INT NOT NULL DEFAULT 0,     -- Leitner box 0..4
  reps             INT NOT NULL DEFAULT 0,
  lapses           INT NOT NULL DEFAULT 0,
  interval_days    DOUBLE PRECISION NOT NULL DEFAULT 0,
  due_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_reviewed_at TIMESTAMPTZ,
  source           TEXT NOT NULL DEFAULT 'manual',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quiz_sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  exam_id      UUID REFERENCES exams(id) ON DELETE SET NULL,
  topic_id     UUID REFERENCES topics(id) ON DELETE SET NULL,
  mode         TEXT NOT NULL DEFAULT 'quiz',   -- quiz | mock | interview
  title        TEXT NOT NULL,
  questions    JSONB NOT NULL DEFAULT '[]',    -- snapshot of the question payloads (answers stripped)
  num_questions INT NOT NULL DEFAULT 0,
  score        INT NOT NULL DEFAULT 0,
  total        INT NOT NULL DEFAULT 0,
  answers      JSONB NOT NULL DEFAULT '[]',    -- [{questionId, topicId, chosen, correct, points, explanation}]
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  duration_sec INT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS study_sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  seconds     INT NOT NULL DEFAULT 0,
  study_date  DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user AI / assistant configuration (settings menu)
CREATE TABLE IF NOT EXISTS user_settings (
  user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  ai_provider         TEXT NOT NULL DEFAULT 'local',  -- local (Ollama & co) | openai (API key)
  ai_base_url         TEXT,                           -- e.g. http://localhost:11434/v1 | https://api.openai.com/v1
  ai_api_key          TEXT,
  ai_model            TEXT,
  ai_embedding_model  TEXT,
  assistant_enabled   BOOLEAN NOT NULL DEFAULT TRUE,  -- toggle for the AI study assistant
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Diagnostics: why generation failed, in the app, instead of only in the
-- terminal. Written by src/lib/diagnostics.ts, which never throws.
CREATE TABLE IF NOT EXISTS diagnostic_events (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  level       TEXT NOT NULL DEFAULT 'info',  -- info | warn | error
  kind        TEXT NOT NULL,                 -- generate | ai-config | upload | system
  message     TEXT NOT NULL,
  details     JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_diag_user_time ON diagnostic_events(user_id, created_at DESC);

-- Persistent study-assistant conversations
CREATE TABLE IF NOT EXISTS chat_sessions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT NOT NULL DEFAULT 'Assistant chat',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  role       TEXT NOT NULL,              -- user | assistant
  content    TEXT NOT NULL,
  sources    JSONB NOT NULL DEFAULT '[]',-- [{title, materialId, snippet}] cited material chunks
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_topics_exam      ON topics(exam_id);
CREATE INDEX IF NOT EXISTS idx_materials_user   ON materials(user_id);
CREATE INDEX IF NOT EXISTS idx_materials_exam   ON materials(exam_id);
CREATE INDEX IF NOT EXISTS idx_materials_kb     ON materials(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_kb_user          ON knowledge_bases(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_material  ON chunks(material_id);
CREATE INDEX IF NOT EXISTS idx_chunks_fts       ON chunks USING GIN (to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS idx_questions_user   ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_exam   ON questions(exam_id);
CREATE INDEX IF NOT EXISTS idx_questions_topic  ON questions(topic_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_due   ON flashcards(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_quiz_user        ON quiz_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_study_user_date  ON study_sessions(user_id, study_date);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_sessions(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);