"use client";

import { useState } from "react";
import {
  BarChart3,
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  Lightbulb,
  Shuffle,
  X,
} from "lucide-react";
import { Badge, Button, Progress } from "@/components/ui";
import { QuestionPrompt } from "@/components/question-prompt";
import { cn } from "@/lib/utils";
import { correctIndex as findCorrectIndex, isCorrect, trueFalseAnswer } from "@/lib/grade";
import type { QuestionRow } from "@/lib/data";

type Picked = { chosen?: string | number | null; text?: string };

function isObjective(q: QuestionRow) {
  return q.type === "mcq" || q.type === "true_false";
}

function shuffle<T>(items: T[]) {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function BankPractice({ questions }: { questions: QuestionRow[] }) {
  const [order, setOrder] = useState<QuestionRow[]>(questions);
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<Record<string, Picked>>({});
  const [results, setResults] = useState<Record<string, boolean>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [submitted, setSubmitted] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);

  const q = order[index];
  const objectiveTotal = order.filter(isObjective).length;
  const right = Object.values(results).filter(Boolean).length;
  const wrong = Object.keys(results).length - right;

  const wasChecked = (id: string) => results[id] !== undefined;

  // Selecting an option only records the pick. Nothing is revealed until the
  // learner confirms, so the answer can't be read off the screen by accident.
  const pick = (p: Picked) => {
    if (!q || wasChecked(q.id)) return;
    setPicked((prev) => ({ ...prev, [q.id]: { ...prev[q.id], ...p } }));
  };

  const confirmAnswer = () => {
    if (!q || wasChecked(q.id)) return;
    const choice = picked[q.id]?.chosen;
    if (choice === undefined || choice === null) return;
    setResults((prev) => ({ ...prev, [q.id]: isCorrect(q, picked[q.id]) }));
  };

  const goTo = (i: number) => {
    setIndex(Math.max(0, Math.min(order.length - 1, i)));
  };

  const restart = () => {
    setOrder(shuffle(order));
    setPicked({});
    setResults({});
    setRevealed({});
    setIndex(0);
    setSubmitted(false);
    setConfirmSubmit(false);
  };

  if (!q) {
    return (
      <div className="card px-4 py-10 text-center text-sm text-foreground/60">
        Nothing to practise here — add or generate questions first.
      </div>
    );
  }

  const result = results[q.id];
  const isChecked = result !== undefined;
  const hasChoice = picked[q.id]?.chosen !== undefined && picked[q.id]?.chosen !== null;
  const correctIndex = findCorrectIndex(q.choices);
  const correctText = correctIndex >= 0 ? (q.choices?.[correctIndex]?.text ?? null) : null;
  const tfAnswer = trueFalseAnswer(q.choices) ?? true;

  const graded = order.filter((o) => results[o.id] !== undefined);
  const allConfirmed = graded.length === objectiveTotal && objectiveTotal > 0;
  const skipped = objectiveTotal - graded.length;
  const percentage = graded.length ? Math.round((right / graded.length) * 100) : 0;

  /** Submitting is always allowed; unconfirmed questions are just counted as skipped. */
  const requestSubmit = () => {
    if (allConfirmed || objectiveTotal === 0) setSubmitted(true);
    else setConfirmSubmit(true);
  };

  if (submitted) {
    return (
      <div className="space-y-5">
        <div className="card space-y-5 p-6 text-center">
          <p className="text-xs font-semibold tracking-wide text-foreground/55 uppercase">
            Your result
          </p>
          <p
            className={cn(
              "text-5xl font-bold tabular-nums",
              percentage >= 70 ? "text-emerald-300" : percentage >= 40 ? "text-amber-300" : "text-rose-300"
            )}
          >
            {percentage}%
          </p>
          <p className="text-sm text-foreground/60">
            {right} correct of {graded.length} confirmed
            {graded.length < objectiveTotal && ` · ${objectiveTotal - graded.length} left unconfirmed`}
          </p>

          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-emerald-400/25 bg-emerald-500/10 px-3 py-3">
              <p className="text-2xl font-bold text-emerald-300 tabular-nums">{right}</p>
              <p className="text-xs text-foreground/60">Correct</p>
            </div>
            <div className="rounded-xl border border-rose-400/25 bg-rose-500/10 px-3 py-3">
              <p className="text-2xl font-bold text-rose-300 tabular-nums">{wrong}</p>
              <p className="text-xs text-foreground/60">Wrong</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 px-3 py-3">
              <p className="text-2xl font-bold text-foreground/70 tabular-nums">
                {objectiveTotal - graded.length}
              </p>
              <p className="text-xs text-foreground/60">Skipped</p>
            </div>
          </div>

          <div className="flex flex-wrap justify-center gap-2">
            <Button onClick={restart}>
              <Shuffle className="h-4 w-4" /> Practise again
            </Button>
            <Button variant="secondary" onClick={() => setSubmitted(false)}>
              Review questions
            </Button>
          </div>
        </div>

        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Answer review</h3>
          {order.map((o, i) => {
            const wasRight = results[o.id];
            const key = findCorrectIndex(o.choices);
            const answerText = key >= 0 ? (o.choices?.[key]?.text ?? null) : null;
            const pickIdx = picked[o.id]?.chosen;
            const pickText =
              o.type === "true_false"
                ? pickIdx === "true"
                  ? "True"
                  : "False"
                : typeof pickIdx === "number"
                  ? (o.choices?.[pickIdx]?.text ?? null)
                  : null;
            if (!isObjective(o)) return null;
            return (
              <div key={o.id} className="card space-y-2 p-4 text-sm">
                <div className="flex items-start gap-2">
                  <span
                    className={cn(
                      "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-xs font-bold",
                      wasRight === undefined
                        ? "bg-white/8 text-foreground/50"
                        : wasRight
                          ? "bg-emerald-500 text-white"
                          : "bg-rose-500 text-white"
                    )}
                  >
                    {wasRight === undefined ? i + 1 : wasRight ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
                  </span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="font-medium">
                      {i + 1}. {o.prompt}
                    </p>
                    <p className="text-xs text-foreground/60">
                      {wasRight === undefined ? (
                        "Not confirmed"
                      ) : (
                        <>
                          Your answer:{" "}
                          <span className={wasRight ? "text-emerald-300" : "text-rose-300"}>
                            {pickText ?? "(none)"}
                          </span>
                        </>
                      )}
                    </p>
                    {wasRight === false && answerText && (
                      <p className="text-xs text-foreground/60">
                        Correct answer: <span className="text-emerald-300">{answerText}</span>
                      </p>
                    )}
                    {o.explanation && (
                      <p className="flex items-start gap-1.5 border-t border-white/10 pt-1.5 text-xs text-foreground/60">
                        <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                        <span className="prose-answer">{o.explanation}</span>
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="card flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <h2 className="font-bold">Practice mode</h2>
          <p className="text-xs text-foreground/55">
            Pick an option, then confirm it to see the answer and why it is correct. Nothing here
            affects your quiz scores.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-emerald-300">{right} right</span>
          <span className="text-xs font-semibold text-rose-300">{wrong} wrong</span>
          <Button variant="secondary" onClick={restart}>
            <Shuffle className="h-4 w-4" /> Shuffle &amp; restart
          </Button>
        </div>
      </div>

      <Progress value={objectiveTotal ? (Object.keys(results).length / objectiveTotal) * 100 : 0} />

      <div className="card space-y-5 p-6">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-foreground/55">
          <Badge color="slate">
            Question {index + 1} of {order.length}
          </Badge>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="tag">{q.type.replace("_", " ")}</span>
            {q.examTitle && <span className="tag">{q.examTitle}</span>}
            {q.topicName && <span className="tag">{q.topicName}</span>}
          </div>
        </div>

        <QuestionPrompt text={q.prompt} className="text-lg font-semibold" />

        {q.type === "mcq" && q.choices && (
          <div className="grid gap-2.5">
            {q.choices.map((c, i) => {
              const chosen = picked[q.id]?.chosen === i;
              const isRight = isChecked && correctIndex === i;
              const isWrongPick = Boolean(isChecked) && chosen && !result;
              return (
                <button
                  key={i}
                  onClick={() => pick({ chosen: i })}
                  disabled={isChecked}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition-all",
                    isRight
                      ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100"
                      : isWrongPick
                        ? "border-rose-400/60 bg-rose-500/15 text-rose-100"
                        : chosen
                          ? "border-violet-400/60 bg-violet-500/15 text-white"
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
            {(["true", "false"] as const).map((val, i) => {
              const chosen = picked[q.id]?.chosen === val;
              const isRight = isChecked && (val === "true") === tfAnswer;
              const isWrongPick = Boolean(isChecked) && chosen && !result;
              return (
                <button
                  key={val}
                  onClick={() => pick({ chosen: val })}
                  disabled={isChecked}
                  className={cn(
                    "rounded-xl border px-4 py-3 text-sm font-semibold transition-all",
                    isRight
                      ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100"
                      : isWrongPick
                        ? "border-rose-400/60 bg-rose-500/15 text-rose-100"
                        : chosen
                          ? "border-sky-400/60 bg-sky-500/15 text-sky-100"
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

        {q.type === "short" || q.type === "interview" ? (
          <div className="space-y-3">
            <textarea
              className="input min-h-28"
              placeholder="Write your answer…"
              value={picked[q.id]?.text ?? ""}
              onChange={(e) => pick({ text: e.target.value })}
            />
            <Button variant="secondary" onClick={() => setRevealed((prev) => ({ ...prev, [q.id]: !prev[q.id] }))}>
              <Eye className="h-4 w-4" /> {revealed[q.id] ? "Hide model answer" : "Show model answer"}
            </Button>
            {revealed[q.id] && (
              <div className="space-y-2 rounded-xl border border-emerald-400/20 bg-emerald-500/8 px-4 py-3 text-sm">
                <p className="prose-answer text-foreground/85">{q.answer ?? "(no model answer)"}</p>
                {q.explanation && (
                  <p className="flex items-start gap-2 border-t border-white/10 pt-2 text-foreground/70">
                    <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
                    <span className="prose-answer">{q.explanation}</span>
                  </p>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {isChecked && (
              <div
                className={cn(
                  "space-y-2 rounded-xl border px-4 py-3 text-sm",
                  result
                    ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
                    : "border-rose-400/30 bg-rose-500/10 text-rose-200"
                )}
              >
                <p className="flex items-center gap-2 font-semibold">
                  {result ? (
                    <>
                      <Check className="h-4 w-4" /> Correct
                    </>
                  ) : (
                    <>
                      <X className="h-4 w-4" /> Incorrect
                    </>
                  )}
                </p>
                {q.type === "mcq" && correctText && (
                  <p className="text-foreground/85">
                    <span className="font-semibold">
                      The answer is {String.fromCharCode(65 + correctIndex)}:
                    </span>{" "}
                    {correctText}
                  </p>
                )}
                {q.type === "true_false" && (
                  <p className="text-foreground/85">
                    <span className="font-semibold">The answer is {tfAnswer ? "True" : "False"}.</span>
                  </p>
                )}
                {!correctText && q.type === "mcq" && (
                  <p className="text-amber-200/90">
                    This question has no answer key stored, so it cannot be graded. Regenerate or fix it.
                  </p>
                )}
                {q.explanation ? (
                  <p className="flex items-start gap-2 border-t border-white/10 pt-2 text-foreground/70">
                    <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
                    <span className="prose-answer">{q.explanation}</span>
                  </p>
                ) : (
                  <p className="border-t border-white/10 pt-2 text-amber-200/90">
                    No justification was stored for this question.
                  </p>
                )}
              </div>
            )}
            {!isChecked && hasChoice && (
              <Button onClick={confirmAnswer} className="w-full sm:w-auto">
                <Check className="h-4 w-4" /> Confirm answer
              </Button>
            )}
            {!isChecked && !hasChoice && (
              <p className="text-xs text-foreground/55">
                Select an option, then confirm it to see the answer and why it is correct.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="secondary" onClick={() => goTo(index - 1)} disabled={index === 0}>
          <ChevronLeft className="h-4 w-4" /> Previous
        </Button>
        <div className="flex flex-col items-center gap-1">
          <Button onClick={requestSubmit} className="w-full sm:w-auto">
            <BarChart3 className="h-4 w-4" /> Submit &amp; see result
          </Button>
          <span className="text-xs text-foreground/55">
            {graded.length} of {objectiveTotal} confirmed
          </span>
        </div>
        <Button onClick={() => goTo(index + 1)} disabled={index >= order.length - 1}>
          Next <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
      {confirmSubmit && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-4">
          <div className="card w-full max-w-sm space-y-4 p-6">
            <h3 className="text-lg font-semibold">Submit with {skipped} skipped?</h3>
            <p className="text-sm text-foreground/60">
              You confirmed {graded.length} of {objectiveTotal} questions. The{" "}
              {skipped} you didn&apos;t confirm will be counted as skipped and scored 0.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setConfirmSubmit(false)}>
                Keep practising
              </Button>
              <Button
                onClick={() => {
                  setConfirmSubmit(false);
                  setSubmitted(true);
                }}
              >
                Submit anyway
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
