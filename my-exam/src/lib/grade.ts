import type { QuizQuestion } from "./data";

export type Choice = { text: string; correct: boolean };
export type Picked = { chosen?: string | number | boolean | null; text?: string; selfCorrect?: boolean };

/** Index of the single option flagged correct, or -1 when the question has no key. */
export function correctIndex(choices: Choice[] | null | undefined): number {
  if (!Array.isArray(choices)) return -1;
  const idx = choices.findIndex((c) => c?.correct === true);
  return idx;
}

export function correctChoice(choices: Choice[] | null | undefined): Choice | null {
  const idx = correctIndex(choices);
  return idx >= 0 ? (choices?.[idx] ?? null) : null;
}

/** The boolean a true/false question is asking for, or null when unanswered. */
export function trueFalseAnswer(choices: Choice[] | null | undefined): boolean | null {
  const right = correctChoice(choices);
  if (!right) return null;
  return right.text.toLowerCase() === "true";
}

/**
 * Single source of truth for scoring an objective answer. Shared by the server
 * actions and by the client-side practice runner so the feedback a learner sees
 * while practising can never disagree with the score they are given.
 */
export type GradableQuestion = Pick<QuizQuestion, "type" | "choices"> & { points?: number };

export function gradeAnswer(question: GradableQuestion, a: Picked): { correct: boolean; got: number } {
  const points = question.points ?? 0;
  if (question.type === "short" || question.type === "interview") {
    return { correct: a.selfCorrect ?? false, got: a.selfCorrect ? points : 0 };
  }
  const right = correctChoice(question.choices);
  if (!right) return { correct: false, got: 0 };

  if (question.type === "true_false") {
    const chosenBool = a.chosen === true || a.chosen === "true";
    const correctBool = right.text.toLowerCase() === "true";
    return { correct: chosenBool === correctBool, got: chosenBool === correctBool ? points : 0 };
  }

  const idx = typeof a.chosen === "number" ? a.chosen : Number(a.chosen);
  const chosen = question.choices?.[idx];
  const correct = chosen?.text === right.text;
  return { correct, got: correct ? points : 0 };
}

/** True/false convenience wrapper: did this pick match the stored key? */
export function isCorrect(question: GradableQuestion, picked: Picked | undefined): boolean {
  if (!picked) return false;
  return gradeAnswer(question, picked).correct;
}
