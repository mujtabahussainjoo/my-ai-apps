export type GeneratedMCQ = {
  topic?: string;
  question: string;
  options: string[];
  correctIndex: number;
  explanation: string;
};

export type GeneratedTF = {
  topic?: string;
  statement: string;
  answer: boolean;
  explanation: string;
};

export type GeneratedShort = {
  topic?: string;
  question: string;
  answer: string;
};

export type GeneratedFlashcard = {
  topic?: string;
  front: string;
  back: string;
};

export type GeneratedInterview = {
  category: string;
  question: string;
  tips?: string;
  idealAnswer?: string;
  followUps?: string[];
};

const JSON_RULES =
  "Respond with ONLY a valid JSON object. Do not wrap it in markdown or add commentary. All fields are required.";

function contextBlock(ctx: string): string {
  const c = ctx.trim();
  return c
    ? `\n\n=== REFERENCE MATERIAL ===\n${c}\n=== END REFERENCE ===\nBase every question strictly on this reference material unless it is empty, in which case use general knowledge for the subject.\n`
    : "\nNo reference material provided. Use your general knowledge of the subject area.\n";
}

export function mcqPrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert exam question writer who creates rigorous, unambiguous multiple-choice questions. Each question must have exactly one correct answer. Wrong options must be plausible but clearly incorrect. Keep questions concise (max ~35 words). Explanations must teach the concept (2-4 sentences)." +
    JSON_RULES;
  const user =
    `Create ${count} multiple-choice questions (4 options each) for these topics: ${topicNames.join(", ") || "general"}.` +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "question": string, "options": string[4], "correctIndex": number, "explanation": string}]}.`;
  return { system, user };
}

export function trueFalsePrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert exam question writer. Write precise true/false statements. The answer must be unambiguously true or false. Statements should be concise. Explanations must clarify why the statement is true or false (1-3 sentences)." +
    JSON_RULES;
  const user =
    `Create ${count} true/false questions for these topics: ${topicNames.join(", ") || "general"}.` +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "statement": string, "answer": boolean, "explanation": string}]}.`;
  return { system, user };
}

export function shortAnswerPrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert exam question writer for short-answer / essay questions. Write clear, focused questions that require understanding, not trivia. Provide a concise model answer (2-5 sentences) and grading key points." +
    JSON_RULES;
  const user =
    `Create ${count} short-answer questions for these topics: ${topicNames.join(", ") || "general"}.` +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "question": string, "answer": string}]}.`;
  return { system, user };
}

export function flashcardPrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert at creating spaced-repetition flashcards. Front should be a short prompt or question. Back should be a concise, accurate answer (1-3 sentences). Avoid overly long backs. Make cards atomic (one idea each)." +
    JSON_RULES;
  const user =
    `Create ${count} flashcards for these topics: ${topicNames.join(", ") || "general"}.` +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "front": string, "back": string}]}.`;
  return { system, user };
}

export function interviewPrompt(opts: {
  role: string;
  difficulty: string;
  categories: string[];
  countPerCategory: number;
  ctx: string;
}): { system: string; user: string } {
  const system =
    "You are a senior interviewer and hiring strategist. Write realistic interview questions for the given role. Provide a category, the question, coaching tips, an ideal STAR-format answer outline, and 1-2 follow-up questions. Match difficulty to the requested level." +
    JSON_RULES;
  const user =
    `Role: ${opts.role}\nDifficulty: ${opts.difficulty}\nCategories: ${opts.categories.join(", ")}\nQuestions per category: ${opts.countPerCategory}\n` +
    "Generate questions. For behavioral questions frame them as STAR-style situations." +
    contextBlock(opts.ctx) +
    `Return JSON with shape: {"questions":[{"category": string, "question": string, "tips": string, "idealAnswer": string, "followUps": string[]}]}.`;
  return { system, user };
}

export function interviewFeedbackPrompt(opts: {
  role: string;
  question: string;
  modelAnswer?: string;
  userAnswer: string;
}): { system: string; user: string } {
  const system =
    "You are a rigorous interview coach. Evaluate the candidate's answer against STAR criteria (Situation, Task, Action, Result), clarity, structure, and delivery. Be constructive but honest. Give a letter score (A-F), strengths, weaknesses, and a rewritten ideal answer." +
    JSON_RULES;
  const user =
    `Role: ${opts.role}\nQuestion: ${opts.question}\nModel answer (optional): ${opts.modelAnswer ?? "(none)"}\n\nCandidate answer:\n"""\n${opts.userAnswer}\n"""\n\n` +
    `Return JSON with shape: {"grade": "A".."F", "score": number(0-100), "strengths": string[], "weaknesses": string[], "verdict": string, "starScore": {"situation": number, "task": number, "action": number, "result": number}} where each starScore component is 0-100.`;
  return { system, user };
}

const INTERVIEW_CATEGORIES = ["behavioral", "technical", "scenario", "hr"];
export { INTERVIEW_CATEGORIES };