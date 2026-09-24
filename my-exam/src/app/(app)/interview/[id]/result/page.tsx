import { redirect, notFound } from "next/navigation";
import { Sparkles, Calendar } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { getInterviewSession, parseQuestions, parseAnswers } from "@/lib/data";
import { FeedbackCard } from "@/components/interview";
import { Card, Badge } from "@/components/ui";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function InterviewResultPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const session = await getInterviewSession(id);
  if (!session) notFound();
  if (!session.completedAt) redirect(`/interview/${id}`);

  const questions = parseQuestions(session.questions);
  const answers = parseAnswers(session.answers);

  const graded = answers.filter((a) => a.feedback?.score).length;
  const avgScore = graded > 0 ? Math.round(answers.reduce((s, a) => s + (a.feedback?.score ?? 0), 0) / graded) : null;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Interview report</h1>
        <p className="mt-1 text-sm text-foreground/60">
          {session.title}
        </p>
      </div>

      <Card className="flex flex-wrap items-center gap-6 p-5">
        <div>
          <div className="text-4xl font-bold tracking-tight">{avgScore ?? "—"}</div>
          <div className="mt-0.5 text-xs uppercase tracking-wider text-foreground/50">average score</div>
        </div>
        <div>
          <div className="text-4xl font-bold tracking-tight text-rose-300">{graded}</div>
          <div className="mt-0.5 text-xs uppercase tracking-wider text-foreground/50">graded answers</div>
        </div>
        <div className="ml-auto">
          <Badge color="slate">AI-graded</Badge>
        </div>
      </Card>

      <div className="space-y-4">
        {questions.map((q) => {
          const a = answers.find((x) => x.questionId === q.id);
          if (!a) return null;
          return <FeedbackCard key={q.id} question={q} answer={a} />;
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/3 p-4">
        <p className="flex items-center gap-2 text-sm text-foreground/60">
          <Sparkles className="h-4 w-4 text-violet-300" />
          PRACTICE IS A MUSCLE. Redo this interview later and compare scores.
        </p>
        <div className="flex gap-2">
          <Link
            href="/interview"
            className="btn btn-secondary"
          >
            <Calendar className="h-4 w-4" /> Practice again
          </Link>
        </div>
      </div>
    </div>
  );
}