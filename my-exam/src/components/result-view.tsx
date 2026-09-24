"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, X, RotateCcw, CircleHelp, Loader2 } from "lucide-react";
import { Button, Badge } from "@/components/ui";
import { selfGradeAnswer } from "@/lib/actions";
import { QuizQuestion, AnswerEntry } from "@/lib/data";

export type ResultItem = {
  question: QuizQuestion;
  answer: AnswerEntry;
};

export function ResultView({
  sessionId,
  mode,
  title,
  items,
  score,
  total,
  durationSec,
}: {
  sessionId: string;
  mode: string;
  title: string;
  items: ResultItem[];
  score: number;
  total: number;
  durationSec: number | null;
}) {
  const [busyGrade, setBusyGrade] = useState<string | null>(null);
  const router = useRouter();

  const pct = total > 0 ? Math.round((score / total) * 100) : 0;
  const grade =
    pct >= 90 ? "A" : pct >= 80 ? "B" : pct >= 70 ? "C" : pct >= 60 ? "D" : "F";

  const gradeColor =
    pct >= 80 ? "text-emerald-400" : pct >= 60 ? "text-amber-300" : "text-rose-400";

  const selfGrade = async (questionId: string, value: boolean) => {
    setBusyGrade(questionId);
    const res = await selfGradeAnswer(sessionId, questionId, value);
    setBusyGrade(null);
    if (res.ok) router.refresh();
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="card relative overflow-hidden p-8 text-center">
        <div className="mx-auto mb-4 flex h-24 w-24 items-center justify-center rounded-full border-[6px] border-white/10" style={{ boxShadow: "0 0 60px -12px rgba(139,92,246,.6)" }}>
          <div>
            <div className="text-3xl font-extrabold">{pct}%</div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-foreground/50">score</div>
          </div>
        </div>
        <h1 className={`text-5xl font-black ${gradeColor}`}>{grade}</h1>
        <p className="mt-1 text-sm text-foreground/60">{title}</p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-xs text-foreground/60">
          <Badge color="slate">{score} / {total} correct</Badge>
          {durationSec !== null && <Badge color="slate">{Math.round(durationSec / 60)}m {durationSec % 60}s</Badge>}
          <Badge color={mode === "mock" ? "sky" : "violet"}>{mode === "mock" ? "Mock exam" : "Practice"}</Badge>
        </div>
        <div className="mt-5">
          <button
            className="btn btn-secondary"
            onClick={() => router.push(mode === "mock" ? "/mock" : "/quiz")}
          >
            <RotateCcw className="h-4 w-4" /> {mode === "mock" ? "Take another mock" : "New practice"}
          </button>
        </div>
      </div>

      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Review</h2>
        {items.map(({ question: q, answer }, i) => {
          const correct = q.type === "short" ? answer.correct : !!answer.correct;
          return (
            <div key={q.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="mb-2 flex flex-wrap items-center gap-1.5">
                    <Badge
                      color={correct === true ? "emerald" : correct === false ? "rose" : "slate"}
                    >
                      {correct ? "Correct" : "Incorrect"}
                    </Badge>
                    <Badge color="slate">#{i + 1}</Badge>
                    <span className="tag">{q.type.replace("_", " ")}</span>
                    {q.category && <span className="tag">{q.category}</span>}
                  </div>
                  <p className="prose-answer font-medium leading-relaxed">{q.prompt}</p>

                  {q.type === "mcq" && q.choices && (
                    <ul className="mt-3 space-y-1.5">
                      {q.choices.map((c, j) => {
                        const chosenIdx = typeof answer.chosen === "number" ? answer.chosen : Number(answer.chosen);
                        const isChosen = chosenIdx === j;
                        const isRight = c.correct;
                        return (
                          <li
                            key={j}
                            className={`flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${
                              isRight
                                ? "bg-emerald-500/10 text-emerald-200"
                                : isChosen
                                  ? "bg-rose-500/10 text-rose-200"
                                  : "bg-white/3 text-foreground/65"
                            }`}
                          >
                            {isRight ? (
                              <Check className="mt-0.5 h-4 w-4 shrink-0" />
                            ) : isChosen ? (
                              <X className="mt-0.5 h-4 w-4 shrink-0" />
                            ) : (
                              <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            )}
                            <span>{String.fromCharCode(65 + j)}. {c.text}</span>
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  {q.type === "true_false" && (
                    <div className="mt-3 flex gap-2">
                      {["true", "false"].map((val, j) => {
                        const chosen = String(answer.chosen) === val;
                        const isRight = (q.choices?.[j].correct) ?? false;
                        return (
                          <span
                            key={val}
                            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                              isRight
                                ? "bg-emerald-500/10 text-emerald-200"
                                : chosen
                                  ? "bg-rose-500/10 text-rose-200"
                                  : "bg-white/3 text-foreground/60"
                            }`}
                          >
                            {j === 0 ? "True" : "False"}
                          </span>
                        );
                      })}
                    </div>
                  )}

                  {q.type === "short" && (
                    <div className="mt-3 space-y-2">
                      <div className="rounded-lg bg-black/25 px-3 py-2 text-sm">
                        <span className="font-semibold text-foreground/60">Your answer: </span>
                        <span className="prose-answer text-foreground/85">{answer.text || "(blank)"}</span>
                      </div>
                      {q.answer && (
                        <div className="rounded-lg border border-emerald-400/20 bg-emerald-500/8 px-3 py-2 text-sm">
                          <span className="font-semibold text-emerald-300">Model answer: </span>
                          <span className="prose-answer text-foreground/85">{q.answer}</span>
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-foreground/55">Did you get it right?</span>
                        <Button
                          variant={answer.correct ? "primary" : "secondary"}
                          className="px-3 py-1 text-xs"
                          disabled={busyGrade === q.id}
                          onClick={() => selfGrade(q.id, true)}
                        >
                          {busyGrade === q.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                          Right
                        </Button>
                        <Button
                          variant={answer.correct === false ? "danger" : "secondary"}
                          className="px-3 py-1 text-xs"
                          disabled={busyGrade === q.id}
                          onClick={() => selfGrade(q.id, false)}
                        >
                          <X className="h-3 w-3" /> Wrong
                        </Button>
                      </div>
                    </div>
                  )}

                  {q.explanation && (
                    <p className="mt-3 rounded-lg bg-white/4 px-3 py-2 text-sm text-foreground/65">
                      <span className="font-semibold text-violet-300">Why: </span>
                      {q.explanation}
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