import { redirect } from "next/navigation";
import { Library, FileText, Link2, AlignLeft } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams, listMaterials } from "@/lib/data";
import { Card, Badge, EmptyState } from "@/components/ui";
import { AddMaterial, DeleteMaterialButton } from "@/components/material-form";
import { timeAgo, truncate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function MaterialsPage({
  searchParams,
}: {
  searchParams: Promise<{ exam?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const { exam } = await searchParams;
  const exams = await listExams();
  const materials = await listMaterials(exam || undefined);

  const examTitle = exams.find((e) => e.id === exam)?.title;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Training materials</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Upload notes, PDFs, docs or weblinks — PrepDesk reads them and uses them as the source of truth for AI generation.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <div className="space-y-4">
          <AddMaterial examId={exam ?? null} />
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">{exam ? `Materials for ${examTitle}` : "All materials"}</h2>
            <span className="text-xs text-foreground/50">{materials.length} source{materials.length === 1 ? "" : "s"}</span>
          </div>

          {materials.length === 0 ? (
            <EmptyState
              icon={<Library className="h-6 w-6" />}
              title="No materials yet"
              description="Train PrepDesk by pasting notes, adding weblinks or uploading PDFs — then generate questions from them."
            />
          ) : (
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
                    <DeleteMaterialButton id={m.id} />
                  </div>
                  {m.source && m.type === "FILE" && <div className="tag w-fit truncate max-w-full">{m.source}</div>}
                  {m.type === "URL" && m.source && (
                    <a href={m.source} target="_blank" rel="noreferrer" className="tag w-fit max-w-full truncate text-sky-300 hover:underline">
                      {truncate(m.source, 50)}
                    </a>
                  )}
                  <div className="rounded-xl border border-white/8 bg-black/20 p-3">
                    <p className="prose-answer line-clamp-4 text-xs leading-relaxed text-foreground/60">{m.content}</p>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}