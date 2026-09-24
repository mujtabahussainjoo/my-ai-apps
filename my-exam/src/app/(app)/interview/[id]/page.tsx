import { redirect, notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getInterviewSession, parseQuestions, sanitizeQuestions } from "@/lib/data";
import { InterviewRunner } from "@/components/interview";

export const dynamic = "force-dynamic";

export default async function TakeInterviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const session = await getInterviewSession(id);
  if (!session) notFound();
  if (session.completedAt) redirect(`/interview/${id}/result`);

  const questions = sanitizeQuestions(parseQuestions(session.questions));

  return (
    <InterviewRunner
      sessionId={session.id}
      questions={questions}
      title={session.title || "Interview practice"}
    />
  );
}