import Link from "next/link";
import { redirect, notFound } from "next/navigation";
import { ArrowLeft, Tags, CircleHelp } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { getExam, listTopics, listMaterials, listQuestions } from "@/lib/data";
import { getMasteryForExam } from "@/lib/stats";
import { Card, Badge, Progress } from "@/components/ui";
import { WeightagePie, MasteryBars } from "@/components/charts";
import { DeleteExamButton, AddTopicForm, EditTopicRow } from "@/components/exam-forms";
import { ExamAIzAction, ExamTestActions } from "@/components/exam-actions";
import { colorForIndex, formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function ExamDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const exam = await getExam(id);
  if (!exam) notFound();

  const [topics, materials, questions, mastery] = await Promise.all([
    listTopics(id),
    listMaterials(id),
    listQuestions({ examId: id, limit: 1000 }),
    getMasteryForExam(user.id, id),
  ]);

  const pieData = topics.map((t, i) => ({ name: t.name, value: t.weightage, color: colorForIndex(i) }));
  const masteryData = mastery.map((m, i) => ({ ...m, color: colorForIndex(i) }));
  const weightSum = topics.reduce((s, t) => s + t.weightage, 0);

  return (
    <div className="space-y-6">
      <Link href="/exams" className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground/60 hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> All exams
      </Link>

      <header className="card relative overflow-hidden p-6">
        <div className="absolute inset-x-0 top-0 h-1" style={{ background: exam.color }} />
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">{exam.title}</h1>
              {weightSum !== 100 && (
                <Badge color="amber">
                  <CircleHelp className="h-3 w-3" /> weights sum to {weightSum}%
                </Badge>
              )}
            </div>
            {exam.description && <p className="mt-1 text-sm text-foreground/60">{exam.description}</p>}
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-foreground/55">
              {exam.targetDate && <Badge color="slate">Target · {formatDate(exam.targetDate)}</Badge>}
              <Badge color="slate">{topics.length} topics</Badge>
              <Badge color="slate">{questions.length} questions</Badge>
              <Badge color="slate">{materials.length} training sources</Badge>
            </div>
          </div>
          <DeleteExamButton examId={id} />
        </div>
      </header>

      <ExamTestActions examId={id} />

      <section className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Tags className="h-4 w-4 text-violet-300" />
            <h2 className="font-semibold">Topic weightage</h2>
          </div>
          <WeightagePie data={pieData} />
          {topics.length === 0 && (
            <p className="mt-3 text-sm text-foreground/55">Add topics below to see the weightage breakdown.</p>
          )}
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Mastery by topic</h2>
            <Badge color="emerald">From your practice</Badge>
          </div>
          <MasteryBars data={masteryData} />
        </Card>
      </section>

      <section className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div>
          <h2 className="mb-3 text-lg font-semibold">Topics</h2>
          <div className="mb-4">
            <AddTopicForm
              examId={id}
              onDone={() => {
                /* router.refresh runs inside */
              }}
            />
          </div>
          <div className="space-y-2">
            {topics.length === 0 && (
              <Card className="border-dashed text-sm text-foreground/55">
                No topics yet. Add topics like “Networking”, “Security” or “Algorithms” with the % each appears on the exam.
              </Card>
            )}
            {topics.map((t) => (
              <EditTopicRow key={t.id} id={t.id} examId={id} name={t.name} weightage={t.weightage} description={t.description} />
            ))}
            {topics.length > 0 && (
              <div className="pt-1">
                <div className="mb-1 flex justify-between text-xs text-foreground/55">
                  <span>Total assigned weight</span>
                  <span className={weightSum === 100 ? "font-bold text-emerald-400" : "font-bold text-amber-400"}>
                    {weightSum}% / 100%
                  </span>
                </div>
                <Progress value={Math.min(100, weightSum)} color={weightSum === 100 ? "#10b981" : "#f59e0b"} />
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <ExamAIzAction examId={id} />

          <Card>
            <h3 className="mb-3 font-semibold">Your question bank</h3>
            {questions.length === 0 ? (
              <p className="text-sm text-foreground/55">
                Nothing here yet. Generate questions above, or add them manually in{" "}
                <Link href="/question-bank" className="font-medium text-violet-300 hover:text-violet-200">
                  Question Bank
                </Link>
                .
              </p>
            ) : (
              <div className="space-y-2">
                {questions.slice(0, 6).map((q) => (
                  <div key={q.id} className="rounded-xl border border-white/8 bg-white/3 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="badge">{q.type}</span>
                      {q.topicName && <span className="tag">{q.topicName}</span>}
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-sm text-foreground/80">{q.prompt}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </section>
    </div>
  );
}