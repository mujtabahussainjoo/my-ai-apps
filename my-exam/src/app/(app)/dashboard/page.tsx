import Link from "next/link";
import { redirect } from "next/navigation";
import {
  Flame,
  Target,
  Clock,
  ListChecks,
  Layers,
  Zap,
  Trophy,
  NotebookPen,
  Mic,
  ArrowRight,
  ScrollText,
} from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { getStats } from "@/lib/stats";
import { listExams } from "@/lib/data";
import { Stat, Card, Progress, Badge, EmptyState } from "@/components/ui";
import { AccuracyArea, MasteryBars } from "@/components/charts";
import { StudyTimer } from "@/components/study-timer";
import { colorForIndex, formatDate, timeAgo } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const [stats, exams] = await Promise.all([getStats(user.id), listExams()]);

  const dayStats = stats.dayStats.map((d) => ({
    label: new Date(d.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    accuracy: d.accuracy,
    studyMins: d.studyMins,
  }));

  const topicData = stats.topicPerformance.map((t, i) => ({
    ...t,
    color: colorForIndex(i),
  }));

  const totalStudyMins = Math.round(stats.totals.totalStudySec / 60);

  return (
    <div className="space-y-6">
      {/* Hero */}
      <section className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <Card className="relative overflow-hidden p-6 sm:p-7">
          <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-violet-600/20 blur-3xl" />
          <div className="relative">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground/60">
              <Flame className="h-4 w-4 text-orange-400" />
              {stats.streak > 0 ? (
                <span>
                  <span className="font-bold text-orange-300">{stats.streak}-day streak</span> — keep it going
                </span>
              ) : (
                <span>Start your streak today</span>
              )}
            </div>
            <h1 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
              Welcome back, <span className="grad-text">{user.name.split(" ")[0]}</span> 👋
            </h1>
            <p className="mt-1.5 text-sm text-foreground/60">
              {exams.length === 0
                ? "Create your first exam, add study material, and let AI build the prep."
                : `You have ${exams.length} plan${exams.length > 1 ? "s" : ""} in progress.`}
            </p>
            <div className="mt-5 flex flex-wrap gap-2.5">
              <Link href="/quiz" className="btn btn-primary">
                <Zap className="h-4 w-4" /> Practice quiz
              </Link>
              <Link href="/mock" className="btn btn-secondary">
                <Trophy className="h-4 w-4" /> Mock exam
              </Link>
              <Link href="/flashcards" className="btn btn-secondary">
                <Layers className="h-4 w-4" /> Flashcards
              </Link>
              <Link href="/interview" className="btn btn-secondary">
                <Mic className="h-4 w-4" /> Interview
              </Link>
            </div>
          </div>
        </Card>
        <StudyTimer />
      </section>

      {/* Stat grid */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <Stat label="Streak" value={`${stats.streak}d`} icon={<Flame className="h-4 w-4" />} />
        <Stat label="Accuracy" value={`${stats.overallAccuracy}%`} icon={<Target className="h-4 w-4" />} />
        <Stat label="Study time" value={totalStudyMins >= 60 ? `${Math.round(totalStudyMins / 60)}h` : `${totalStudyMins}m`} icon={<Clock className="h-4 w-4" />} />
        <Stat label="Sessions" value={stats.totals.quizCount + stats.totals.mockCount} icon={<ListChecks className="h-4 w-4" />} />
        <Stat label="Questions" value={stats.totals.questionCount} icon={<NotebookPen className="h-4 w-4" />} />
        <Stat label="Flashcards" value={stats.totals.flashcardCount} icon={<Layers className="h-4 w-4" />} />
      </section>

      {/* Charts */}
      <section className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Accuracy — last 14 days</h2>
            {dayStats.some((d) => d.accuracy !== null) && (
              <Badge color="violet">Practice</Badge>
            )}
          </div>
          <AccuracyArea data={dayStats} />
          {!dayStats.some((d) => d.accuracy !== null) && (
            <p className="mt-2 text-center text-xs text-foreground/50">
              Complete a quiz to start tracking accuracy over time.
            </p>
          )}
        </Card>
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Topic mastery</h2>
            <Badge color="emerald">By accuracy</Badge>
          </div>
          <MasteryBars data={topicData} />
        </Card>
      </section>

      {/* Exams + recent */}
      <section className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Your study plans</h2>
            <Link href="/exams" className="flex items-center gap-1 text-sm font-medium text-violet-300 hover:text-violet-200">
              Manage <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          {exams.length === 0 ? (
            <EmptyState
              icon={<ScrollText className="h-6 w-6" />}
              title="No exams yet"
              description="Create your first exam plan, set topic weightages, and train PrepDesk with your materials."
              action={
                <Link href="/exams" className="btn btn-primary">
                  Create an exam plan
                </Link>
              }
            />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {exams.map((exam) => (
                <Link key={exam.id} href={`/exams/${exam.id}`} className="card group p-5 transition-all hover:-translate-y-0.5 hover:border-violet-400/30">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold leading-snug">{exam.title}</div>
                      {exam.targetDate && (
                        <div className="mt-0.5 text-xs text-foreground/55">Target · {formatDate(exam.targetDate)}</div>
                      )}
                    </div>
                    <span className="mt-0.5 h-3 w-3 shrink-0 rounded-full" style={{ background: exam.color }} />
                  </div>
                  <div className="mt-4 flex items-center gap-2 text-[11px] text-foreground/55">
                    <span className="tag">{exam.topicCount} topics</span>
                    <span className="tag">{exam.questionCount} Qs</span>
                    <span className="tag">{exam.mockCount} mocks</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <h2 className="text-lg font-semibold">Recent sessions</h2>
          {stats.recent.length === 0 ? (
            <Card className="border-dashed py-10 text-center text-sm text-foreground/55">
              No completed sessions yet.
            </Card>
          ) : (
            <div className="space-y-2.5">
              {stats.recent.map((r) => {
                const pct = r.total > 0 ? Math.round((r.score / r.total) * 100) : 0;
                return (
                  <Link
                    key={r.id}
                    href={r.mode === "mock" ? `/mock/${r.id}/result` : `/quiz/${r.id}/result`}
                    className="card block p-3.5 transition-all hover:border-violet-400/30"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{r.title}</span>
                      <Badge color={r.mode === "mock" ? "sky" : "violet"}>{r.mode === "mock" ? "mock" : "quiz"}</Badge>
                    </div>
                    <div className="mb-2 flex items-center justify-between text-xs text-foreground/55">
                      <span>{timeAgo(r.completedAt)}</span>
                      <span className="font-semibold text-foreground/80">
                        {r.score}/{r.total} · {pct}%
                      </span>
                    </div>
                    <Progress value={pct} color={pct >= 70 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#f43f5e"} />
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}