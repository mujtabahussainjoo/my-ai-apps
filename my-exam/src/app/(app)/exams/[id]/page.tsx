import Link from "next/link";
import { redirect, notFound } from "next/navigation";
import { ArrowLeft, Tags, CircleHelp, CheckCircle2, Upload } from "lucide-react";
import { getCurrentUser, isAdmin } from "@/lib/auth";
import { getExam, listTopicTree, listMaterials, listQuestions, listKnowledgeBases, type TopicNode } from "@/lib/data";
import { getMasteryForExam } from "@/lib/stats";
import { Card, Badge, Progress } from "@/components/ui";
import { WeightagePie, MasteryBars } from "@/components/charts";
import { DeleteExamButton, AddTopicForm, EditTopicRow } from "@/components/exam-forms";
import { ExamAIzAction, ExamTestActions } from "@/components/exam-actions";
import { SyllabusImporter } from "@/components/syllabus-importer";
import { totalAssignedWeight, weightsAreBalanced } from "@/lib/syllabus";
import { colorForIndex, formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function ExamDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const exam = await getExam(id);
  if (!exam) notFound();

  const [tree, materials, questions, mastery, knowledgeBases] = await Promise.all([
    listTopicTree(id),
    listMaterials({ examId: id }),
    listQuestions({ examId: id, limit: 1000 }),
    getMasteryForExam(user.id, id),
    listKnowledgeBases(),
  ]);
  const topics = flattenTree(tree);
  const topLevel = tree;

  // The donut and the total both read from the leaves, because a parent topic is
  // a heading whose value is the sum of its children — charting both would show
  // every domain twice and push the total past 100.
  const leaves = topics.filter((t) => !topics.some((c) => c.parentId === t.id));
  const weightSum = totalAssignedWeight(topics);
  const balanced = weightsAreBalanced(topics);

  const pieData = leaves.map((t, i) => ({ name: t.name, value: t.weightage, color: colorForIndex(i) }));
  const masteryData = mastery.map((m, i) => ({ ...m, color: colorForIndex(i) }));

  const admin = isAdmin(user);

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
              {topics.length === 0 ? (
                <Badge color="sky">
                  <Upload className="h-3 w-3" /> no syllabus yet
                </Badge>
              ) : balanced ? (
                <Badge color="emerald">
                  <CheckCircle2 className="h-3 w-3" /> weights sum to 100%
                </Badge>
              ) : (
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
          {admin ? <DeleteExamButton examId={id} /> : null}
        </div>
      </header>

      <ExamTestActions examId={id} />

      <section className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-4 flex items-center gap-2">
            <Tags className="h-4 w-4 text-violet-300" />
            <h2 className="font-semibold">Topic weightage</h2>
            {topics.length > 0 && (
              <span className="ml-auto text-xs text-foreground/55">{leaves.length} weighted topics</span>
            )}
          </div>
          <WeightagePie data={pieData} />
          {topics.length === 0 ? (
            <p className="mt-3 text-sm text-foreground/55">Add topics below, or import your syllabus to see the weightage breakdown.</p>
          ) : !balanced ? (
            <p className="mt-3 text-sm text-amber-300/85">
              Weightage adds up to {weightSum}%. Rebalance it and mocks will match the real paper more closely.
            </p>
          ) : null}
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
          {admin && (
            <div className="mb-4">
              <AddTopicForm examId={id} topics={topics} />
            </div>
          )}
          <div className="space-y-2">
            {topics.length === 0 && (
              <Card className="border-dashed text-sm text-foreground/55">
                {admin
                  ? "No topics yet. Add a topic like “LLMs”, with subtopics under it like “How LLMs Behave” — give each a % weightage."
                  : "No topics have been added to this exam yet."}
              </Card>
            )}
            <TopicTree nodes={topLevel} examId={id} allTopics={topics} canEdit={admin} />
            {topics.length > 0 && (
              <div className="pt-1">
                <div className="mb-1 flex justify-between text-xs text-foreground/55">
                  <span>Total assigned weight</span>
                  <span className={balanced ? "font-bold text-emerald-400" : "font-bold text-amber-400"}>
                    {weightSum}% / 100%
                  </span>
                </div>
                <Progress value={Math.min(100, weightSum)} color={balanced ? "#10b981" : "#f59e0b"} />
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          {admin && (
            <SyllabusImporter
              examId={id}
              examTitle={exam.title}
              topicCount={topics.length}
              currentTotal={weightSum}
            />
          )}

          {admin ? <ExamAIzAction examId={id} knowledgeBases={knowledgeBases} /> : null}

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

function flattenTree(nodes: TopicNode[]): TopicNode[] {
  const out: TopicNode[] = [];
  for (const n of nodes) {
    out.push(n);
    out.push(...flattenTree(n.children));
  }
  return out;
}

function TopicTree({
  nodes,
  examId,
  allTopics,
  canEdit,
}: {
  nodes: TopicNode[];
  examId: string;
  allTopics: TopicNode[];
  canEdit: boolean;
}) {
  return (
    <>
      {nodes.map((t) => (
        <div key={t.id} className="space-y-2">
          {canEdit ? (
            <EditTopicRow
              id={t.id}
              examId={examId}
              name={t.name}
              weightage={t.weightage}
              description={t.description}
              parentId={t.parentId}
              topics={allTopics}
            />
          ) : (
            <ReadOnlyTopicRow name={t.name} weightage={t.weightage} description={t.description} />
          )}
          {t.children.length > 0 && (
            <div className="ml-6 space-y-2 border-l border-white/10 pl-3">
              {t.children.map((c) => (
                <div key={c.id} className="space-y-2">
                  {canEdit ? (
                    <EditTopicRow
                      id={c.id}
                      examId={examId}
                      name={c.name}
                      weightage={c.weightage}
                      description={c.description}
                      parentId={c.parentId}
                      topics={allTopics}
                    />
                  ) : (
                    <ReadOnlyTopicRow name={c.name} weightage={c.weightage} description={c.description} />
                  )}
                  {c.children.length > 0 && (
                    <div className="ml-6 space-y-2 border-l border-white/10 pl-3">
                      {c.children.map((gc) => (
                        <div key={gc.id}>
                          {canEdit ? (
                            <EditTopicRow
                              key={gc.id}
                              id={gc.id}
                              examId={examId}
                              name={gc.name}
                              weightage={gc.weightage}
                              description={gc.description}
                              parentId={gc.parentId}
                              topics={allTopics}
                            />
                          ) : (
                            <ReadOnlyTopicRow name={gc.name} weightage={gc.weightage} description={gc.description} />
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function ReadOnlyTopicRow({
  name,
  weightage,
  description,
}: {
  name: string;
  weightage: number;
  description: string | null;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-white/8 bg-white/3 px-4 py-3">
      <div className="min-w-0">
        <div className="font-medium">{name}</div>
        {description && <p className="mt-0.5 line-clamp-2 text-xs text-foreground/55">{description}</p>}
      </div>
      <span className="rounded-md bg-violet-500/15 px-2 py-1 text-xs font-bold text-violet-200">{weightage}%</span>
    </div>
  );
}