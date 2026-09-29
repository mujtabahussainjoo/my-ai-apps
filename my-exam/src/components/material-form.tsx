"use client";

import { useActionState, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, FileText, Link2, AlignLeft, Upload, X, Library, FolderOpen, ChevronDown, ChevronRight } from "lucide-react";
import { Button, Field } from "@/components/ui";
import { addMaterials, createKnowledgeBase } from "@/lib/actions";
import { skipReason } from "@/lib/material-path";
import type { ActionResult } from "@/lib/actions";

type Tab = "text" | "url" | "file";

type Picked = { file: File; path: string };

const MAX_UPLOAD_FILES = 200;
const MAX_UPLOAD_TOTAL_MB = 60;

export function AddMaterial({
  examId,
  knowledgeBases,
  defaultKnowledgeBaseId,
}: {
  examId: string | null;
  knowledgeBases: { id: string; name: string }[];
  defaultKnowledgeBaseId?: string | null;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("text");
  const [state, action, pending] = useActionState<ActionResult, FormData>(addMaterials, {} as ActionResult);
  const [picked, setPicked] = useState<Picked[]>([]);
  const formRef = useRef<HTMLFormElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  // `webkitRelativePath` only exists in the browser, so the folder a file came
  // from has to be captured here and sent as a matching array of paths.
  const onPick = (files: File[]) => {
    setPicked(
      files.map((file) => ({
        file,
        path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
      }))
    );
  };

  const totalMb = (picked.reduce((sum, p) => sum + p.file.size, 0) / 1024 / 1024).toFixed(1);
  const oversize =
    picked.reduce((sum, p) => sum + p.file.size, 0) > MAX_UPLOAD_TOTAL_MB * 1024 * 1024 ||
    picked.length > MAX_UPLOAD_FILES;
  const rootLabel =
    picked.length === 0
      ? ""
      : picked.length === 1
        ? picked[0].path
        : `${picked[0].path.split("/")[0]}/… · ${picked.length} files · ${totalMb}MB`;

  const wasPending = useRef(false);
  useEffect(() => {
    if (pending) {
      wasPending.current = true;
      return;
    }
    if (!wasPending.current) return;
    wasPending.current = false;
    if (state && "ok" in state && state.ok) router.refresh();
  }, [pending, state, router]);

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "text", label: "Paste text", icon: <AlignLeft className="h-3.5 w-3.5" /> },
    { key: "url", label: "Web link", icon: <Link2 className="h-3.5 w-3.5" /> },
    { key: "file", label: "Upload files", icon: <Upload className="h-3.5 w-3.5" /> },
  ];

  // The file inputs hold no `name`, so the picked files have to be attached
  // here together with their folder paths.
  const [submitting, startSubmit] = useTransition();
  const busy = pending || submitting;
  const onSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    if (tab !== "file") return;
    e.preventDefault();
    // The button is disabled in both cases, but never post an empty selection.
    if (picked.length === 0 || oversize) return;
    const form = formRef.current;
    if (!form) return;
    const fd = new FormData(form);
    for (const { file } of picked) {
      fd.append("files", file, file.name);
    }
    fd.set("paths", JSON.stringify(picked.map((p) => p.path)));
    startSubmit(() => {
      action(fd);
    });
  };

  return (
    <form ref={formRef} action={action} onSubmit={onSubmit} className="card space-y-4 p-5">
      <input type="hidden" name="kind" value={tab} />
      <input type="hidden" name="examId" value={examId ?? ""} />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 font-semibold">
          <FileText className="h-4 w-4 text-violet-300" /> Add training material
        </h3>
        <div className="flex rounded-xl border border-white/10 bg-white/4 p-1">
          {tabs.map(({ key, label, icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                tab === key ? "bg-violet-500/20 text-violet-200" : "text-foreground/55 hover:text-foreground"
              }`}
            >
              {icon} {label}
            </button>
          ))}
        </div>
      </div>

      <Field label="Knowledge base (which training does this belong to?)">
        <select name="knowledgeBaseId" className="input" defaultValue={defaultKnowledgeBaseId ?? ""}>
          {knowledgeBases.length === 0 && <option value="">No knowledge base yet — create one first</option>}
          {knowledgeBases.length > 0 && <option value="">None (global prep material)</option>}
          {knowledgeBases.map((kb) => (
            <option key={kb.id} value={kb.id}>
              {kb.name}
            </option>
          ))}
        </select>
      </Field>

      {tab === "url" && (
        <>
          <Field label="Website URL">
            <input name="url" type="url" className="input" placeholder="https://docs.example.com/guide" required />
          </Field>
          <Field label="Title (optional)">
            <input name="title" className="input" placeholder="Defaults to the page title" />
          </Field>
        </>
      )}

      {tab === "file" && (
        <Field label="Documents (.pdf, .txt, .md, .docx) — pick files, or a whole folder">
          <div className="flex flex-col gap-2">
            <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/15 bg-white/3 px-4 py-6 text-center transition-colors hover:border-violet-400/40 hover:bg-violet-500/5">
              <Upload className="h-6 w-6 text-foreground/50" />
              {picked.length === 0 ? (
                <span className="text-sm font-medium">
                  Click to choose files
                  <span className="block text-xs font-normal text-foreground/50">
                    Max 15MB each · up to {MAX_UPLOAD_FILES} files
                  </span>
                </span>
              ) : (
                <span className="max-w-full text-sm font-medium">
                  {picked.length} file{picked.length === 1 ? "" : "s"} ready
                  <span className="block text-xs font-normal text-foreground/50">{rootLabel}</span>
                </span>
              )}
              <input
                type="file"
                multiple
                accept=".pdf,.txt,.md,.markdown,.docx,.csv,.html,.htm,.json"
                className="hidden"
                onChange={(e) => onPick(Array.from(e.target.files ?? []))}
              />
            </label>
            <button
              type="button"
              onClick={() => folderInput.current?.click()}
              className="flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/3 px-4 py-2.5 text-xs font-semibold text-foreground/70 transition-colors hover:border-violet-400/40 hover:text-foreground"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {picked.length === 0 ? "Or upload a whole folder" : "Choose a different folder"}
            </button>
            <input
              ref={folderInput}
              type="file"
              multiple
              {...{ webkitdirectory: "", directory: "" }}
              className="hidden"
              onChange={(e) => onPick(Array.from(e.target.files ?? []))}
            />
            {picked.length > 0 && (
              <ul className="max-h-40 space-y-1 overflow-y-auto rounded-xl border border-white/10 bg-black/20 p-2 text-xs text-foreground/60">
                {picked.map((entry, i) => (
                  <li key={`${entry.path}-${i}`} className="flex items-center gap-2 truncate">
                    {skipReason(entry.path) ? (
                      <span className="text-amber-300/70" title="Will be skipped">
                        {entry.path}
                      </span>
                    ) : (
                      <span className="truncate">{entry.path}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {oversize && (
              <p className="text-xs text-amber-300/80">
                That selection is {totalMb}MB — the limit is {MAX_UPLOAD_TOTAL_MB}MB. Pick fewer or smaller files.
              </p>
            )}
          </div>
        </Field>
      )}

      {tab === "text" && (
        <>
          <Field label="Notes / content">
            <textarea name="text" className="input min-h-40 font-mono text-xs" placeholder="Paste lecture notes, chapters, documentation…" />
          </Field>
          <Field label="Title (optional)">
            <input name="title" className="input" placeholder="e.g. Chapter 1 — Networking basics" />
          </Field>
        </>
      )}

      {state && "error" in state && state.error && (
        <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{state.error}</div>
      )}
      {state && "ok" in state && state.ok && (
        <div className="space-y-2 rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          <div>
            Added {((state.data as { created?: number })?.created ?? 1)} source{(state.data as { created?: number })?.created === 1 ? "" : "s"}.
            {(state.data as { note?: string })?.note ?? ""}
          </div>
          {((state.data as { alreadyThere?: number })?.alreadyThere ?? 0) > 0 && (
            <p className="text-xs text-foreground/55">
              Files already imported were left alone; re-uploading a folder refreshes changed files instead of duplicating them.
            </p>
          )}
          <SkippedFiles skipped={(state.data as { skipped?: string[] })?.skipped ?? []} />
        </div>
      )}

      <div className="flex justify-end">
        <Button type="submit" disabled={busy || (tab === "file" && picked.length === 0) || oversize}>
          {busy ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Reading & indexing…
            </>
          ) : (
            <>
              <Upload className="h-4 w-4" /> Add & index
            </>
          )}
        </Button>
      </div>
      <p className="text-xs text-foreground/50">
        PrepDesk chunks the content and embeds it locally, so AI questions and flashcards stay grounded in your material.
      </p>
    </form>
  );
}

/**
 * Names the exact files that were left out and why. Reporting only a count made
 * "9 skipped" impossible to act on, which is the whole reason this list exists.
 */
function SkippedFiles({ skipped }: { skipped: string[] }) {
  const [open, setOpen] = useState(false);
  if (skipped.length === 0) return null;
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-2 py-1.5 text-xs text-amber-200/90">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 text-left font-semibold"
      >
        {open ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
        {skipped.length} file{skipped.length === 1 ? "" : "s"} not added — click for details
      </button>
      {open && (
        <ul className="mt-1.5 max-h-56 space-y-1 overflow-y-auto pl-4">
          {skipped.map((line, i) => {
            const match = line.match(/^Skipped "(.+)" \((.+)\)$/);
            return (
              <li key={i} className="list-disc break-words text-foreground/70">
                {match ? (
                  <>
                    <span className="font-mono text-[11px] text-foreground/80">{match[1]}</span>
                    <span className="text-foreground/50"> — {match[2]}</span>
                  </>
                ) : (
                  line
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function ExpandableContent({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  if (text.length <= 320) {
    return <p className="prose-answer whitespace-pre-wrap text-xs leading-relaxed text-foreground/60">{text}</p>;
  }
  return (
    <div>
      <p
        className={`prose-answer whitespace-pre-wrap text-xs leading-relaxed text-foreground/60 ${
          open ? "" : "line-clamp-4"
        }`}
      >
        {text}
      </p>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="mt-1.5 text-[11px] font-semibold text-violet-300 transition-colors hover:text-violet-200"
      >
        {open ? "Show less" : `Show full document (${text.length.toLocaleString("en-US")} chars)`}
      </button>
    </div>
  );
}

export function DeleteMaterialButton({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="secondary"
      className="text-foreground/60"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Delete this material?")) return;
        setBusy(true);
        const { deleteMaterial } = await import("@/lib/actions");
        await deleteMaterial(id);
        router.refresh();
      }}
    >
      <X className="h-3.5 w-3.5" /> Remove
    </Button>
  );
}

export function CreateKnowledgeBaseForm() {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionResult, FormData>(createKnowledgeBase, {} as ActionResult);

  const wasPending = useRef(false);
  useEffect(() => {
    if (pending) {
      wasPending.current = true;
      return;
    }
    if (!wasPending.current) return;
    wasPending.current = false;
    if (state && "ok" in state && state.ok) router.refresh();
  }, [pending, state, router]);

  return (
    <form action={action} className="card space-y-3 p-5">
      <h3 className="flex items-center gap-2 font-semibold">
        <Library className="h-4 w-4 text-violet-300" /> New knowledge base
      </h3>
      <p className="text-xs text-foreground/60">
        Give a training a name (e.g. “Leap Year Parser”, “Sales Onboarding”). Every doc you upload below this name becomes
        selectable in the AI generation dropdown.
      </p>
      <Field label="Name">
        <input name="name" className="input" placeholder="e.g. Sales Onboarding 2026" required />
      </Field>
      <Field label="Description (optional)">
        <input name="description" className="input" placeholder="What is this training about?" />
      </Field>
      {state && "error" in state && state.error && (
        <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{state.error}</div>
      )}
      <div className="flex justify-end">
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Library className="h-4 w-4" />} Create
        </Button>
      </div>
    </form>
  );
}

export function DeleteKnowledgeBaseButton({ id, name }: { id: string; name: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="secondary"
      className="px-2.5 py-1 text-xs text-foreground/60"
      disabled={busy}
      onClick={async () => {
        if (!confirm(`Delete "${name}" and all of its materials?`)) return;
        setBusy(true);
        const { deleteKnowledgeBase } = await import("@/lib/actions");
        await deleteKnowledgeBase(id);
        router.refresh();
      }}
    >
      <X className="h-3 w-3" /> Delete
    </Button>
  );
}