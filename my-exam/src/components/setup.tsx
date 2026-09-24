"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Zap, Trophy } from "lucide-react";
import { Button, Field, ErrorText } from "@/components/ui";
import { createQuiz, createMock } from "@/lib/actions";

export function QuizSetup({
  exams,
  defaultCount = 10,
}: {
  exams: { id: string; title: string; topicCount: number }[];
  defaultCount?: number;
}) {
  const router = useRouter();
  const [examId, setExamId] = useState("");
  const [count, setCount] = useState(defaultCount);
  const [types, setTypes] = useState<string[]>(["mcq", "true_false"]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggle = (t: string) =>
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const start = async () => {
    setBusy(true);
    setErr(null);
    const res = await createQuiz({ examId: examId || null, topicId: null, mode: "quiz", count, types });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    router.push(`/quiz/${res.id}`);
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        start();
      }}
      className="card space-y-4 p-5"
    >
      <h3 className="flex items-center gap-2 font-semibold">
        <Zap className="h-4 w-4 text-violet-300" /> New practice quiz
      </h3>

      <Field label="Exam">
        <select className="input" value={examId} onChange={(e) => setExamId(e.target.value)}>
          <option value="">Any / all exams</option>
          {exams.map((e) => (
            <option key={e.id} value={e.id}>
              {e.title}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Number of questions">
        <input type="number" min={1} max={50} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
      </Field>

      <div className="space-y-2">
        <span className="label">Question types</span>
        <div className="flex flex-wrap gap-2">
          {[
            ["mcq", "Multiple choice"],
            ["true_false", "True / false"],
            ["short", "Short answer"],
          ].map(([val, label]) => {
            const on = types.includes(val);
            return (
              <button
                key={val}
                type="button"
                onClick={() => toggle(val)}
                className={`tag px-3 py-1.5 text-xs font-semibold ${
                  on ? "border-violet-400/50 bg-violet-500/15 text-violet-200" : ""
                }`}
              >
                {on ? "✓ " : ""}
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <ErrorText>{err}</ErrorText>

      <Button type="submit" disabled={busy || types.length === 0} className="w-full">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
        Start quiz
      </Button>
    </form>
  );
}

export function MockSetup({
  exams,
  defaultCount = 20,
}: {
  exams: { id: string; title: string; topicCount: number }[];
  defaultCount?: number;
}) {
  const router = useRouter();
  const [examId, setExamId] = useState("");
  const [count, setCount] = useState(defaultCount);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState(false);

  const start = async () => {
    setBusy(true);
    setErr(null);
    setNotice(false);
    if (!examId) {
      setErr("Pick an exam to build a weighted mock for it.");
      setBusy(false);
      return;
    }
    const res = await createMock({ examId, count });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    const data = res as { data?: { aiAdded?: number } };
    if (data.data?.aiAdded) setNotice(true);
    router.push(`/mock/${res.id}`);
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        start();
      }}
      className="card space-y-4 p-5"
    >
      <h3 className="flex items-center gap-2 font-semibold">
        <Trophy className="h-4 w-4 text-sky-300" /> Build a weighted mock exam
      </h3>
      <p className="text-xs text-foreground/55">
        Questions are drawn from your bank in proportion to each topic&apos;s weightage — like the real paper.
      </p>

      <Field label="Exam">
        <select className="input" value={examId} onChange={(e) => setExamId(e.target.value)}>
          <option value="">Choose an exam…</option>
          {exams.map((e) => (
            <option key={e.id} value={e.id} disabled={e.topicCount === 0}>
              {e.title}
              {e.topicCount === 0 ? " (add topics first)" : ""}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Number of questions">
        <input type="number" min={5} max={50} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
      </Field>

      <ErrorText>{err}</ErrorText>
      {notice && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">Some questions were AI-generated to fill your mock.</div>}

      <Button type="submit" disabled={busy} variant="secondary" className="w-full !border-sky-400/40 !bg-sky-500/10 text-sky-200 hover:!bg-sky-500/20">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trophy className="h-4 w-4" />}
        Generate mock exam
      </Button>
    </form>
  );
}