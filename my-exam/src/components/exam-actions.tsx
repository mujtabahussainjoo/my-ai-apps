"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Wand2, Link2, Zap, Loader2, Layers } from "lucide-react";
import { Button, Field } from "@/components/ui";
import {
  generateQuestions,
  generateFlashcards,
  createMock,
  createQuiz,
} from "@/lib/actions";

export function ExamAIzAction({ examId }: { examId: string }) {
  const router = useRouter();
  const [type, setType] = useState("mcq");
  const [count, setCount] = useState(8);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const res = await generateQuestions({ examId, topicIds: [], type, count });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    const created = (res as { data?: { created?: number } }).data?.created ?? 0;
    setMsg(`Generated ${created} ${type} question${created === 1 ? "" : "s"}.`);
    router.refresh();
  };

  const flashcards = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const res = await generateFlashcards({ examId, topicIds: [], count });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    const created = (res as { data?: { created?: number } }).data?.created ?? 0;
    setMsg(`Generated ${created} flashcards.`);
    router.refresh();
  };

  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-center gap-2">
        <Wand2 className="h-4 w-4 text-violet-300" />
        <h3 className="font-semibold">Generate with AI</h3>
      </div>
      <p className="text-xs text-foreground/55">
        PrepDesk writes questions from your training materials (RAG), so everything is grounded in what you uploaded.
      </p>

      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr]">
        <Field label="Type">
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="mcq">Multiple choice</option>
            <option value="true_false">True / false</option>
            <option value="short">Short answer</option>
          </select>
        </Field>
        <Field label="Count">
          <input type="number" min={1} max={20} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
        </Field>
        <div className="flex items-end gap-2">
          <Button onClick={run} disabled={busy} className="flex-1">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
            Generate
          </Button>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-white/8 pt-3">
        <span className="text-xs text-foreground/55">Or build a deck of memory cards:</span>
        <Button variant="secondary" disabled={busy} onClick={flashcards}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Layers className="h-4 w-4" />}
          Flashcards
        </Button>
      </div>

      {msg && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
      {err && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}
    </div>
  );
}

export function ExamTestActions({ examId }: { examId: string }) {
  const router = useRouter();
  const [mockCount, setMockCount] = useState(20);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const startMock = async () => {
    setBusy(true);
    setErr(null);
    const res = await createMock({ examId, count: mockCount });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    router.push(`/mock/${res.id}`);
  };

  const startQuiz = async () => {
    setBusy(true);
    setErr(null);
    const res = await createQuiz({ examId, topicId: null, mode: "quiz", count: 10 });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    router.push(`/quiz/${res.id}`);
  };

  return (
    <div className="card flex flex-wrap items-end gap-3 p-5">
      <div className="flex items-end gap-3">
        <div className="w-24">
          <Field label="Mock length">
            <input type="number" min={5} max={50} className="input" value={mockCount} onChange={(e) => setMockCount(Number(e.target.value))} />
          </Field>
        </div>
        <Button onClick={startMock} disabled={busy} variant="secondary">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
          Start mock (weighted)
        </Button>
      </div>
      <div className="flex-1" />
      <Button onClick={startQuiz} disabled={busy}>
        <Zap className="h-4 w-4" /> 10-question practice
      </Button>
      {err && <div className="w-full rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}
    </div>
  );
}