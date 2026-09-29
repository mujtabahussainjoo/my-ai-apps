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

/**
 * Every generated question has to survive being read on its own, years later,
 * with no document open. The reference material is a merged blob of chunks from
 * many files, so the model cannot assume the reader can see anything it saw.
 */
const SELF_CONTAINED =
  " SELF-CONTAINMENT RULES (mandatory): every question must be fully answerable from the question text alone. " +
  "If the source material contains a diagram, figure, flowchart, table, architecture, code listing, program, configuration, command, terminal output or trace, " +
  "you MUST reproduce that content verbatim inside the question itself, wrapped in a fenced code block (```), so the reader can see it. " +
  "Never refer to material the reader cannot see: phrases like 'the diagram above', 'the figure below', 'the following code', 'the image shown', 'as illustrated in the figure', " +
  "'according to the table', 'the output above' or 'the example given' are forbidden. " +
  "If a photo, screenshot, video or other raster image is the only way to convey the content, do not ask about it — skip that topic and use a different one. " +
  "Length limits apply to your prose only: when you inline a diagram or listing, include all of it, even if the question gets long.";

function contextBlock(ctx: string): string {
  const c = ctx.trim();
  return c
    ? `\n\n=== REFERENCE MATERIAL ===\n${c}\n=== END REFERENCE ===\nBase every question strictly on this reference material unless it is empty, in which case use general knowledge for the subject.\n`
    : "\nNo reference material provided. Use your general knowledge of the subject area.\n";
}

/**
 * Lists questions that have already been produced.
 *
 * Without this a small model answers "what is the basic unit of text" over and
 * over; every repeat was discarded as a duplicate, so a request for 50 questions
 * could return 4 while burning half an hour. Naming what already exists is the
 * only reliable way to get a different batch out of it.
 */
function avoidBlock(avoid: string[]): string {
  if (avoid.length === 0) return "";
  const stems = avoid.slice(-40).map((q) => `- ${q.replace(/\s+/g, " ").slice(0, 90)}`);
  return `\nThese questions ALREADY EXIST and will be thrown away if repeated. Cover DIFFERENT ideas, and target any of the subtopics listed above that are not represented yet:\n${stems.join("\n")}\n`;
}

export function mcqPrompt(
  ctx: string,
  topicNames: string[],
  count: number,
  avoid: string[] = []
): { system: string; user: string } {
  const system =
    "You are an expert exam question writer who creates rigorous, unambiguous multiple-choice questions. Each question must have exactly one correct answer and 4 or 5 options (never fewer than 4, never more than 5). Wrong options must be plausible but clearly incorrect. Keep the prose of each question concise (max ~35 words). Every option must be a complete, self-contained statement — never a bare 'A'/'B' label or a pointer to a diagram. Explanations must teach the concept in 1-2 short sentences and must never be empty." +
    SELF_CONTAINED +
    JSON_RULES;
  const user =
    `Create exactly ${count} multiple-choice questions (4 or 5 options each, never fewer than 4) for these topics: ${topicNames.join(", ") || "general"}.
     Output MUST contain exactly ${count} question objects — return all ${count}, never fewer.
     If a question needs a diagram or code listing to make sense, paste that content into the "question" field as a fenced code block rather than describing it.` +
    avoidBlock(avoid) +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "question": string, "options": string[4-5], "correctIndex": number, "explanation": string}]}.`;
  return { system, user };
}

export function trueFalsePrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert exam question writer. Write precise true/false statements. The answer must be unambiguously true or false. Statements must be self-contained sentences that are true or false on their own — if a statement only makes sense next to a diagram, code listing or table, either inline that content in a fenced code block or drop the idea. Statements should be concise. Explanations must clarify why the statement is true or false (1-3 sentences) and must never be empty." +
    SELF_CONTAINED +
    JSON_RULES;
  const user =
    `Create exactly ${count} true/false questions for these topics: ${topicNames.join(", ") || "general"}.
     Output MUST contain exactly ${count} question objects — return all ${count}, never fewer.
     If a statement needs a diagram or code listing to be judgeable, paste that content into the "statement" field as a fenced code block.` +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "statement": string, "answer": boolean, "explanation": string}]}.`;
  return { system, user };
}

export function shortAnswerPrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert exam question writer for short-answer / essay questions. Write clear, focused questions that require understanding, not trivia. Provide a concise model answer (2-5 sentences) and grading key points." +
    SELF_CONTAINED +
    JSON_RULES;
  const user =
    `Create exactly ${count} short-answer questions for these topics: ${topicNames.join(", ") || "general"}.
     Output MUST contain exactly ${count} question objects — return all ${count}, never fewer.
     If a question needs a diagram or code listing to make sense, paste that content into the "question" field as a fenced code block.` +
    contextBlock(ctx) +
    `Return JSON with shape: {"questions":[{"topic": string, "question": string, "answer": string}]}.`;
  return { system, user };
}

export function flashcardPrompt(ctx: string, topicNames: string[], count: number): { system: string; user: string } {
  const system =
    "You are an expert at creating spaced-repetition flashcards. Front should be a short prompt or question that makes sense on its own, with no reference to a document the learner cannot see. Back should be a concise, accurate answer (1-3 sentences). Avoid overly long backs. Make cards atomic (one idea each)." +
    SELF_CONTAINED +
    JSON_RULES;
  const user =
    `Create exactly ${count} flashcards for these topics: ${topicNames.join(", ") || "general"}.
     Output MUST contain exactly ${count} card objects — return all ${count}, never fewer.
     If a card front needs a diagram or code listing, paste it into the "front" field as a fenced code block.` +
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
    "You are a senior interviewer and hiring strategist. Write realistic interview questions for the given role. Provide a category, the question, coaching tips, an ideal STAR-format answer outline, and 1-2 follow-up questions. Match difficulty to the requested level. Each question must stand on its own, with no reference to a diagram or listing the candidate cannot see." +
    SELF_CONTAINED +
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

export function assistantSystemPrompt(ctx: { index: number; title: string; content: string }[]): string {
  const ref = ctx.length
    ? ctx.map((c) => `[${c.index}] ${c.title}\n${c.content}`).join("\n\n---\n\n")
    : "";
  const refBlock = ref
    ? `\n\n=== REFERENCE MATERIAL ===\n${ref}\n=== END REFERENCE ===\nBase your answer primarily on this reference material. Cite the chunks you used inline as [1], [2], etc. If the question is outside the reference, use general knowledge and say so explicitly.\n`
    : "\nNo reference material was found in the user's study materials. Use general knowledge and let the user know nothing relevant was found in their notes.\n";
  return (
    "You are PrepDesk, a helpful study assistant for exam and interview preparation. " +
    "Answer the user's question clearly and accurately. Use markdown (headings, short paragraphs, bullet lists) and keep answers focused. " +
    "Write in the same language the user writes in. Never invent citations — only cite the reference chunks that are actually provided." +
    refBlock
  );
}