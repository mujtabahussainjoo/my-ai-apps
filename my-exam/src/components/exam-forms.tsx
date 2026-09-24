"use client";

import { useActionState, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus, Trash2, X, Settings } from "lucide-react";
import { Button, ErrorText, Field } from "@/components/ui";
import {
  createExam,
  createTopic,
  updateTopic,
  deleteExam,
  deleteTopic,
} from "@/lib/actions";
import type { ActionResult } from "@/lib/actions";

const COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
  "#06b6d4", "#f43f5e", "#84cc16", "#3b82f6", "#eab308",
];

export function CreateExamForm() {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionResult, FormData>(createExam, {} as ActionResult);
  const [color, setColor] = useState("#6366f1");
  const [open, setOpen] = useState(false);

  if (state && "ok" in state && state.ok && state.id && typeof window !== "undefined") {
    router.push(`/exams/${state.id}`);
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} className="px-5 py-3">
        <Plus className="h-4 w-4" /> New exam plan
      </Button>
    );
  }

  return (
    <form action={action} className="card overflow-hidden border-violet-400/25">
      <div className="flex items-center justify-between border-b border-white/8 bg-white/4 px-5 py-3">
        <span className="text-sm font-semibold">Create exam plan</span>
        <button type="button" onClick={() => setOpen(false)} className="rounded-lg p-1 text-foreground/60 hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-4 p-5">
        <Field label="Exam / certification name">
          <input name="title" className="input" placeholder="e.g. AWS Solutions Architect" required />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Target date" className="sm:col-span-1">
            <input name="targetDate" type="date" className="input" />
          </Field>
          <Field label="Accent colour">
            <div className="flex flex-wrap gap-2">
              {COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className="h-7 w-7 rounded-full transition-transform"
                  style={{
                    background: c,
                    outline: color === c ? "2px solid white" : "none",
                    outlineOffset: "2px",
                  }}
                />
              ))}
              <input type="hidden" name="color" value={color} />
            </div>
          </Field>
        </div>
        <Field label="Description (optional)">
          <textarea name="description" className="input" rows={2} placeholder="What does this certification cover?" />
        </Field>
        <ErrorText>{state && "error" in state ? state.error : ""}</ErrorText>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={pending}>
            {pending && <Loader2 className="h-4 w-4 animate-spin" />}
            Create plan
          </Button>
        </div>
      </div>
    </form>
  );
}

export function DeleteExamButton({ examId }: { examId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="danger"
      className="gap-1.5"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Delete this exam plan and all its topics, questions and mocks?")) return;
        setBusy(true);
        const res = await deleteExam(examId);
        if (res.ok) router.push("/exams");
      }}
    >
      <Trash2 className="h-4 w-4" /> Delete plan
    </Button>
  );
}

export function AddTopicForm({ examId, onDone }: { examId: string; onDone: () => void }) {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionResult, FormData>(createTopic, {} as ActionResult);
  const [open, setOpen] = useState(false);

  if (state && "ok" in state && state.ok) {
    router.refresh();
    onDone();
  }

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} className="w-full">
        <Plus className="h-4 w-4" /> Add topic
      </Button>
    );
  }

  return (
    <form action={action} className="card space-y-3 border-violet-400/25 p-4">
      <input type="hidden" name="examId" value={examId} />
      <input type="hidden" name="description" value="" />
      <Field label="Topic name">
        <input name="name" className="input" placeholder="e.g. Networking & Content Delivery" required />
      </Field>
      <Field label="Weightage (%)">
        <input name="weightage" type="number" min={0} max={100} defaultValue={10} className="input" />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending && <Loader2 className="h-4 w-4 animate-spin" />} Add
        </Button>
      </div>
      <ErrorText>{state && "error" in state ? state.error : ""}</ErrorText>
    </form>
  );
}

export function EditTopicRow({
  id,
  examId,
  name,
  weightage,
  description,
}: {
  id: string;
  examId: string;
  name: string;
  weightage: number;
  description: string | null;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [state, action, pending] = useActionState<ActionResult, FormData>(updateTopic, {} as ActionResult);

  if (state && "ok" in state && state.ok) {
    setEditing(false);
    router.refresh();
  }

  return (
    <div className="rounded-xl border border-white/8 bg-white/3 px-4 py-3">
      {editing ? (
        <form action={action} className="space-y-3">
          <input type="hidden" name="id" value={id} />
          <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
            <div>
              <label className="label">Name</label>
              <input name="name" className="input" defaultValue={name} required />
            </div>
            <div>
              <label className="label">Weightage %</label>
              <input name="weightage" type="number" min={0} max={100} className="input" defaultValue={weightage} />
            </div>
          </div>
          {description !== null && (
            <input type="hidden" name="description" value={description} />
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending && <Loader2 className="h-4 w-4 animate-spin" />} Save
            </Button>
          </div>
          <ErrorText>{state && "error" in state ? state.error : ""}</ErrorText>
        </form>
      ) : (
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">{name}</div>
            {description && <div className="truncate text-xs text-foreground/50">{description}</div>}
          </div>
          <div className="w-24">
            <ProgressValue value={weightage} />
          </div>
          <button className="rounded-lg p-2 text-foreground/50 hover:bg-white/8 hover:text-foreground" onClick={() => setEditing(true)}>
            <Settings className="h-4 w-4" />
          </button>
          <DeleteTopicButton topicId={id} examId={examId} />
        </div>
      )}
    </div>
  );
}

function ProgressValue({ value }: { value: number }) {
  return (
    <div className="text-right">
      <div className="text-sm font-bold tabular-nums">{value}%</div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-fuchsia-400" style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  );
}

function DeleteTopicButton({ topicId }: { topicId: string; examId?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="rounded-lg p-2 text-foreground/50 hover:bg-rose-500/10 hover:text-rose-400"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Delete this topic?")) return;
        setBusy(true);
        await deleteTopic(topicId);
        router.refresh();
      }}
    >
      <Trash2 className="h-4 w-4" />
    </button>
  );
}