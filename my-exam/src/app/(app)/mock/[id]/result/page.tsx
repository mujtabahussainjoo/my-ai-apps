import { redirect, notFound } from "next/navigation";
import { Scale, TrendingDown, TrendingUp } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { getQuizSession, parseQuestions, parseAnswers, listTopics } from "@/lib/data";
import { ResultView, type ResultItem } from "@/components/result-view";
import { Card, Progress } from "@/components/ui";
import { colorForIndex } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function MockResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const session = await getQuizSession(id);
  if (!session) notFound();
  if (session.mode !== "mock") redirect(`/quiz/${id}/result`);
  if (!session.completedAt) redirect(`/mock/${id}`);

  const questions = parseQuestions(session.questions);
  const answers = parseAnswers(session.answers);
  const items: ResultItem[] = questions.map((q) => {
    const a = answers.find((x) => x.questionId === q.id) ?? {
      questionId: q.id,
      chosen: null,
      correct: false,
      points: q.points,
      got: 0,
    };
    return { question: q, answer: a };
  });

  const topics = session.examId ? await listTopics(session.examId) : [];
  const totalWeight = topics.reduce((s, t) => s + t.weightage, 0) || 1;
  const overallPct = session.total > 0 ? (session.score / session.total) * 100 : 0;

  const byTopic = topics
    .map((t, i) => {
      const inTopic = items.filter((it) => it.question.topicId === t.id);
      const points = inTopic.reduce((s, it) => s + (it.answer.points ?? 1), 0);
      const got = inTopic.reduce((s, it) => s + (it.answer.got ?? 0), 0);
      const pct = points > 0 ? (got / points) * 100 : null;
      const expected = Math.round((t.weightage / totalWeight) * session.total);
      return {
        name: t.name,
        weightage: t.weightage,
        expected,
        questions: inTopic.length,
        points,
        got,
        pct,
        color: colorForIndex(i),
      };
    })
    .filter((t) => t.questions > 0);

  const estimate =
    byTopic.reduce((s, t) => s + (t.pct ?? 0) * t.weightage, 0) / totalWeight;

  return (
    <div className="space-y-6">
      <ResultView
        sessionId={session.id}
        mode={session.mode}
        title={session.title || "Mock exam"}
        items={items}
        score={session.score}
        total={session.total}
        durationSec={session.durationSec}
      />

      {byTopic.length > 0 && (
        <Card className="p-5">
          <div className="mb-1 flex items-center gap-2">
            <Scale className="h-4 w-4 text-sky-300" />
            <h2 className="font-semibold">Weighted score report</h2>
          </div>
          <p className="mb-4 text-xs text-foreground/55">
            Applying your topic weightages to this performance estimates a score of{" "}
            <span className="font-bold text-foreground/85">{Math.round(estimate)}%</span> on the full paper
            {Math.abs(estimate - overallPct) >= 3 && (
              <span className="ml-1 inline-flex items-center gap-1 font-medium">
                {estimate > overallPct ? (
                  <span className="text-sky-300">
                    <TrendingUp className="mr-0.5 inline h-3 w-3" /> more favourable
                  </span>
                ) : (
                  <span className="text-rose-300">
                    <TrendingDown className="mr-0.5 inline h-3 w-3" /> worse than raw
                  </span>
                )}
                than your raw score
              </span>
            )}
            .
          </p>

          <div className="grid gap-2 sm:grid-cols-2">
            {byTopic.map((t) => (
              <div key={t.name} className="rounded-xl border border-white/8 bg-white/3 p-3.5">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: t.color }} />
                    <span className="truncate text-sm font-semibold">{t.name}</span>
                  </div>
                  <span className="shrink-0 text-[11px] font-bold text-foreground/55">{t.weightage}% weight</span>
                </div>
                <Progress
                  value={t.pct ?? 0}
                  color={t.pct === null ? "#8b5cf6" : t.pct >= 70 ? "#10b981" : t.pct >= 50 ? "#f59e0b" : "#f43f5e"}
                />
                <div className="mt-2 flex items-center justify-between text-[11px] text-foreground/55">
                  <span>
                    {t.questions} asked · {t.got}/{t.points} correct
                  </span>
                  <span className="font-bold">{t.pct === null ? "—" : `${Math.round(t.pct)}%`}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}