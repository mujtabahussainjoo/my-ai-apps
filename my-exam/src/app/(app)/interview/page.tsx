import { redirect } from "next/navigation";
import Link from "next/link";
import { Mic, Sparkles, History } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams, getInterviewHistory } from "@/lib/data";
import { Card, Badge } from "@/components/ui";
import { InterviewSetup } from "@/components/interview";
import { timeAgo } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function InterviewPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const [exams, history] = await Promise.all([listExams(), getInterviewHistory(user.id)]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Interview coach</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Practice against an AI interviewer that grades each of your answers with STAR-style feedback.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <InterviewSetup exams={exams.map((e) => ({ id: e.id, title: e.title }))} />

        <div>
          <h2 className="mb-3 flex items-center gap-2 font-semibold">
            <History className="h-4 w-4 text-foreground/50" /> Graded sessions
          </h2>
          {history.length === 0 ? (
            <Card className="flex flex-col items-center gap-3 border-dashed py-12 text-center">
              <Sparkles className="h-7 w-7 text-rose-300" />
              <p className="max-w-sm text-sm text-foreground/60">
                Run your first AI interview. It generates realistic questions, then scores your answers on situation, task,
                action and result.
              </p>
            </Card>
          ) : (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {history.map((h) => {
                const entries: AnswerEntryLite[] = Array.isArray(h.answers)
                  ? (h.answers as AnswerEntryLite[])
                  : (JSON.parse(String(h.answers)) as AnswerEntryLite[]);
                const graded = entries.filter((e) => e.feedback?.score).length;
                const avg = graded > 0 ? Math.round(entries.reduce((s, e) => s + (e.feedback?.score ?? 0), 0) / graded) : null;
                return (
                  <Link key={h.id} href={`/interview/${h.id}/result`} className="card block p-4 transition-all hover:border-rose-400/30">
                    <div className="flex items-center justify-between gap-2">
                      <span className="line-clamp-1 font-medium">{h.title}</span>
                      <Badge color="slate">{timeAgo(h.createdAt)}</Badge>
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-xs text-foreground/55">
                      <Mic className="h-3 w-3" /> {h.numQuestions} questions · {graded} graded
                      {avg !== null && (
                        <span className="ml-auto font-bold text-foreground/80">avg {avg}/100</span>
                      )}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

type AnswerEntryLite = {
  feedback?: { score?: number } | null;
};