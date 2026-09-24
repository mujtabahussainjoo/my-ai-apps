import { redirect, notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getQuizSession, parseQuestions, parseAnswers } from "@/lib/data";
import { ResultView, type ResultItem } from "@/components/result-view";

export const dynamic = "force-dynamic";

export default async function QuizResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const session = await getQuizSession(id);
  if (!session) notFound();
  if (!session.completedAt) redirect(`/quiz/${id}`);

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

  return (
    <ResultView
      sessionId={session.id}
      mode={session.mode}
      title={session.title || "Practice quiz"}
      items={items}
      score={session.score}
      total={session.total}
      durationSec={session.durationSec}
    />
  );
}