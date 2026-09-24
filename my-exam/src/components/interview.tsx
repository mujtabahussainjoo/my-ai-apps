"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Mic, Send, Loader2, Sparkles, ChevronRight, AlertCircle } from "lucide-react";
import { Button, Field, Badge } from "@/components/ui";
import { startInterview, submitInterview } from "@/lib/actions";
import type { QuizQuestion, AnswerEntry, InterviewFeedback } from "@/lib/data";
import { cn } from "@/lib/utils";

export function InterviewSetup({
  exams,
}: {
  exams: { id: string; title: string }[];
}) {
  const router = useRouter();
  const [examId, setExamId] = useState("");
  const [role, setRole] = useState("Software Engineer");
  const [difficulty, setDifficulty] = useState("medium");
  const [count, setCount] = useState(5);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setErr(null);
    const res = await startInterview({
      examId: examId || null,
      role,
      difficulty,
      count,
    });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    router.push(`/interview/${res.id}`);
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
        <Mic className="h-4 w-4 text-rose-300" /> AI mock interview
      </h3>
      <p className="text-xs text-foreground/55">
        The AI asks realistic questions, you answer in writing, then PrepDesk grades every answer with STAR feedback.
      </p>

      <Field label="Role / position">
        <input className="input" value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Data Scientist" required />
      </Field>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Difficulty">
          <select className="input" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
            <option value="entry">Entry</option>
            <option value="medium">Mid-level</option>
            <option value="senior">Senior</option>
          </select>
        </Field>
        <Field label="Questions">
          <input type="number" min={1} max={10} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
        </Field>
        <Field label="Relevant exam">
          <select className="input" value={examId} onChange={(e) => setExamId(e.target.value)}>
            <option value="">None</option>
            {exams.map((e) => (
              <option key={e.id} value={e.id}>
                {e.title}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {err && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      <Button type="submit" disabled={busy} className="w-full">
        {busy ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Preparing your interviewer…
          </>
        ) : (
          <>
            <Sparkles className="h-4 w-4" /> Start interview
          </>
        )}
      </Button>
    </form>
  );
}

export function InterviewRunner({
  sessionId,
  questions,
  title,
}: {
  sessionId: string;
  questions: QuizQuestion[];
  title: string;
}) {
  const router = useRouter();
  const [current, setCurrent] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const q = questions[current];
  const filled = Object.values(answers).filter((a) => a.trim().length > 8).length;

  const submit = async () => {
    setBusy(true);
    const res = await submitInterview(
      sessionId,
      Object.entries(answers).map(([questionId, text]) => ({ questionId, text }))
    );
    if (res.ok) router.push(`/interview/${sessionId}/result`);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">{title}</h1>
          <div className="text-xs text-foreground/55">
            Answer in writing — aim for STAR: Situation, Task, Action, Result.
          </div>
        </div>
        <Badge color="rose">
          {filled}/{questions.length} answered
        </Badge>
      </div>

      {q && (
        <div className="card space-y-4 p-6" key={q.id}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge color="slate">
              Question {current + 1} of {questions.length}
            </Badge>
            {q.category && <Badge color="violet">{q.category}</Badge>}
          </div>
          <p className="text-xl font-semibold leading-relaxed">{q.prompt}</p>
          <textarea
            className="input min-h-44 leading-relaxed"
            placeholder="Type your answer here… (aim for 80–300 words)"
            value={answers[q.id] ?? ""}
            onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
          />
          <div className="flex justify-end">
            <Button onClick={() => setCurrent((i) => Math.min(questions.length - 1, i + 1))} disabled={current === questions.length - 1}>
              Next <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          {!(answers[q.id]?.trim().length > 8) && (
            <p className="text-right text-xs text-amber-300/80">
              Write a real answer to get graded feedback — blank answers are skipped.
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap justify-center gap-1.5">
        {questions.map((_, i) => (
          <button
            key={i}
            onClick={() => setCurrent(i)}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-lg text-xs font-bold",
              i === current ? "bg-rose-500 text-white" : (answers[questions[i].id]?.trim().length ?? 0) > 8 ? "bg-emerald-500/25 text-emerald-200" : "bg-white/6 text-foreground/60"
            )}
          >
            {i + 1}
          </button>
        ))}
      </div>

      <div className="flex justify-end">
        <Button onClick={() => setConfirm(true)} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          Submit & get feedback
        </Button>
      </div>

      {confirm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-4">
          <div className="card w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold">Finish and get AI feedback?</h3>
            <p className="mt-1 text-sm text-foreground/60">
              {filled} of {questions.length} answered. Each answered question gets a letter grade with strengths, weaknesses
              and STAR scoring. (Remember to think of a fitting answer before submitting.)
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirm(false)}>
                Keep writing
              </Button>
              <Button onClick={submit} disabled={busy}>
                {busy ? "Grading your answers…" : "Yes, grade me"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function StarBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="font-medium text-foreground/70">{label}</span>
        <span className="text-foreground/60">{value}/100</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/8">
        <div
          className="h-full rounded-full bg-gradient-to-r from-rose-400 to-violet-400 transition-all"
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

export function FeedbackCard({ question, answer }: { question: QuizQuestion; answer: AnswerEntry }) {
  const fb: InterviewFeedback | null = answer.feedback ?? null;
  return (
    <div className="card p-5">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge color={fb?.score && fb.score >= 80 ? "emerald" : fb?.score && fb.score >= 60 ? "amber" : "rose"}>
          {fb?.score ? `${fb.score}/100` : "No grade"}
        </Badge>
        {q_category(question)}
      </div>
      <p className="text-base font-semibold leading-relaxed">{question.prompt}</p>

      <div className="mt-3 space-y-2">
        <div className="rounded-lg bg-black/25 px-3 py-2 text-sm">
          <span className="font-semibold text-foreground/60">Your answer: </span>
          <span className="prose-answer text-foreground/85">{answer.text || "(no answer given)"}</span>
        </div>

        {fb && (
          <>
            <div className="mt-2 grid gap-3 rounded-xl bg-white/4 p-3 sm:grid-cols-2">
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-foreground/55">Strengths</span>
                <ul className="mt-1.5 space-y-1.5 text-sm">
                  {(fb.strengths ?? []).map((s, i) => (
                    <li key={i} className="flex gap-1.5 text-emerald-300">
                      <span>+</span> {s}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <span className="text-xs font-bold uppercase tracking-wider text-foreground/55">To improve</span>
                <ul className="mt-1.5 space-y-1.5 text-sm">
                  {(fb.weaknesses ?? []).map((s, i) => (
                    <li key={i} className="flex gap-1.5 text-rose-300">
                      <span>−</span> {s}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="grid gap-2.5 rounded-xl bg-white/4 p-3">
              <StarBar label="Situation" value={fb.starScore?.situation ?? 0} />
              <StarBar label="Task" value={fb.starScore?.task ?? 0} />
              <StarBar label="Action" value={fb.starScore?.action ?? 0} />
              <StarBar label="Result" value={fb.starScore?.result ?? 0} />
            </div>

            {fb.verdict && (
              <p className="rounded-lg border border-violet-400/20 bg-violet-500/8 px-3 py-2 text-sm leading-relaxed text-violet-200">
                <span className="font-semibold">Verdict: </span>
                {fb.verdict}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function q_category(question: QuizQuestion) {
  return question.category ? <Badge color="slate">{question.category}</Badge> : <Badge color="slate">interview</Badge>;
}