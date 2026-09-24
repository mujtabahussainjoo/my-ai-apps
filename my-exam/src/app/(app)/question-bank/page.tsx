import Link from "next/link";
import { redirect } from "next/navigation";
import { NotebookPen, Search } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams, listTopics, listQuestions } from "@/lib/data";
import { Card, Badge, EmptyState } from "@/components/ui";
import { GenerateQuestionsPanel, ManualQuestionForm, DeleteQuestionButton } from "@/components/question-forms";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

const TYPE_COLORS: Record<string, "violet" | "sky" | "amber" | "rose"> = {
  mcq: "violet",
  true_false: "sky",
  short: "amber",
  interview: "rose",
};

export default async function QuestionBankPage({
  searchParams,
}: {
  searchParams: Promise<{ exam?: string; type?: string; q?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const sp = await searchParams;
  const exams = await listExams();
  const activeExam = sp.exam && exams.some((e) => e.id === sp.exam) ? sp.exam : exams[0]?.id ?? "";

  const topics = activeExam ? await listTopics(activeExam) : [];
  const questions = await listQuestions({
    examId: sp.exam || undefined,
    type: sp.type || undefined,
    q: sp.q || undefined,
    limit: 400,
  });

  const typeBadge = (t: string) => TYPE_COLORS[t] ?? "slate";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Question bank</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Your library of questions across all exams. Practice quizzes and mocks draw from here, topped up by AI when needed.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <div className="space-y-5">
          <GenerateQuestionsPanel exams={exams.map((e) => ({ id: e.id, title: e.title }))} examId={activeExam} />
          <ManualQuestionForm examId={activeExam} topics={topics} />
        </div>

        <div>
          <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap gap-2">
              <Link
                href="/question-bank"
                className={`tag ${!sp.exam ? "border-violet-400/40 text-violet-200" : ""}`}
              >
                All
              </Link>
              {exams.map((e) => (
                <Link
                  key={e.id}
                  href={`/question-bank?exam=${e.id}`}
                  className={`tag ${sp.exam === e.id ? "border-violet-400/40 text-violet-200" : ""}`}
                >
                  {e.title}
                </Link>
              ))}
            </div>
            <form action="/question-bank" method="GET" className="relative sm:w-64">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground/40" />
              <input name="q" className="input pl-9" placeholder="Search questions…" defaultValue={sp.q ?? ""} />
              {sp.exam && <input type="hidden" name="exam" value={sp.exam} />}
            </form>
          </div>

          {questions.length === 0 ? (
            <EmptyState
              icon={<NotebookPen className="h-6 w-6" />}
              title="No questions here"
              description="Use AI generation to build a question bank from your materials, or add questions by hand."
            />
          ) : (
            <div className="space-y-3">
              {questions.map((q) => {
                return (
                  <Card key={q.id} className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="mb-2 flex flex-wrap items-center gap-1.5">
                          <Badge color={typeBadge(q.type)}>{q.type.replace("_", " ")}</Badge>
                          <Badge color={q.source === "ai" ? "emerald" : "slate"}>{q.source}</Badge>
                          {q.examTitle && <Badge color="slate">{q.examTitle}</Badge>}
                          {q.topicName && <span className="tag">{q.topicName}</span>}
                          <span className="text-[11px] text-foreground/40">{formatDate(q.createdAt)}</span>
                        </div>
                        <p className="prose-answer font-medium leading-relaxed">{q.prompt}</p>
                        {q.choices && (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {q.choices.map((c, i) => (
                              <span
                                key={i}
                                className={`tag text-xs ${c.correct ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-300" : ""}`}
                              >
                                {String.fromCharCode(65 + i)}. {c.text}
                              </span>
                            ))}
                          </div>
                        )}
                        {q.answer && q.type !== "mcq" && (
                          <p className="mt-2 rounded-lg bg-black/25 px-3 py-2 text-sm text-foreground/70">
                            <span className="font-semibold text-emerald-300">Answer: </span>
                            {q.answer}
                          </p>
                        )}
                        {q.explanation && (
                          <p className="mt-2 text-sm text-foreground/55">
                            <span className="font-semibold">Why: </span>
                            {q.explanation}
                          </p>
                        )}
                      </div>
                      <DeleteQuestionButton id={q.id} />
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}