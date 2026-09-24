import { AIError, chatJsonArray, ragSearch } from "@/lib/ai";
import { query } from "@/lib/db";
import {
  mcqPrompt,
  trueFalsePrompt,
  shortAnswerPrompt,
  flashcardPrompt,
  interviewPrompt,
  type GeneratedMCQ,
  type GeneratedTF,
  type GeneratedShort,
  type GeneratedFlashcard,
  type GeneratedInterview,
} from "@/lib/prompts";

export type GenInput = {
  userId: string;
  examId?: string | null;
  topicIds?: string[];
  type: "mcq" | "true_false" | "short" | "flashcard" | "interview";
  count: number;
};

type TopicInfo = { id: string | null; name: string };

async function loadTopics(examId?: string | null): Promise<TopicInfo[]> {
  if (!examId) return [];
  const topics = await query<{ id: string; name: string }>(
    "SELECT id, name FROM topics WHERE exam_id = $1 ORDER BY sort_order",
    [examId]
  );
  return topics.map((t) => ({ id: t.id, name: t.name }));
}

async function buildContext(
  userId: string,
  examId: string | null | undefined,
  topicNames: string[]
): Promise<string> {
  const queryText = topicNames.join(", ") || "general exam preparation";
  const results = await ragSearch(userId, queryText, { examId: examId ?? null, limit: 6 });
  return results.map((r) => `[${r.title}]\n${r.content}`).join("\n\n---\n\n");
}

function abbreviated(question: string, options: string[]): string {
  return options.every((o) => o.length < 240) && question.length < 800
    ? options.join("  |  ")
    : "short options";
}

export async function generateFromAI(input: GenInput): Promise<
  { topicId: string | null; prompt: string; type: string; choices: unknown; answer: string; explanation: string; category: string | null }[]
> {
  const topics = await loadTopics(input.examId);
  const topicNames = topics.map((t) => t.name);
  const filteredTopics = topics.filter((t) => !input.topicIds || input.topicIds.length === 0 || input.topicIds.includes(t.id ?? ""));
  const names = filteredTopics.length > 0 ? filteredTopics.map((t) => t.name) : topicNames;
  const ctx = await buildContext(input.userId, input.examId, names);

  const idForName = new Map(names.map((n, i) => [n, filteredTopics[i]?.id ?? null]));

  switch (input.type) {
    case "mcq": {
      const { system, user } = mcqPrompt(ctx, names, input.count);
      const out = await chatJsonArray<GeneratedMCQ>(system, user, { maxTokens: 4096 });
      return out.slice(0, input.count).map((q) => ({
        topicId: idForName.get(q.topic ?? "") ?? null,
        prompt: q.question,
        type: "mcq",
        choices: q.options.map((text, idx) => ({ text, correct: idx === q.correctIndex })),
        answer: q.options[q.correctIndex] ?? "",
        explanation: q.explanation ?? "",
        category: null,
      }));
    }
    case "true_false": {
      const { system, user } = trueFalsePrompt(ctx, names, input.count);
      const out = await chatJsonArray<GeneratedTF>(system, user, { maxTokens: 4096 });
      return out.slice(0, input.count).map((q) => ({
        topicId: idForName.get(q.topic ?? "") ?? null,
        prompt: q.statement,
        type: "true_false",
        choices: [
          { text: "True", correct: q.answer },
          { text: "False", correct: !q.answer },
        ],
        answer: q.answer ? "True" : "False",
        explanation: q.explanation ?? "",
        category: null,
      }));
    }
    case "short": {
      const { system, user } = shortAnswerPrompt(ctx, names, input.count);
      const out = await chatJsonArray<GeneratedShort>(system, user, { maxTokens: 4096 });
      return out.slice(0, input.count).map((q) => ({
        topicId: idForName.get(q.topic ?? "") ?? null,
        prompt: q.question,
        type: "short",
        choices: null,
        answer: q.answer ?? "",
        explanation: "",
        category: null,
      }));
    }
    case "flashcard": {
      const { system, user } = flashcardPrompt(ctx, names, input.count);
      const out = await chatJsonArray<GeneratedFlashcard>(system, user, { maxTokens: 4096 });
      return out.slice(0, input.count).map((q) => ({
        topicId: idForName.get(q.topic ?? "") ?? null,
        prompt: q.front,
        type: "flashcard",
        choices: null,
        answer: q.back ?? "",
        explanation: "",
        category: null,
      }));
    }
    case "interview": {
      const role = names.join(", ") || "Software Engineer";
      const { system, user } = interviewPrompt({
        role,
        difficulty: "medium",
        categories: ["behavioral", "technical"],
        countPerCategory: 2,
        ctx,
      });
      const out = await chatJsonArray<GeneratedInterview>(system, user, { maxTokens: 4096 });
      return out.slice(0, input.count).map((q) => ({
        topicId: null,
        prompt: q.question,
        type: "interview",
        choices: null,
        answer: q.idealAnswer ?? "",
        explanation: `${q.tips ?? ""}\n\nFollow-ups: ${(q.followUps ?? []).join(" / ")}`,
        category: q.category ?? "behavioral",
      }));
    }
    default:
      throw new AIError("Unknown generation type");
  }
}

export async function persistGeneratedQuestions(
  userId: string,
  examId: string | null,
  rows: { topicId: string | null; type: string; prompt: string; choices: unknown; answer: string; explanation: string; category: string | null }[]
): Promise<number> {
  for (const r of rows) {
    const choicesJson = r.choices ? JSON.stringify(r.choices) : null;
    await query(
      `INSERT INTO questions (user_id, exam_id, topic_id, type, category, prompt, choices, answer, explanation, source)
       VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, 'ai')`,
      [userId, examId, r.topicId, r.type, r.category, r.prompt, choicesJson, r.answer, r.explanation]
    );
  }
  return rows.length;
}

export function makeQuestionSnapshot(
  row: { id: string; type: string; category: string | null; prompt: string; choices: unknown | null; answer: string | null; explanation: string | null; topic_id: string | null; points: number }
) {
  return {
    id: row.id,
    type: row.type,
    category: row.category,
    prompt: row.prompt,
    choices: row.choices,
    answer: row.answer,
    explanation: row.explanation,
    topicId: row.topic_id,
    points: row.points,
  };
}

export { abbreviated };