-- MyExam schema (idempotent — safe to run repeatedly)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  name          TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE INDEX IF NOT EXISTS idx_topics_exam      ON topics(exam_id);
CREATE INDEX IF NOT EXISTS idx_materials_user   ON materials(user_id);
CREATE INDEX IF NOT EXISTS idx_materials_exam   ON materials(exam_id);
CREATE INDEX IF NOT EXISTS idx_chunks_material  ON chunks(material_id);
CREATE INDEX IF NOT EXISTS idx_questions_user   ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_exam   ON questions(exam_id);
CREATE INDEX IF NOT EXISTS idx_questions_topic  ON questions(topic_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_due   ON flashcards(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_quiz_user        ON quiz_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_study_user_date  ON study_sessions(user_id, study_date);