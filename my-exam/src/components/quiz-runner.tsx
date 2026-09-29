"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronLeft, ChevronRight, Lightbulb, Loader2, Send, Timer, X } from "lucide-react";
import { Button, Badge, ErrorText } from "@/components/ui";
import { Progress } from "@/components/ui";
import { QuestionPrompt } from "@/components/question-prompt";
import { cn } from "@/lib/utils";
import { checkAnswer, submitQuiz, submitMock } from "@/lib/actions";
import type { AnswerCheck, SubmittedAnswer } from "@/lib/actions";
import type { QuizQuestion } from "@/lib/data";

export function QuizRunner({
  sessionId,
  questions,
  mode,
  title,
  allowShort,
  timerSeconds,
}: {
  sessionId: string;
  questions: QuizQuestion[];
  mode: "quiz" | "mock";
  title: string;
  allowShort: boolean;
  timerSeconds?: number | null;
}) {
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, SubmittedAnswer>>({});
  const [submitting, setSubmitting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(timerSeconds ?? null);
  const [checked, setChecked] = useState<Record<string, AnswerCheck>>({});
  const [checking, setChecking] = useState<string | null>(null);
  const [checkErr, setCheckErr] = useState<string | null>(null);

  const answered = Object.keys(answers).length;
  const checkedCount = Object.keys(checked).length;

  const submit = useCallback(async () => {
    if (submitting) return;
    setSubmitting(true);
    const action = mode === "mock" ? submitMock : submitQuiz;
    const res = await action(sessionId, Object.values(answers));
    if (res.ok && res.id) {
      router.push(mode === "mock" ? `/mock/${res.id}/result` : `/quiz/${res.id}/result`);
    }
  }, [answers, mode, sessionId, submitting, router]);

  useEffect(() => {
    if (!remaining) return;
    const id = setInterval(() => {
      setRemaining((r) => {
        if (r === null || r <= 0) {
          clearInterval(id);
          if (r === 0) submit();
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [remaining, submit]);

  const q = questions[index];

  const setAnswer = (a: SubmittedAnswer) => {
    setAnswers((prev) => ({ ...prev, [q.id]: a }));
  };

  const check = async (pickedOverride?: string | number) => {
    if (!q || checking || checked[q.id]) return;
    const picked = pickedOverride !== undefined ? pickedOverride : answers[q.id]?.chosen;
    if (picked === undefined || picked === null) return;
    setChecking(q.id);
    setCheckErr(null);
    const res = await checkAnswer(sessionId, q.id, picked);
    setChecking(null);
    if (!res.ok) {
      setCheckErr(res.error);
      return;
    }
    setChecked((prev) => ({ ...prev, [q.id]: res.data as AnswerCheck }));
  };

  /** Selecting only records the pick - the answer stays hidden until Confirm is pressed. */
  const choose = (chosen: string | number) => {
    if (!q) return;
    setAnswer({ questionId: q.id, chosen });
  };

  const goTo = (i: number) => {
    setIndex(i);
    setCheckErr(null);
  };

  const result = q ? checked[q.id] : undefined;
  const isChecked = Boolean(result);
  const currentChoice = q ? answers[q.id]?.chosen : undefined;
  const hasChoice = currentChoice !== undefined && currentChoice !== null;
  const checkable = q?.type === "mcq" || q?.type === "true_false";

  const fmtTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold">{title}</h1>
          <div className="text-xs text-foreground/55">
            {questions.length} question{questions.length === 1 ? "" : "s"} · {answered}/{questions.length} answered
            {checkedCount > 0 && ` · ${checkedCount} checked`}
          </div>
        </div>
        {remaining !== null && (
          <div className={`flex shrink-0 items-center gap-1.5 rounded-xl border px-3 py-1.5 text-sm font-bold tabular-nums ${
            remaining < 60 ? "border-rose-400/40 bg-rose-500/10 text-rose-300" : "border-white/10 bg-white/5 text-foreground/80"
          }`}>
            <Timer className="h-4 w-4" /> {fmtTime(remaining)}
          </div>
        )}
      </div>

      <Progress value={(answered / questions.length) * 100} />

      {q && (
        <div className="card space-y-5 p-6" key={q.id}>
          <div className="flex items-center justify-between gap-2 text-xs text-foreground/55">
            <Badge color="slate">
              Question {index + 1} of {questions.length}
            </Badge>
            <span className="tag">{q.type.replace("_", " ")}</span>
          </div>
          <QuestionPrompt text={q.prompt} className="text-lg font-semibold" />

          {q.type === "mcq" && q.choices && (
            <div className="grid gap-2.5">
              {q.choices.map((c, i) => {
                const chosen = answers[q.id]?.chosen === i;
                const isRight = result?.correctIndex === i;
                const isWrongPick = Boolean(result) && chosen && !result?.correct;
                return (
                  <button
                    key={i}
                    onClick={() => choose(i)}
                    disabled={isChecked || checking === q.id}
                    className={cn(
                      "flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-all",
                      isRight
                        ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100"
                        : isWrongPick
                          ? "border-rose-400/60 bg-rose-500/15 text-rose-100"
                          : chosen
                            ? "border-violet-400/60 bg-violet-500/15 text-white shadow-lg shadow-violet-900/20"
                            : "border-white/10 bg-white/4 hover:border-white/25 hover:bg-white/8",
                      isChecked && "cursor-default"
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold",
                        isRight
                          ? "bg-emerald-500 text-white"
                          : isWrongPick
                            ? "bg-rose-500 text-white"
                            : chosen
                              ? "bg-violet-500 text-white"
                              : "bg-white/8 text-foreground/60"
                      )}
                    >
                      {isRight ? (
                        <Check className="h-4 w-4" />
                      ) : isWrongPick ? (
                        <X className="h-4 w-4" />
                      ) : chosen ? (
                        <Check className="h-4 w-4" />
                      ) : (
                        String.fromCharCode(65 + i)
                      )}
                    </span>
                    {c.text}
                  </button>
                );
              })}
            </div>
          )}

          {q.type === "true_false" && (
            <div className="grid grid-cols-2 gap-2.5">
              {["true", "false"].map((val, i) => {
                const chosen = answers[q.id]?.chosen === val;
                const isRight = result?.correctValue === val;
                const isWrongPick = Boolean(result) && chosen && !result?.correct;
                return (
                  <button
                    key={val}
                    onClick={() => choose(val)}
                    disabled={isChecked || checking === q.id}
                    className={cn(
                      "rounded-xl border px-4 py-3 text-sm font-semibold transition-all",
                      isRight
                        ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100"
                        : isWrongPick
                          ? "border-rose-400/60 bg-rose-500/15 text-rose-100"
                          : chosen
                            ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-200"
                            : "border-white/10 bg-white/4 hover:border-white/25 hover:bg-white/8",
                      isChecked && "cursor-default"
                    )}
                  >
                    {i === 0 ? "True" : "False"}
                  </button>
                );
              })}
            </div>
          )}

          {checkable && (
            <div className="space-y-3">
              {!isChecked && (
                <Button onClick={() => void check()} disabled={!hasChoice || checking === q.id} className="w-full sm:w-auto">
                  {checking === q.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  {checking === q.id ? "Checking…" : "Confirm answer"}
                </Button>
              )}
              <ErrorText>{checkErr}</ErrorText>
              {result && (
                <div
                  className={cn(
                    "space-y-2 rounded-xl border px-4 py-3 text-sm",
                    result.correct
                      ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
                      : "border-rose-400/30 bg-rose-500/10 text-rose-200"
                  )}
                >
                  <p className="flex items-center gap-2 font-semibold">
                    {result.correct ? (
                      <>
                        <Check className="h-4 w-4" /> Correct — {result.got}/{result.points} point
                        {result.points === 1 ? "" : "s"}
                      </>
                    ) : (
                      <>
                        <X className="h-4 w-4" /> Incorrect
                        {q.type === "mcq" && result.correctIndex !== null && (
                          <> — the answer is {String.fromCharCode(65 + result.correctIndex)}</>
                        )}
                        {q.type === "true_false" && <> — the answer is {result.correctValue === "true" ? "True" : "False"}</>}
                      </>
                    )}
                  </p>
                  {q.type === "mcq" && result.correctIndex !== null && (
                    <p className="text-foreground/85">
                      <span className="font-semibold">
                        The answer is {String.fromCharCode(65 + result.correctIndex)}:
                      </span>{" "}
                      {q.choices?.[result.correctIndex]?.text}
                    </p>
                  )}
                  {result.explanation && (
                    <p className="flex items-start gap-2 border-t border-white/10 pt-2 text-foreground/70">
                      <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
                      <span className="prose-answer">{result.explanation}</span>
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {q.type === "short" && (
            <div>
              {!allowShort ? (
                <p className="rounded-xl border border-amber-400/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
                  Short-answer is scored by you. Type your answer, then mark it right/wrong on the results page.
                </p>
              ) : null}
              <textarea
                className="input min-h-32"
                placeholder="Write your answer…"
                value={typeof answers[q.id]?.text === "string" ? (answers[q.id]?.text as string) : ""}
                onChange={(e) => setAnswer({ questionId: q.id, text: e.target.value })}
              />
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <Button variant="secondary" onClick={() => goTo(Math.max(0, index - 1))} disabled={index === 0}>
          <ChevronLeft className="h-4 w-4" /> Previous
        </Button>
        <div className="flex flex-wrap justify-center gap-1.5">
          {questions.map((question, i) => {
            const res = checked[question.id];
            return (
              <button
                key={i}
                onClick={() => goTo(i)}
                title={
                  res
                    ? `Checked — ${res.correct ? "correct" : "incorrect"}`
                    : answers[question.id]
                      ? "Answered"
                      : "Not answered"
                }
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-lg text-xs font-bold transition-colors",
                  i === index
                    ? "bg-violet-500 text-white"
                    : res
                      ? res.correct
                        ? "bg-emerald-500 text-white"
                        : "bg-rose-500/70 text-white"
                      : answers[question.id]
                        ? "bg-emerald-500/25 text-emerald-200"
                        : "bg-white/6 text-foreground/60 hover:bg-white/12"
                )}
              >
                {i + 1}
              </button>
            );
          })}
        </div>
        {index < questions.length - 1 ? (
          <Button onClick={() => goTo(Math.min(questions.length - 1, index + 1))}>
            Next <ChevronRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button onClick={() => setConfirmOpen(true)} disabled={submitting}>
            <Send className="h-4 w-4" /> {submitting ? "Submitting…" : "Submit"}
          </Button>
        )}
      </div>

      {confirmOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-4">
          <div className="card w-full max-w-sm p-6">
            <h3 className="text-lg font-semibold">Finish {mode === "mock" ? "mock exam" : "quiz"}?</h3>
            <p className="mt-1 text-sm text-foreground/60">
              You answered {answered} of {questions.length} question{questions.length === 1 ? "" : "s"}
              {answered < questions.length ? " — unanswered ones will score 0." : "."}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
                Keep going
              </Button>
              <Button onClick={submit} disabled={submitting}>
                {submitting ? "Submitting…" : "Yes, finish"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}