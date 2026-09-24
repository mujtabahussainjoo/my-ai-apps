import Link from "next/link";
import { redirect } from "next/navigation";
import { Zap, Clock } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams, listSessions } from "@/lib/data";
import { Badge, EmptyState, Progress } from "@/components/ui";
import { QuizSetup } from "@/components/setup";
import { timeAgo } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function QuizPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const [exams, sessions] = await Promise.all([
    listExams(),
    listSessions("quiz", 10),
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Practice quiz</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Rapid-fire practice drawn from your question bank and AI — perfect for daily reps.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <QuizSetup exams={exams.map((e) => ({ id: e.id, title: e.title, topicCount: e.topicCount }))} />

        <div>
          <h2 className="mb-3 flex items-center gap-2 font-semibold">
            <Clock className="h-4 w-4 text-foreground/50" /> Recent attempts
          </h2>
          {sessions.length === 0 ? (
            <EmptyState
              icon={<Zap className="h-6 w-6" />}
              title="No practice yet"
              description="Start a quiz on the left — results appear here with accuracy tracking over time."
            />
          ) : (
            <div className="space-y-2.5">
              {sessions.map((s) => {
                const pct = s.total > 0 ? Math.round((s.score / s.total) * 100) : 0;
                return (
                  <Link
                    key={s.id}
                    href={`/quiz/${s.id}/result`}
                    className="card block p-4 transition-all hover:border-violet-400/30"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="font-medium">{s.title}</div>
                        <div className="mt-0.5 text-xs text-foreground/50">
                          {s.numQuestions} questions · {timeAgo(s.completedAt ?? s.startedAt)}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-bold">
                          {s.score}/{s.total}
                        </span>
                        <Badge color={pct >= 70 ? "emerald" : pct >= 50 ? "amber" : "rose"}>{pct}%</Badge>
                      </div>
                    </div>
                    <div className="mt-2.5">
                      <Progress value={pct} color={pct >= 70 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#f43f5e"} />
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