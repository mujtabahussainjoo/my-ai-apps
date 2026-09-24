import { redirect, notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getQuizSession, parseQuestions, sanitizeQuestions } from "@/lib/data";
import { QuizRunner } from "@/components/quiz-runner";

export const dynamic = "force-dynamic";

export default async function TakeMockPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const session = await getQuizSession(id);
  if (!session) notFound();
  if (session.mode !== "mock") redirect(`/quiz/${id}`);
  if (session.completedAt) redirect(`/mock/${id}/result`);

  const questions = sanitizeQuestions(parseQuestions(session.questions));
  const timerSeconds = Math.max(60, session.numQuestions * 60);

  return (
    <QuizRunner
      sessionId={session.id}
      questions={questions}
      mode="mock"
      title={session.title || "Mock exam"}
      allowShort={false}
      timerSeconds={timerSeconds}
    />
  );
}