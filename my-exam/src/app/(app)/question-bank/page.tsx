import Link from "next/link";
import { redirect } from "next/navigation";
import { ChevronLeft, ChevronRight, ListChecks, NotebookPen, User, X } from "lucide-react";
import { getCurrentUser, isAdmin } from "@/lib/auth";
import {
  countQuestions,
  GENERAL_EXAM,
  listExams,
  listKnowledgeBases,
  listMaterials,
  listQuestions,
  listTopics,
  listTopicTree,
} from "@/lib/data";
import { Badge, Card, EmptyState } from "@/components/ui";
import { DeleteQuestionButton, GenerateQuestionsPanel, ManualQuestionForm } from "@/components/question-forms";
import { QuestionTopicSelect } from "@/components/question-topic-select";
import { QuestionBankFilters } from "@/components/question-bank-filters";
import { BankPractice } from "@/components/bank-practice";
import { QuestionPrompt } from "@/components/question-prompt";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

const TYPE_COLORS: Record<string, "violet" | "sky" | "amber" | "rose"> = {
  mcq: "violet",
  true_false: "sky",
  short: "amber",
  interview: "rose",
};

const QUESTION_TYPES = [
  { value: "mcq", label: "MCQ" },
  { value: "true_false", label: "True / False" },
  { value: "short", label: "Short answer" },
  { value: "interview", label: "Interview" },
];

const PAGE_SIZE = 20;
const PRACTICE_CAP = 400;

export default async function QuestionBankPage({
  searchParams,
}: {
  searchParams: Promise<{ exam?: string; type?: string; q?: string; topic?: string; mode?: string; page?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const sp = await searchParams;
  const practice = sp.mode === "practice";
  const requestedPage = Math.max(1, Number(sp.page) || 1);
  const exams = await listExams();
  const filterExam =
    sp.exam === GENERAL_EXAM || (sp.exam && exams.some((e) => e.id === sp.exam)) ? sp.exam : undefined;
  const activeExam =
    sp.exam === GENERAL_EXAM ? "" : sp.exam && exams.some((e) => e.id === sp.exam) ? sp.exam : exams[0]?.id ?? "";

  const topics = activeExam ? await listTopics(activeExam) : [];
  const topicsByExam = Object.fromEntries(
    await Promise.all(exams.map(async (e) => [e.id, await listTopics(e.id)]))
  );
  const topicTree = activeExam ? await listTopicTree(activeExam) : [];
  const activeTopic = topics.some((t) => t.id === sp.topic) ? sp.topic : undefined;

  const filters = {
    examId: filterExam,
    topicId: activeTopic,
    type: sp.type || undefined,
    q: sp.q || undefined,
  };

  const total = practice ? 0 : await countQuestions(filters);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(requestedPage, totalPages);

  const questions = practice
    ? await listQuestions({ ...filters, limit: PRACTICE_CAP })
    : await listQuestions({ ...filters, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });

  const typeBadge = (t: string) => TYPE_COLORS[t] ?? "slate";

  // Keeps the active exam/topic/type/search filters when switching modes.
  // Filter changes always reset pagination back to page 1.
  const href = (patch: Record<string, string | undefined>) => {
    const merged = { exam: sp.exam, topic: sp.topic, type: sp.type, q: sp.q, mode: sp.mode, ...patch };
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(merged)) if (v) params.set(k, v);
    const qs = params.toString();
    return qs ? `/question-bank?${qs}` : "/question-bank";
  };

  // Page navigation link for a specific page, preserving all active filters.
  const pageHref = (p: number) => {
    const merged = { exam: sp.exam, topic: sp.topic, type: sp.type, q: sp.q, mode: sp.mode, page: String(p) };
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(merged)) if (v) params.set(k, v);
    const qs = params.toString();
    return qs ? `/question-bank?${qs}` : "/question-bank";
  };

  const pageNumbers: (number | "…")[] = (() => {
    if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
    const window = new Set<number>([1, totalPages, page - 1, page, page + 1]);
    const sorted = [...window].filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b);
    const out: (number | "…")[] = [];
    let prev = 0;
    for (const p of sorted) {
      if (p - prev > 1) out.push("…");
      out.push(p);
      prev = p;
    }
    return out;
  })();

  const examTitle =
    filterExam === GENERAL_EXAM ? "General knowledge" : exams.find((e) => e.id === filterExam)?.title;
  const typeLabel = QUESTION_TYPES.find((t) => t.value === sp.type)?.label;
  const topicName = topics.find((t) => t.id === activeTopic)?.name;
  const clearAllHref = href({ exam: undefined, topic: undefined, type: undefined, q: undefined });
  const chips = [
    examTitle ? { key: "exam", label: examTitle, href: href({ exam: undefined, topic: undefined }) } : null,
    topicName ? { key: "topic", label: topicName, href: href({ topic: undefined }) } : null,
    typeLabel ? { key: "type", label: typeLabel, href: href({ type: undefined }) } : null,
    sp.q ? { key: "q", label: `"${sp.q}"`, href: href({ q: undefined }) } : null,
  ].filter((c): c is { key: string; label: string; href: string } => c !== null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Question bank</h1>
        <p className="mt-1 text-sm text-foreground/60">
          {isAdmin(user)
            ? "Every user's questions across all exams. Practice quizzes and mocks draw from here, topped up by AI when needed."
            : "Your library of questions across all exams. Practice quizzes and mocks draw from here, topped up by AI when needed."}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
        <div className="space-y-5">
          <GenerateQuestionsPanel
            exams={exams.map((e) => ({ id: e.id, title: e.title }))}
            examId={activeExam}
            knowledgeBases={await listKnowledgeBases()}
            topicsByExam={topicsByExam}
            materials={await listMaterials()}
          />
          <ManualQuestionForm examId={activeExam} exams={exams.map((e) => ({ id: e.id, title: e.title }))} topicsByExam={topicsByExam} />
        </div>

        <div>
          <div className="card mb-4 p-4">
            <QuestionBankFilters
              exams={[{ value: GENERAL_EXAM, label: "General knowledge" }, ...exams.map((e) => ({ value: e.id, label: e.title }))]}
              types={QUESTION_TYPES}
              topics={topics.map((t) => {
                const parent = topics.find((p) => p.id === t.parentId);
                return { value: t.id, label: parent ? `↳ ${t.name}` : t.name };
              })}
              examValue={filterExam ?? ""}
              typeValue={sp.type ?? ""}
              topicValue={activeTopic ?? ""}
              qValue={sp.q ?? ""}
              modeValue={practice ? "practice" : ""}
            />

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-white/8 pt-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {chips.length > 0 ? (
                  <>
                    {chips.map((c) => (
                      <Link
                        key={c.key}
                        href={c.href}
                        className="tag gap-1 bg-violet-500/15 text-violet-200 transition-colors hover:bg-violet-500/25"
                      >
                        {c.label} <X className="h-3 w-3" />
                      </Link>
                    ))}
                    <Link href={clearAllHref} className="text-xs font-medium text-foreground/50 hover:text-foreground">
                      Clear all
                    </Link>
                  </>
                ) : (
                  <span className="text-xs text-foreground/50">
                    {practice ? `Practising ${questions.length} questions` : `Showing all ${total} questions`}
                  </span>
                )}
              </div>

              {questions.length > 0 &&
                (practice ? (
                  <Link href={href({ mode: undefined })} className="btn btn-secondary whitespace-nowrap">
                    <NotebookPen className="h-4 w-4" /> Browse
                  </Link>
                ) : (
                  <Link href={href({ mode: "practice" })} className="btn btn-primary whitespace-nowrap">
                    <ListChecks className="h-4 w-4" /> Practice
                  </Link>
                ))}
            </div>
          </div>

          {practice ? (
            <BankPractice questions={questions} />
          ) : questions.length === 0 ? (
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
                          {q.topicName && (
                            <span className="tag">
                              {q.topicParentName ? `${q.topicParentName} › ` : ""}
                              {q.topicName}
                            </span>
                          )}
                          {isAdmin(user) && q.ownerEmail && (
                            <span className="tag gap-1 text-sky-300">
                              <User className="h-3 w-3" /> {q.ownerEmail}
                            </span>
                          )}
                          <span className="text-[11px] text-foreground/40">{formatDate(q.createdAt)}</span>
                        </div>
                        <QuestionPrompt text={q.prompt} />
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
                      <div className="flex shrink-0 flex-col items-end gap-2">
                        <DeleteQuestionButton id={q.id} />
                        <QuestionTopicSelect questionId={q.id} topics={topicTree} value={q.topicId} />
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}

          {!practice && totalPages > 1 && (
            <nav className="mt-4 flex flex-wrap items-center justify-center gap-1.5" aria-label="Pagination">
              <Link
                href={pageHref(page - 1)}
                className={`btn btn-secondary gap-1 ${page <= 1 ? "pointer-events-none opacity-40" : ""}`}
                aria-disabled={page <= 1}
                scroll={false}
              >
                <ChevronLeft className="h-4 w-4" /> Prev
              </Link>
              {pageNumbers.map((p, i) =>
                p === "…" ? (
                  <span key={`gap-${i}`} className="px-1 text-xs text-foreground/40">
                    …
                  </span>
                ) : (
                  <Link
                    key={p}
                    href={pageHref(p)}
                    scroll={false}
                    aria-current={p === page ? "page" : undefined}
                    className={`tag cursor-pointer ${
                      p === page ? "border-violet-400/40 bg-violet-500/15 text-violet-200" : ""
                    }`}
                  >
                    {p}
                  </Link>
                )
              )}
              <Link
                href={pageHref(page + 1)}
                className={`btn btn-secondary gap-1 ${page >= totalPages ? "pointer-events-none opacity-40" : ""}`}
                aria-disabled={page >= totalPages}
                scroll={false}
              >
                Next <ChevronRight className="h-4 w-4" />
              </Link>
              <span className="ml-2 text-xs text-foreground/45">
                Page {page} of {totalPages} · {total} question{total === 1 ? "" : "s"}
              </span>
            </nav>
          )}
        </div>
      </div>
    </div>
  );
}