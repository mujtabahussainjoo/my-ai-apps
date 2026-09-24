import Link from "next/link";
import { redirect } from "next/navigation";
import { GraduationCap, ArrowRight, CalendarDays, CircleHelp } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams } from "@/lib/data";
import { Card, Badge, EmptyState } from "@/components/ui";
import { CreateExamForm } from "@/components/exam-forms";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function ExamsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const exams = await listExams();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Exams & Weightage</h1>
          <p className="mt-1 text-sm text-foreground/60">
            Define your exams and their topic weightages — mock exams mirror them exactly.
          </p>
        </div>
        <CreateExamForm />
      </div>

      {exams.length === 0 ? (
        <EmptyState
          icon={<GraduationCap className="h-6 w-6" />}
          title="Create your first exam plan"
          description="Name an exam or certification, add its topics with a % weightage each, and train it with your materials."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {exams.map((exam) => (
            <Link key={exam.id} href={`/exams/${exam.id}`} className="card group relative overflow-hidden p-5 transition-all hover:-translate-y-0.5 hover:border-violet-400/30">
              <div className="absolute inset-x-0 top-0 h-1" style={{ background: exam.color }} />
              <div className="flex items-start justify-between">
                <h3 className="font-semibold leading-snug">{exam.title}</h3>
                <ArrowRight className="h-4 w-4 shrink-0 text-foreground/30 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground/70" />
              </div>
              {exam.description && <p className="mt-1 line-clamp-2 text-sm text-foreground/55">{exam.description}</p>}

              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-white/4 py-2">
                  <div className="text-lg font-bold">{exam.topicCount}</div>
                  <div className="text-[10px] uppercase tracking-wider text-foreground/50">topics</div>
                </div>
                <div className="rounded-lg bg-white/4 py-2">
                  <div className="text-lg font-bold">{exam.questionCount}</div>
                  <div className="text-[10px] uppercase tracking-wider text-foreground/50">questions</div>
                </div>
                <div className="rounded-lg bg-white/4 py-2">
                  <div className="text-lg font-bold">{exam.materialCount}</div>
                  <div className="text-[10px] uppercase tracking-wider text-foreground/50">sources</div>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                {exam.targetDate && (
                  <Badge color="slate">
                    <CalendarDays className="h-3 w-3" />
                    {formatDate(exam.targetDate)}
                  </Badge>
                )}
                {exam.totalWeightage > 0 && (
                  <Badge color={exam.totalWeightage === 100 ? "emerald" : "amber"}>
                    {exam.totalWeightage}% weight
                    {exam.totalWeightage !== 100 && <CircleHelp className="h-3 w-3" />}
                  </Badge>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}

      <Card className="border-dashed text-sm text-foreground/55">
        <strong className="text-foreground/80">Tip:</strong> weightages should total 100%. Mock exams distribute questions
        by those weights so they feel like the real thing — and the report shows exactly which topics you lost marks in.
      </Card>
    </div>
  );
}