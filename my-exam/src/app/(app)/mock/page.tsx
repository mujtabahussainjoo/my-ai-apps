import { redirect } from "next/navigation";
import Link from "next/link";
import { Trophy, Clock, Target } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams, listSessions } from "@/lib/data";
import { Card, Badge, EmptyState, Progress } from "@/components/ui";
import { MockSetup } from "@/components/setup";
import { timeAgo } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function MockPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const [exams, sessions] = await Promise.all([listExams(), listSessions("mock", 10)]);

  const weighted = exams.filter((e) => e.topicCount > 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Mock exams</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Timed, full-length papers weighted exactly by your topic weightage — scored with a per-topic breakdown.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <div className="space-y-4">
          <MockSetup exams={weighted.map((e) => ({ id: e.id, title: e.title, topicCount: e.topicCount }))} />
          {exams.length > 0 && weighted.length === 0 && (
            <Card className="border-amber-400/20 bg-amber-500/5 text-sm text-amber-200">
              Add topics with weightage to an exam to enable weighted mocks.
            </Card>
          )}
        </div>

        <div>
          <h2 className="mb-3 flex items-center gap-2 font-semibold">
            <Clock className="h-4 w-4 text-foreground/50" /> Past mocks
          </h2>
          {sessions.length === 0 ? (
            <EmptyState
              icon={<Trophy className="h-6 w-6" />}
              title="No mocks yet"
              description="Generate your first weighted mock — it adapts questions to your syllabus split."
            />
          ) : (
            <div className="space-y-2.5">
              {sessions.map((s) => {
                const pct = s.total > 0 ? Math.round((s.score / s.total) * 100) : 0;
                const completed = !!s.completedAt;
                return (
                  <Link
                    key={s.id}
                    href={completed ? `/mock/${s.id}/result` : `/mock/${s.id}`}
                    className="card block p-4 transition-all hover:border-violet-400/30"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="font-medium">{s.title}</div>
                        <div className="mt-0.5 flex items-center gap-2 text-xs text-foreground/50">
                          <Clock className="h-3 w-3" />
                          {s.numQuestions} questions
                          <span>·</span>
                          {timeAgo(s.completedAt ?? s.startedAt)}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {completed ? (
                          <>
                            <span className="text-sm font-bold">
                              {s.score}/{s.total}
                            </span>
                            <Badge color={pct >= 70 ? "emerald" : pct >= 50 ? "amber" : "rose"}>{pct}%</Badge>
                          </>
                        ) : (
                          <Badge color="sky">In progress</Badge>
                        )}
                      </div>
                    </div>
                    {completed && (
                      <div className="mt-2.5">
                        <Progress value={pct} color={pct >= 70 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#f43f5e"} />
                      </div>
                    )}
                  </Link>
                );
              })}
            </div>
          )}

          <Card className="mt-4 flex items-start gap-3 border-dashed text-sm text-foreground/60">
            <Target className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" />
            <p>
              Each mock sets 1 minute per question. The score report maps every missed question back to its topic weight, so
              you can see exactly where a 10% drop in accuracy costs you marks.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}