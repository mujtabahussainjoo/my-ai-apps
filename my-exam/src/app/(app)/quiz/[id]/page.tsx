import { redirect, notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getQuizSession, parseQuestions, sanitizeQuestions } from "@/lib/data";
import { QuizRunner } from "@/components/quiz-runner";

export const dynamic = "force-dynamic";

export default async function TakeQuizPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const session = await getQuizSession(id);
  if (!session) notFound();
  if (session.completedAt) redirect(`/quiz/${id}/result`);
  if (session.mode === "mock") redirect(`/mock/${id}`);

  const questions = sanitizeQuestions(parseQuestions(session.questions));

  return (
    <QuizRunner
      sessionId={session.id}
      questions={questions}
      mode="quiz"
      title={session.title || "Practice quiz"}
      allowShort={session.mode === "quiz"}
      timerSeconds={null}
    />
  );
}