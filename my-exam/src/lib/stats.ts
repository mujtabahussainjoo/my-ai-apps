import { query } from "@/lib/db";

export type DayStat = { date: string; quizCount: number; studyMins: number; accuracy: number | null };

export async function getStats(userId: string) {
  const [totals] = await query<{
    quizCount: string;
    mockCount: string;
    questionCount: string;
    flashcardCount: string;
    materialCount: string;
    examCount: string;
    totalStudySec: string;
  }>(
    `SELECT
       (SELECT count(*)::text FROM quiz_sessions WHERE user_id = $1 AND mode = 'quiz' AND completed_at IS NOT NULL) AS "quizCount",
       (SELECT count(*)::text FROM quiz_sessions WHERE user_id = $1 AND mode = 'mock' AND completed_at IS NOT NULL) AS "mockCount",
       (SELECT count(*)::text FROM questions WHERE user_id = $1) AS "questionCount",
       (SELECT count(*)::text FROM flashcards WHERE user_id = $1) AS "flashcardCount",
       (SELECT count(*)::text FROM materials WHERE user_id = $1) AS "materialCount",
       (SELECT count(*)::text FROM exams WHERE user_id = $1) AS "examCount",
       (SELECT COALESCE(sum(seconds)::text, '0') FROM study_sessions WHERE user_id = $1) AS "totalStudySec"`,
    [userId]
  );

  // Overall accuracy across completed quiz/mock sessions
  const [acc] = await query<{ score: string; total: string }>(
    `SELECT COALESCE(sum(score)::text, '0') AS score, COALESCE(sum(total)::text, '0') AS total
     FROM quiz_sessions WHERE user_id = $1 AND completed_at IS NOT NULL AND mode IN ('quiz','mock')`,
    [userId]
  );

  // Last 14 days activity (study seconds + completed quizzes + accuracy)
  const days = await query<{
    d: string;
    sec: string;
    qc: string;
    sc: string;
    to: string;
  }>(
    `WITH ds AS (
       SELECT d::date AS d FROM generate_series(now() - interval '13 days', now(), interval '1 day') AS d
     )
     SELECT ds.d::text AS d,
            COALESCE(sum(s.seconds), 0)::text AS sec,
            COALESCE((SELECT count(*) FROM quiz_sessions q
                       WHERE q.user_id = $1 AND q.completed_at IS NOT NULL AND q.mode IN ('quiz','mock')
                         AND q.completed_at::date = ds.d), 0)::text AS qc,
            COALESCE((SELECT sum(q.score) FROM quiz_sessions q
                       WHERE q.user_id = $1 AND q.completed_at IS NOT NULL AND q.mode IN ('quiz','mock')
                         AND q.completed_at::date = ds.d), 0)::text AS sc,
            COALESCE((SELECT sum(q.total) FROM quiz_sessions q
                       WHERE q.user_id = $1 AND q.completed_at IS NOT NULL AND q.mode IN ('quiz','mock')
                         AND q.completed_at::date = ds.d), 0)::text AS to
     FROM ds LEFT JOIN study_sessions s ON s.user_id = $1 AND s.study_date = ds.d
     GROUP BY ds.d ORDER BY ds.d`,
    [userId]
  );

  const dayStats: DayStat[] = days.map((r) => {
    const total = Number(r.to);
    return {
      date: r.d,
      studyMins: Math.round(Number(r.sec) / 60),
      quizCount: Number(r.qc),
      accuracy: total > 0 ? Math.round((Number(r.sc) / total) * 100) : null,
    };
  });

  // Current streak
  const today = new Date();
  const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  let streak = 0;
  let cursor = new Date(today);
  const dayOf = (d: Date) => {
    const key = ymd(d);
    return dayStats.find((s) => s.date === key);
  };
  // count from today backwards
  for (let i = 0; i < 400; i++) {
    const s = dayOf(cursor);
    const hasActivity = !!s && (s.quizCount > 0 || s.studyMins > 0);
    if (i === 0 && !hasActivity) {
      // today not yet — start from yesterday
      cursor = new Date(cursor.getTime() - 86400000);
      continue;
    }
    if (hasActivity) {
      streak++;
      cursor = new Date(cursor.getTime() - 86400000);
    } else break;
  }

  const totalScore = Number(acc?.score ?? 0);
  const totalTotal = Number(acc?.total ?? 0);
  const overallAccuracy = totalTotal > 0 ? Math.round((totalScore / totalTotal) * 100) : 0;

  // Best topics by accuracy (from last 30 days of sessions)
  const topicPerformance = await query<{
    topicId: string | null;
    topic: string | null;
    exam: string | null;
    total: string;
    correct: string;
  }>(
    `SELECT (a.entry->>'topicId')::uuid AS "topicId", t.name AS topic, e.title AS exam,
            count(*)::text AS total,
            sum(CASE WHEN (a.entry->>'correct')::boolean THEN 1 ELSE 0 END)::text AS correct
     FROM quiz_sessions qs
     CROSS JOIN LATERAL jsonb_array_elements(qs.answers) AS a(entry)
     LEFT JOIN topics t ON t.id = (a.entry->>'topicId')::uuid
     LEFT JOIN exams e ON e.id = qs.exam_id
     WHERE qs.user_id = $1 AND qs.completed_at IS NOT NULL AND qs.mode IN ('quiz','mock')
       AND qs.completed_at > now() - interval '90 days'
       AND a.entry->>'topicId' IS NOT NULL
     GROUP BY (a.entry->>'topicId')::uuid, t.name, e.title
     ORDER BY sum(CASE WHEN (a.entry->>'correct')::boolean THEN 1 ELSE 0 END)::int DESC
     LIMIT 8`,
    [userId]
  );

  // Recent sessions
  const recent = await query<{
    id: string;
    title: string;
    mode: string;
    score: string;
    total: string;
    completedAt: Date | null;
  }>(
    `SELECT id, title, mode, score::text AS score, total::text AS total, completed_at AS "completedAt"
     FROM quiz_sessions
     WHERE user_id = $1
     ORDER BY created_at DESC LIMIT 6`,
    [userId]
  );

  return {
    totals: {
      quizCount: Number(totals?.quizCount ?? 0),
      mockCount: Number(totals?.mockCount ?? 0),
      questionCount: Number(totals?.questionCount ?? 0),
      flashcardCount: Number(totals?.flashcardCount ?? 0),
      materialCount: Number(totals?.materialCount ?? 0),
      examCount: Number(totals?.examCount ?? 0),
      totalStudySec: Number(totals?.totalStudySec ?? 0),
    },
    overallAccuracy,
    streak,
    dayStats,
    topicPerformance: topicPerformance.map((r) => ({
      topicId: r.topicId,
      topic: r.topic ?? "Untagged",
      exam: r.exam,
      total: Number(r.total),
      correct: Number(r.correct),
      pct:
        Number(r.total) > 0
          ? Math.round((Number(r.correct) / Number(r.total)) * 100)
          : 0,
    })),
    recent: recent.map((r) => ({
      id: r.id,
      title: r.title,
      mode: r.mode,
      score: Number(r.score),
      total: Number(r.total),
      completedAt: r.completedAt,
    })),
  };
}

export async function getMasteryForExam(userId: string, examId: string) {
  const rows = await query<{
    topicId: string;
    topic: string;
    total: string;
    correct: string;
  }>(
    `SELECT t.id AS "topicId", t.name AS topic,
            count(*)::text AS total,
            sum(CASE WHEN (a.entry->>'correct')::boolean THEN 1 ELSE 0 END)::text AS correct
     FROM quiz_sessions qs
     CROSS JOIN LATERAL jsonb_array_elements(qs.answers) AS a(entry)
     JOIN topics t ON t.id = (a.entry->>'topicId')::uuid
     WHERE qs.user_id = $1 AND qs.exam_id = $2 AND qs.completed_at IS NOT NULL
       AND a.entry->>'topicId' IS NOT NULL
     GROUP BY t.id, t.name
     ORDER BY t.sort_order`,
    [userId, examId]
  );
  return rows.map((r) => ({
    topicId: r.topicId,
    topic: r.topic,
    total: Number(r.total),
    correct: Number(r.correct),
    pct: Number(r.total) > 0 ? Math.round((Number(r.correct) / Number(r.total)) * 100) : 0,
  }));
}