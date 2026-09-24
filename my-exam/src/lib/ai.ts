import { query } from "@/lib/db";

export class AIError extends Error {}

export type AIConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  embeddingModel: string;
};

export function aiConfig(): AIConfig {
  const baseUrl = (
    process.env.AI_BASE_URL ||
    "http://localhost:11434/v1"
  ).replace(/\/+$/, "");
  const apiKey = process.env.AI_API_KEY || "ollama";
  const model = process.env.AI_MODEL || "llama3.2";
  const embeddingModel = process.env.AI_EMBEDDING_MODEL || "nomic-embed-text";
  return { baseUrl, apiKey, model, embeddingModel };
}

export async function isAiAvailable(): Promise<boolean> {
  try {
    const { baseUrl, apiKey } = aiConfig();
    const res = await fetch(`${baseUrl}/models`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      signal: AbortSignal.timeout(4000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

type ChatMessage = { role: "system" | "user" | "assistant"; content: string };

async function chat(
  messages: ChatMessage[],
  opts: { temperature?: number; maxTokens?: number; json?: boolean } = {}
): Promise<string> {
  const { baseUrl, apiKey, model } = aiConfig();
  const res = await fetch(`${baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages,
      temperature: opts.temperature ?? 0.4,
      max_tokens: opts.maxTokens ?? 2048,
      stream: false,
      ...(opts.json ? { response_format: { type: "json_object" } } : {}),
    }),
    signal: AbortSignal.timeout(300_000),
  });
  if (!res.ok) {
    throw new AIError(`AI request failed (${res.status})`);
  }
  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const content = data.choices?.[0]?.message?.content;
  if (!content) throw new AIError("AI returned an empty response");
  return content;
}

/** Resiliently extracts a JSON object from an LLM response. */
export function parseJson<T = unknown>(raw: string): T {
  const text = raw
    .trim()
    .replace(/^```(?:json)?/i, "")
    .replace(/```$/i, "")
    .trim();
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed) || (parsed && typeof parsed === "object")) {
      return parsed as T;
    }
  } catch {
    // fall through to repair
  }
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start !== -1 && end > start) {
    const candidate = text.slice(start, end + 1);
    try {
      return JSON.parse(candidate) as T;
    } catch {
      // fall through
    }
  }
  throw new AIError("AI returned invalid JSON");
}

/** Runs a chat request expecting a JSON object response. */
export async function chatJson<T = unknown>(
  system: string,
  user: string,
  opts: { temperature?: number; maxTokens?: number } = {}
): Promise<T> {
  const content = await chat(
    [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    { ...opts, json: true }
  );
  return parseJson<T>(content);
}

/** Generates one JSON array of results, retrying once on malformed output. */
export async function chatJsonArray<T = unknown>(
  system: string,
  user: string,
  opts: { temperature?: number; maxTokens?: number } = {}
): Promise<T[]> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const content = await chat(
        [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        { ...opts, json: true }
      );
      const parsed = parseJson<unknown>(content);
      if (Array.isArray(parsed)) return parsed as T[];
      if (parsed && typeof parsed === "object") {
        const arr = (parsed as Record<string, unknown>).items
          ? ((parsed as Record<string, unknown>).items as T[])
          : ((parsed as Record<string, unknown>).questions as unknown)
            ? ((parsed as Record<string, unknown>).questions as T[])
            : null;
        if (Array.isArray(arr)) return arr;
      }
    } catch (err) {
      if (attempt === 1) throw err;
    }
  }
  throw new AIError("AI returned malformed data");
}

export async function embedTexts(inputs: string[]): Promise<number[][]> {
  const { baseUrl, apiKey, embeddingModel } = aiConfig();
  const res = await fetch(`${baseUrl}/embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ model: embeddingModel, input: inputs }),
    signal: AbortSignal.timeout(120_000),
  });
  if (!res.ok) throw new AIError("Embedding request failed");
  const data = (await res.json()) as {
    data: { embedding: number[] }[];
  };
  if (!Array.isArray(data.data)) {
    // Some providers return a single object for a single prompt
    if (data.data && Array.isArray((data.data as never as { embedding: number[] }).embedding)) {
      return [(data.data as never as { embedding: number[] }).embedding];
    }
    throw new AIError("Embedding response was malformed");
  }
  return data.data.map((d) => d.embedding);
}

export async function embedText(input: string): Promise<number[]> {
  const [vec] = await embedTexts([input]);
  return vec;
}

export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length === 0 || b.length === 0 || a.length !== b.length) return 0;
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  const denom = Math.sqrt(na) * Math.sqrt(nb);
  return denom === 0 ? 0 : dot / denom;
}

export type RAGResult = { materialId: string; title: string; content: string; score: number };

/**
 * Retrieves the most relevant material chunks for a query using embedding
 * cosine similarity. Scoped to the user's own materials.
 */
export async function ragSearch(
  userId: string,
  queryText: string,
  opts: { examId?: string | null; limit?: number; minScore?: number } = {}
): Promise<RAGResult[]> {
  const limit = opts.limit ?? 5;
  const examClause = opts.examId
    ? "AND m.exam_id = $2"
    : opts.examId === null
      ? ""
      : "AND (m.exam_id IS NULL OR TRUE)";
  const params: unknown[] = [userId];
  if (opts.examId) params.push(opts.examId);

  const rows = await query<{
    id: string;
    material_id: string;
    title: string;
    content: string;
    embedding: number[];
  }>(
    `SELECT c.id, c.material_id, m.title, c.content, c.embedding
     FROM chunks c
     JOIN materials m ON m.id = c.material_id
     WHERE m.user_id = $1 ${examClause}`,
    params
  );

  if (rows.length === 0) return [];

  let queryVector: number[];
  try {
    queryVector = await embedText(queryText.slice(0, 6000));
  } catch {
    return [];
  }

  const scored = rows
    .map((row) => ({
      materialId: row.material_id,
      title: row.title,
      content: row.content,
      score: cosineSimilarity(queryVector, row.embedding || []),
    }))
    .filter((r) => r.score > (opts.minScore ?? 0.15))
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);

  return scored;
}