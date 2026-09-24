"use client";

import { useActionState, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, FileText, Link2, AlignLeft, Upload, X } from "lucide-react";
import { Button, Field } from "@/components/ui";
import { addMaterial } from "@/lib/actions";
import type { ActionResult } from "@/lib/actions";

type Tab = "text" | "url" | "file";

export function AddMaterial({ examId }: { examId: string | null }) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("text");
  const [state, action, pending] = useActionState<ActionResult, FormData>(addMaterial, {} as ActionResult);
  const [fileName, setFileName] = useState<string>("");

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "text", label: "Paste text", icon: <AlignLeft className="h-3.5 w-3.5" /> },
    { key: "url", label: "Web link", icon: <Link2 className="h-3.5 w-3.5" /> },
    { key: "file", label: "Upload file", icon: <Upload className="h-3.5 w-3.5" /> },
  ];

  if (state && "ok" in state && state.ok) {
    router.refresh();
  }

  return (
    <form action={action} className="card space-y-4 p-5">
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
        <Field label="Document (.pdf, .txt, .md, .docx)">
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-white/15 bg-white/3 px-4 py-8 text-center transition-colors hover:border-violet-400/40 hover:bg-violet-500/5">
            <Upload className="h-6 w-6 text-foreground/50" />
            <span className="text-sm font-medium">
              {fileName || "Click to choose a file"}
              <span className="block text-xs font-normal text-foreground/50">Max 15MB · text and PDFs extract best</span>
            </span>
            <input
              type="file"
              name="file"
              accept=".pdf,.txt,.md,.markdown,.docx,.csv,.html"
              className="hidden"
              onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")}
            />
          </label>
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

      <div className="flex justify-end">
        <Button type="submit" disabled={pending || (tab === "file" && !fileName)}>
          {pending ? (
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