import { redirect } from "next/navigation";
import Link from "next/link";
import { Library, FileText, Link2, AlignLeft, FolderOpen, User } from "lucide-react";
import { getCurrentUser, isAdmin } from "@/lib/auth";
import { listExams, listTopics, listKnowledgeBases, listMaterials } from "@/lib/data";
import type { MaterialRow } from "@/lib/data";
import { Card, Badge, EmptyState } from "@/components/ui";
import {
  AddMaterial,
  CreateKnowledgeBaseForm,
  DeleteMaterialButton,
  DeleteKnowledgeBaseButton,
  ExpandableContent,
} from "@/components/material-form";
import { GenerateQuestionsPanel } from "@/components/question-forms";
import { timeAgo, truncate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function MaterialsPage({
  searchParams,
}: {
  searchParams: Promise<{ exam?: string; kb?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { exam, kb } = await searchParams;
  const exams = await listExams();
  const knowledgeBases = await listKnowledgeBases();
  const topicsByExam = Object.fromEntries(
    await Promise.all(exams.map(async (e) => [e.id, await listTopics(e.id)]))
  );

  const materials: MaterialRow[] = kb
    ? await listMaterials({ knowledgeBaseId: kb })
    : exam
      ? await listMaterials({ examId: exam })
      : await listMaterials();

  const examTitle = exams.find((e) => e.id === exam)?.title;
  const activeKb = knowledgeBases.find((b) => b.id === kb);

  const materialsByKb = new Map<string, MaterialRow[]>();
  const ungrouped: MaterialRow[] = [];
  for (const m of materials) {
    if (m.knowledgeBaseId) {
      const list = materialsByKb.get(m.knowledgeBaseId) ?? [];
      list.push(m);
      materialsByKb.set(m.knowledgeBaseId, list);
    } else {
      ungrouped.push(m);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Training materials</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Name your training as a <span className="font-medium text-foreground">knowledge base</span>, upload all its docs in
          one go, then pick that name from the dropdown when generating questions or flashcards.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <div className="space-y-4">
          {isAdmin(user) ? (
            <>
              <CreateKnowledgeBaseForm />
              <AddMaterial examId={exam ?? null} knowledgeBases={knowledgeBases} defaultKnowledgeBaseId={activeKb?.id ?? null} />
            </>
          ) : (
            <Card className="border-dashed p-4 text-sm text-foreground/55">
              Read-only. Only admins can create knowledge bases or upload training material — you can read everything
              below and generate practice from it.
            </Card>
          )}
        </div>

        <div>
          <div className="mb-4">
            {isAdmin(user) ? (
              <GenerateQuestionsPanel
                exams={exams}
                examId={exam ?? ""}
                knowledgeBases={knowledgeBases.length > 0 ? knowledgeBases : undefined}
                defaultKnowledgeBaseId={activeKb?.id ?? null}
                topicsByExam={topicsByExam}
                materials={materials}
              />
            ) : null}
          </div>

          {!kb && !exam && (
            <div className="mb-4 flex flex-wrap gap-3">
              {knowledgeBases.length === 0 && (
                <div className="flex w-full items-start gap-2 rounded-xl border border-white/8 bg-white/3 px-4 py-3 text-xs text-foreground/60">
                  <FolderOpen className="mt-0.5 h-4 w-4 shrink-0 text-violet-300" />
                  <span>
                    No knowledge bases yet. Create one on the left (e.g. “Sales Onboarding”), then upload its documents into
                    it — you&apos;ll be able to choose it from a dropdown when generating Q&amp;A.
                  </span>
                </div>
              )}
              {knowledgeBases.map((b) => (
                <div
                  key={b.id}
                  className="flex min-w-56 items-center justify-between gap-3 rounded-xl border border-white/8 bg-white/3 px-4 py-3 transition-colors hover:border-violet-400/40 hover:bg-violet-500/5"
                >
                  <Link href={`/materials?kb=${b.id}`} className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Library className="h-4 w-4 text-violet-300" />
                      <span className="font-semibold">{b.name}</span>
                    </div>
                    {b.description && <p className="mt-0.5 line-clamp-1 text-xs text-foreground/55">{b.description}</p>}
                    <p className="mt-1 text-[11px] text-foreground/45">
                      {b.docCount} doc{b.docCount === 1 ? "" : "s"} · {b.chunkCount} chunks
                    </p>
                  </Link>
                  {isAdmin(user) && <DeleteKnowledgeBaseButton id={b.id} name={b.name} />}
                </div>
              ))}
            </div>
          )}

          {kb && activeKb ? (
            <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-white/8 bg-white/3 px-4 py-3">
              <div>
                <div className="flex items-center gap-2">
                  <Library className="h-4 w-4 text-violet-300" />
                  <span className="font-semibold">{activeKb.name}</span>
                </div>
                <p className="mt-0.5 text-xs text-foreground/55">
                  {activeKb.description ?? "Knowledge base"} · {activeKb.docCount} doc{activeKb.docCount === 1 ? "" : "s"} ·{" "}
                  {activeKb.chunkCount} chunks
                </p>
              </div>
              <div className="flex items-center gap-2">
                {isAdmin(user) && <DeleteKnowledgeBaseButton id={activeKb.id} name={activeKb.name} />}
                <Link href="/materials" className="tag text-foreground/55 hover:text-foreground">
                  Show all
                </Link>
              </div>
            </div>
          ) : exam ? (
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold">{examTitle ? `Materials for ${examTitle}` : "All materials"}</h2>
              <span className="text-xs text-foreground/50">{materials.length} source{materials.length === 1 ? "" : "s"}</span>
            </div>
          ) : null}

          {materials.length === 0 ? (
            <EmptyState
              icon={<Library className="h-6 w-6" />}
              title="No materials yet"
              description="Create a knowledge base, then paste notes, add weblinks or upload a whole folder of PDFs — then generate questions from them."
            />
          ) : kb && activeKb ? (
            <MaterialsGrid materials={materialsByKb.get(activeKb.id) ?? []} showOwner={isAdmin(user)} canEdit={isAdmin(user)} />
          ) : exam ? (
            <MaterialsGrid materials={materials} showOwner={isAdmin(user)} canEdit={isAdmin(user)} />
          ) : (
            <div className="space-y-8">
              {knowledgeBases.map((b) => {
                const list = materialsByKb.get(b.id) ?? [];
                return (
                  <section key={b.id}>
                    <div className="mb-2 flex items-center justify-between">
                      <h2 className="font-semibold">{b.name}</h2>
                      <span className="text-xs text-foreground/50">
                        {list.length} source{list.length === 1 ? "" : "s"}
                      </span>
                    </div>
                    {list.length === 0 ? (
                      <p className="rounded-xl border border-dashed border-white/10 px-4 py-3 text-xs text-foreground/45">
                        No docs in this knowledge base yet — upload them below.
                      </p>
                    ) : (
                      <MaterialsGrid materials={list} showOwner={isAdmin(user)} canEdit={isAdmin(user)} />
                    )}
                  </section>
                );
              })}
              {ungrouped.length > 0 && (
                <section>
                  <div className="mb-2 flex items-center justify-between">
                    <h2 className="font-semibold">Ungrouped</h2>
                    <span className="text-xs text-foreground/50">
                      {ungrouped.length} source{ungrouped.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <MaterialsGrid materials={ungrouped} showOwner={isAdmin(user)} canEdit={isAdmin(user)} />
                </section>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MaterialsGrid({ materials, showOwner = false, canEdit = false }: { materials: MaterialRow[]; showOwner?: boolean; canEdit?: boolean }) {
  if (materials.length === 0) {
    return (
      <EmptyState
        icon={<Library className="h-6 w-6" />}
        title="No materials here yet"
        description="Upload documents into this knowledge base to make them available for AI generation."
      />
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {materials.map((m) => (
        <Card key={m.id} className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h3 className="truncate font-semibold">{m.title}</h3>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge color={m.type === "URL" ? "sky" : m.type === "FILE" ? "amber" : "violet"}>
                  {m.type === "URL" ? <Link2 className="h-3 w-3" /> : m.type === "FILE" ? <FileText className="h-3 w-3" /> : <AlignLeft className="h-3 w-3" />}
                  {m.type}
                </Badge>
                <span className="text-[11px] text-foreground/45">
                  {Number(m.chunkCount)} chunks · {timeAgo(m.createdAt)}
                </span>
              </div>
            </div>
            {canEdit && <DeleteMaterialButton id={m.id} />}
          </div>
          {showOwner && m.ownerEmail && (
                <span className="tag w-fit gap-1 text-sky-300">
                  <User className="h-3 w-3" /> {m.ownerEmail}
                </span>
              )}
              {m.source && m.type === "FILE" && <div className="tag w-fit max-w-full truncate">{m.source}</div>}
          {m.type === "URL" && m.source && (
            <a href={m.source} target="_blank" rel="noreferrer" className="tag w-fit max-w-full truncate text-sky-300 hover:underline">
              {truncate(m.source, 50)}
            </a>
          )}
          <div className="rounded-xl border border-white/8 bg-black/20 p-3">
            <ExpandableContent text={m.content ?? ""} />
          </div>
        </Card>
      ))}
    </div>
  );
}