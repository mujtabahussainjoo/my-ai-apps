import { query, queryOne } from "@/lib/db";

export class AIError extends Error {}

/** Told when a response was cut off by the output cap, so callers can record it. */
type TruncationNotice = (info: { maxTokens: number; finishReason: string }) => void;

export type AIProvider = "local" | "openai";

export type AIConfig = {
  provider: AIProvider;
  baseUrl: string;
  apiKey: string;
  model: string;
  embeddingModel: string;
};

const DEFAULT_LOCAL_URL = "http://localhost:11434/v1";
const DEFAULT_OPENAI_URL = "https://api.openai.com/v1";
const DEFAULT_LOCAL_MODEL = "llama3.2";
const DEFAULT_OPENAI_MODEL = "gpt-4o-mini";
const DEFAULT_LOCAL_EMBEDDING = "nomic-embed-text";
const DEFAULT_OPENAI_EMBEDDING = "text-embedding-3-small";

/** Env-based default config (used when a user has no saved settings). */
export function aiConfig(): AIConfig {
  const baseUrl = (process.env.AI_BASE_URL || DEFAULT_LOCAL_URL).replace(/\/+$/, "");
  return {
    provider: baseUrl.includes("openai.com") ? "openai" : "local",
    baseUrl,
    apiKey: process.env.AI_API_KEY || "ollama",
    model: process.env.AI_MODEL || DEFAULT_LOCAL_MODEL,
    embeddingModel: process.env.AI_EMBEDDING_MODEL || DEFAULT_LOCAL_EMBEDDING,
  };
}

type SettingsRow = {
  ai_provider: string | null;
  ai_base_url: string | null;
  ai_api_key: string | null;
  ai_model: string | null;
  ai_embedding_model: string | null;
};

/**
 * Resolves the effective AI config for a user by merging their saved
 * settings (Settings menu) over the environment defaults. Falls back to
 * provider-specific defaults when fields are blank.
 */
export async function aiConfigForUser(userId: string): Promise<AIConfig> {
  const env = aiConfig();
  const row = await queryOne<SettingsRow>(
    "SELECT ai_provider, ai_base_url, ai_api_key, ai_model, ai_embedding_model FROM user_settings WHERE user_id = $1",
    [userId]
  );
  const provider: AIProvider = row?.ai_provider === "openai" ? "openai" : "local";

  if (provider === "openai") {
    return {
      provider,
      baseUrl: (row?.ai_base_url || (env.baseUrl.includes("openai.com") ? env.baseUrl : DEFAULT_OPENAI_URL)).replace(/\/+$/, ""),
      apiKey: row?.ai_api_key || env.apiKey,
      model: row?.ai_model || env.model || DEFAULT_OPENAI_MODEL,
      embeddingModel: row?.ai_embedding_model || DEFAULT_OPENAI_EMBEDDING,
    };
  }

  return {
    provider,
    baseUrl: (row?.ai_base_url || env.baseUrl).replace(/\/+$/, ""),
    apiKey: row?.ai_api_key || env.apiKey,
    model: row?.ai_model || env.model || DEFAULT_LOCAL_MODEL,
    embeddingModel: row?.ai_embedding_model || env.embeddingModel || DEFAULT_LOCAL_EMBEDDING,
  };
}

async function resolveConfig(userId: string | null): Promise<AIConfig> {
  if (!userId) return aiConfig();
  return aiConfigForUser(userId);
}

async function checkAvailability(cfg: AIConfig, timeoutMs = 4000): Promise<boolean> {
  const res = await fetch(`${cfg.baseUrl}/models`, {
    headers: { Authorization: `Bearer ${cfg.apiKey}` },
    signal: AbortSignal.timeout(timeoutMs),
  });
  return res.ok;
}

/** Whether the effective AI service for a user (or env default) is reachable. */
export async function isAiAvailable(userId: string | null = null): Promise<boolean> {
  try {
    return await checkAvailability(await resolveConfig(userId));
  } catch {
    return false;
  }
}

/** Tests an arbitrary provider config, e.g. values typed into the Settings form. */
export async function testAiConfig(cfg: AIConfig): Promise<{ ok: boolean; detail: string }> {
  let modelCount = -1;
  try {
    const res = await fetch(`${cfg.baseUrl}/models`, {
      headers: { Authorization: `Bearer ${cfg.apiKey}` },
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) return { ok: false, detail: `Connection failed (HTTP ${res.status})` };
    const data = (await res.json().catch(() => null)) as { data?: unknown[] } | null;
    modelCount = Array.isArray(data?.data) ? data.data.length : -1;
  } catch {
    return { ok: false, detail: "Could not reach the model provider" };
  }

  const prefix = modelCount >= 0 ? `Connected — ${modelCount} model(s).` : "Connected.";

  // Connectivity is not enough: a model can answer and still be far too slow to
  // build a question bank. Measure real generation throughput so the user finds
  // out here instead of staring at a failed generation minutes later.
  const started = Date.now();
  try {
    const res = await timedFetch(
      `${cfg.baseUrl}/chat/completions`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${cfg.apiKey}`,
        },
        body: JSON.stringify({
          model: cfg.model,
          messages: [{ role: "user", content: "Reply with the single word: OK" }],
          stream: false,
          max_tokens: 8,
        }),
        signal: AbortSignal.timeout(90_000),
      }
    );
    if (!res.ok) return { ok: false, detail: `${prefix} Generation failed (HTTP ${res.status})` };
    const data = (await res.json()) as {
      choices?: { message?: { content?: string } }[];
      usage?: { completion_tokens?: number };
    };
    const elapsed = (Date.now() - started) / 1000;
    const tokens = data.usage?.completion_tokens ?? 0;
    const rate = tokens > 0 ? tokens / elapsed : 0;
    const reply = (data.choices?.[0]?.message?.content ?? "").trim();
    if (elapsed > 60) {
      return {
        ok: false,
        detail: `${prefix} "${cfg.model}" took ${elapsed.toFixed(0)}s to answer "${reply.slice(0, 20)}" — far too slow to generate questions. Free up memory, use a smaller model, or point AI_BASE_URL at a hosted provider.`,
      };
    }
    const speed = rate > 0 ? ` ~${rate.toFixed(1)} tokens/sec` : "";
    if (elapsed > 20) {
      return {
        ok: false,
        detail: `${prefix} "${cfg.model}" is very slow (${elapsed.toFixed(0)}s${speed}). Free memory or use a smaller model, or generation will time out.`,
      };
    }
    return { ok: true, detail: `${prefix} "${cfg.model}" replied in ${elapsed.toFixed(1)}s${speed}.` };
  } catch (err) {
    const message = err instanceof AIError ? err.message : String(err);
    return { ok: false, detail: `${prefix} Generation check failed: ${message}` };
  }
}

// ---------------------------------------------------------------- chat

export type AIChatMessage = { role: "system" | "user" | "assistant"; content: string };

/** Ollama's native API root, derived from an OpenAI-style base URL (…/v1). */
function ollamaApiRoot(baseUrl: string): string {
  return baseUrl.replace(/\/v1\/?$/, "");
}

/**
 * Wraps fetch so a slow or wedged model fails with an actionable message.
 * A raw AbortError used to surface as "The operation was aborted", which told
 * the user nothing about the actual cause.
 */
async function timedFetch(url: string, init: RequestInit & { signal?: AbortSignal }): Promise<Response> {
  const started = Date.now();
  try {
    return await fetch(url, init);
  } catch (err) {
    const elapsed = Math.round((Date.now() - started) / 1000);
    const aborted = err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
    if (aborted) {
      throw new AIError(
        `AI request timed out after ${elapsed}s. The model is too slow to finish in time — ` +
          `reduce the number of questions, use a smaller model, or free up memory on the machine.`
      );
    }
    // A dropped connection is ambiguous: the provider may be unreachable, or it
    // may have been killed mid-request (a local model that outgrew RAM is the
    // common case). Probing costs a few hundred ms and only happens on failure,
    // and it turns a useless "fetch failed" into the actual cause.
    const alive = await providerStillResponding(url);
    if (!alive.ok) {
      throw new AIError(
        `The AI provider died while answering (${elapsed}s, ${alive.reason}). ` +
          `A local model that exhausts RAM gets killed by the OS mid-request. ` +
          `Free memory, use a smaller model, or point AI_BASE_URL at a hosted provider.`
      );
    }
    throw new AIError(
      `The AI provider accepted the connection but dropped the request after ${elapsed}s ` +
        `(${err instanceof Error ? err.message : String(err)}). It may have run out of memory ` +
        `mid-request. Try fewer questions, or use a smaller model.`
    );
  }
}

/** Cheap liveness probe, used only to explain a failed request. */
async function providerStillResponding(url: string): Promise<{ ok: boolean; reason: string }> {
  try {
    const root = new URL(url).origin;
    const res = await fetch(`${root}/v1/models`, { signal: AbortSignal.timeout(4000) });
    if (res.ok) return { ok: true, reason: "reachable" };
    return { ok: false, reason: `responded with HTTP ${res.status}` };
  } catch (err) {
    const e = err as Error & { cause?: { code?: string } };
    const code = e?.cause?.code ?? e?.name ?? "unknown";
    return { ok: false, reason: `no longer accepting connections (${code})` };
  }
}

async function chatCompletionWithConfig(
  cfg: AIConfig,
  messages: AIChatMessage[],
  opts: {
    temperature?: number;
    maxTokens?: number;
    json?: boolean;
    timeoutMs?: number;
    onTruncated?: TruncationNotice;
  } = {}
): Promise<string> {
  // The local provider speaks Ollama's native API so we can enforce a large
  // context window (num_ctx) and structured JSON. Without num_ctx Ollama
  // loads tiny 4K contexts and silently truncates big training documents.
  if (cfg.provider === "local") {
    const res = await timedFetch(`${ollamaApiRoot(cfg.baseUrl)}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: cfg.model,
        messages,
        stream: false,
        ...(opts.json ? { format: "json" } : {}),
        options: {
          temperature: opts.temperature ?? 0.4,
          num_predict: opts.maxTokens ?? 2048,
          num_ctx: Number(process.env.AI_NUM_CTX ?? 16_384),
        },
      }),
      signal: AbortSignal.timeout(opts.timeoutMs ?? 600_000),
    });
    if (!res.ok) {
      throw new AIError(`AI request failed (${res.status})`);
    }
    const data = (await res.json()) as { message?: { content?: string }; done_reason?: string };
    const content = data.message?.content;
    if (!content) throw new AIError("AI returned an empty response");
    if (data.done_reason === "length") {
      // Silently truncated JSON still parses into plausible-looking but broken
      // objects, which the quality gate then rejects for missing fields. Say so.
      const maxTokens = opts.maxTokens ?? 2048;
      console.warn(
        `[ai] response hit the ${maxTokens}-token output cap (finish=length) — ask for fewer items per call`
      );
      opts.onTruncated?.({ maxTokens, finishReason: "length" });
    }
    return content;
  }

  const res = await timedFetch(`${cfg.baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.apiKey}`,
    },
    body: JSON.stringify({
      model: cfg.model,
      messages,
      temperature: opts.temperature ?? 0.4,
      max_tokens: opts.maxTokens ?? 2048,
      stream: false,
      ...(opts.json ? { response_format: { type: "json_object" } } : {}),
    }),
    signal: AbortSignal.timeout(opts.timeoutMs ?? 300_000),
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

/**
 * Free-form (non-JSON) chat completion with multi-turn history.
 * Uses the user's saved provider config, or env defaults when userId is null.
 */
export async function chatCompletion(
  userId: string | null,
  messages: AIChatMessage[],
  opts: { temperature?: number; maxTokens?: number } = {}
): Promise<string> {
  const cfg = await resolveConfig(userId);
  return chatCompletionWithConfig(cfg, messages, opts);
}

/**
 * Repairs the JSON defects small local models actually produce, in place:
 * smart quotes, bare `undefined`, unescaped newlines inside strings, trailing
 * commas, and output cut off mid-object by a token limit.
 */
function repairJson(text: string): string {
  const out = text
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/:\s*undefined\b/g, ": null");

  // Walk the text tracking string state so repairs never touch string contents
  // beyond escaping genuinely illegal control characters, and so an unterminated
  // object can be closed at the end.
  const stack: string[] = [];
  let inString = false;
  let escaped = false;
  let built = "";
  for (let i = 0; i < out.length; i++) {
    const ch = out[i];
    if (inString) {
      if (escaped) {
        escaped = false;
        built += ch;
        continue;
      }
      if (ch === "\\") {
        escaped = true;
        built += ch;
        continue;
      }
      if (ch === '"') {
        inString = false;
        built += ch;
        continue;
      }
      if (ch === "\n") {
        built += "\\n";
        continue;
      }
      if (ch === "\r") {
        built += "\\r";
        continue;
      }
      if (ch === "\t") {
        built += "\\t";
        continue;
      }
      built += ch;
      continue;
    }
    if (ch === '"') {
      inString = true;
      built += ch;
      continue;
    }
    if (ch === "{" || ch === "[") {
      stack.push(ch);
      built += ch;
      continue;
    }
    if (ch === "}" || ch === "]") {
      stack.pop();
      built += ch;
      continue;
    }
    built += ch;
  }
  if (inString) built += '"';
  // Truncated output: close whatever is still open so the parse can succeed.
  while (stack.length > 0) built += stack.pop() === "{" ? "}" : "]";
  return built;
}

/** Every top-level {...} / [...] block in the text, ignoring braces inside strings. */
function balancedBlocks(text: string): string[] {
  const blocks: string[] = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{" || ch === "[") {
      if (depth === 0) start = i;
      depth++;
      continue;
    }
    if (ch === "}" || ch === "]") {
      depth--;
      if (depth === 0 && start !== -1) {
        blocks.push(text.slice(start, i + 1));
        start = -1;
      }
      if (depth < 0) depth = 0;
    }
  }
  return blocks;
}

const CLOSERS: Record<string, string> = { "{": "}", "[": "]" };

/** Parses one JSON value, applying repairs only if the strict parse fails. */
function tryParse(text: string): unknown | undefined {
  try {
    return JSON.parse(text);
  } catch {
    // fall through to repair
  }
  for (const candidate of balancedBlocks(text)) {
    try {
      return JSON.parse(candidate);
    } catch {
      // keep looking
    }
    const repaired = repairJson(candidate);
    try {
      return JSON.parse(repaired);
    } catch {
      // keep looking
    }
  }
  const repaired = repairJson(text).replace(/,\s*([}\]])/g, "$1");
  try {
    return JSON.parse(repaired);
  } catch {
    return undefined;
  }
}

/** Resiliently extracts a JSON object from an LLM response. */
export function parseJson<T = unknown>(raw: string): T {
  const text = raw
    .trim()
    .replace(/^```(?:json)?/i, "")
    .replace(/```$/i, "")
    .trim();
  const direct = tryParse(text);
  if (direct !== undefined && (Array.isArray(direct) || (direct && typeof direct === "object"))) {
    return direct as T;
  }
  // Last resort: an unterminated leading value whose tail was cut off.
  const first = text.search(/[[{]/);
  if (first !== -1) {
    const stack: string[] = [];
    let inString = false;
    let escaped = false;
    for (let i = first; i < text.length; i++) {
      const ch = text[i];
      if (inString) {
        if (escaped) escaped = false;
        else if (ch === "\\") escaped = true;
        else if (ch === '"') inString = false;
        continue;
      }
      if (ch === '"') inString = true;
      else if (ch === "{" || ch === "[") stack.push(ch);
      else if (ch === "}" || ch === "]") stack.pop();
    }
    if (stack.length > 0) {
      let sliced = text.slice(first);
      if (inString) sliced += '"';
      for (let i = stack.length - 1; i >= 0; i--) sliced += CLOSERS[stack[i]];
      const salvaged = tryParse(sliced);
      if (salvaged !== undefined && (Array.isArray(salvaged) || (salvaged && typeof salvaged === "object"))) {
        return salvaged as T;
      }
    }
  }
  const snippet = text.slice(0, 140).replace(/\s+/g, " ");
  const truncated = text.length > 0 && !/[\]}]\s*$/.test(text);
  throw new AIError(
    `AI returned invalid JSON${truncated ? " (response looked cut off)" : ""}: ${snippet}`
  );
}

/** Runs a chat request expecting a JSON object response. */
export async function chatJson<T = unknown>(
  userId: string | null,
  system: string,
  user: string,
  opts: { temperature?: number; maxTokens?: number } = {}
): Promise<T> {
  const cfg = await resolveConfig(userId);
  const content = await chatCompletionWithConfig(
    cfg,
    [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    { ...opts, json: true }
  );
  return parseJson<T>(content);
}

/** Extracts an array of items from an AI JSON reply (array, or wrapped in items/questions). */
function extractArray<T>(parsed: unknown): T[] {
  if (Array.isArray(parsed)) return parsed as T[];
  if (!parsed || typeof parsed !== "object") return [];
  const obj = parsed as Record<string, unknown>;
  for (const key of ["items", "questions"]) {
    if (Array.isArray(obj[key])) return obj[key] as T[];
  }
  // A single object is treated as a one-element array so a model that only
  // returns one item can still be backfilled up to the requested count.
  return [parsed as T];
}

/**
 * Generates one array of results, retrying malformed output. When
 * `targetCount` is provided, it keeps calling the provider until that many
 * items are collected (or attempts run out) — this guarantees batch
 * generation no matter how few items a single response contains.
 */
export async function chatJsonArray<T = unknown>(
  userId: string | null,
  system: string,
  user: string,
  opts: {
    temperature?: number;
    maxTokens?: number;
    targetCount?: number;
    budgetMs?: number;
    onTruncated?: TruncationNotice;
  } = {}
): Promise<T[]> {
  const cfg = await resolveConfig(userId);
  const target = opts.targetCount ?? 0;
  const maxAttempts = Math.min(10, Math.max(3, Math.ceil(target * 0.9) || 3));
  // Scale the ceiling with the work asked for. A flat 5 minutes looked fine on
  // a GPU but falsely timed out slow hosts, where a batch that is progressing
  // normally got reported as a dead model.
  const budgetMs = opts.budgetMs ?? Math.max(300_000, (opts.targetCount ?? 1) * 60_000);
  const startedAt = Date.now();
  const collected: T[] = [];
  const seen = new Set<string>();
  let lastError: AIError | null = null;
  let salvagedTotal = 0;

  // Drops only exact duplicates so a weak local model's near-repeats still
  // count toward the target while literally identical items are not re-spent.
  /** Never let one request outlive the batch deadline. */
  function remainingMs(): number {
    const left = budgetMs - (Date.now() - startedAt);
    return Math.max(5_000, Math.min(180_000, left));
  }

  function dedupe(items: T[]) {
    for (const item of items) {
      const key = JSON.stringify(item).replace(/\s+/g, " ").toLowerCase();
      if (key.length < 8 || seen.has(key)) continue;
      seen.add(key);
      collected.push(item);
    }
  }

  /**
   * Recovers individual items from a response that is not valid JSON as a
   * whole. One malformed question in a batch used to throw away the four good
   * ones with it, which is what made generation look like it "didn't work".
   */
  function salvage(raw: string): T[] {
    const out: T[] = [];
    for (const block of balancedBlocks(raw)) {
      const parsed = tryParse(block);
      if (parsed && typeof parsed === "object") out.push(parsed as T);
    }
    if (out.length === 0) return [];
    salvagedTotal += out.length;
    console.warn(
      `[ai] salvaged ${out.length} question(s) from a response that was not valid JSON as a whole`
    );
    return out;
  }

  for (let attempt = 0; attempt < maxAttempts && (target === 0 || collected.length < target); attempt++) {
    if (Date.now() - startedAt > budgetMs) {
      lastError = new AIError(
        `AI generation gave up after ${Math.round((Date.now() - startedAt) / 1000)}s without a usable answer. ` +
          `The model is too slow for this request — try fewer questions, a smaller model, or free up memory.`
      );
      break;
    }
    let content = "";
    try {
      content = await chatCompletionWithConfig(
        cfg,
        [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        { ...opts, json: true, timeoutMs: remainingMs(), onTruncated: (info) => opts.onTruncated?.(info) }
      );
    } catch (err) {
      lastError = err instanceof AIError ? err : new AIError(String(err));
      continue;
    }
    let items: T[] = [];
    try {
      items = extractArray<T>(parseJson<unknown>(content));
    } catch (err) {
      lastError = err instanceof AIError ? err : new AIError(String(err));
      items = salvage(content);
    }
    dedupe(items);
    if (target > 0 && collected.length >= target) break;
  }

  if (collected.length === 0) {
    throw lastError ?? new AIError("AI returned malformed data");
  }
  if (salvagedTotal > 0) {
    console.warn(`[ai] ${salvagedTotal} question(s) came from repaired JSON`);
  }
  return target > 0 ? collected.slice(0, target) : collected;
}

// ---------------------------------------------------------------- embeddings

export async function embedTexts(userId: string | null, inputs: string[]): Promise<number[][]> {
  const cfg = await resolveConfig(userId);
  const res = await fetch(`${cfg.baseUrl}/embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.apiKey}`,
    },
    body: JSON.stringify({ model: cfg.embeddingModel, input: inputs }),
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

export async function embedText(userId: string | null, input: string): Promise<number[]> {
  const [vec] = await embedTexts(userId, [input]);
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

// ---------------------------------------------------------------- hybrid RAG search

export type RAGResult = {
  chunkId: string;
  materialId: string;
  title: string;
  content: string;
  score: number;
};

/**
 * Retrieves the most relevant material chunks for a query using a hybrid
 * search fused with Reciprocal Rank Fusion (RRF):
 *
 *   1. Lexical channel   — PostgreSQL full-text search (ts_rank)
 *   2. Semantic channel  — embedding cosine similarity
 *   3. Fusion            — 1/(k + rank) summed across both rankings
 *
 * Scoped to the user's own materials. RRF handles the different score
 * distributions of the two channels without needing to normalise them.
 */
export async function ragSearch(
  userId: string,
  queryText: string,
  opts: { knowledgeBaseId?: string | null; examId?: string | null; materialId?: string | null; limit?: number; minScore?: number } = {}
): Promise<RAGResult[]> {
  const limit = opts.limit ?? 5;
  const channelDepth = Math.max(limit * 3, 10);
  const K = 60; // RRF constant

  // An explicit knowledge base scopes retrieval to that library only.
  // Otherwise prefer the exam's own materials, but also include materials
  // uploaded without an exam (they are global prep and apply to every exam).
  const clauses = ["m.user_id = $1", "m.status = 'ready'", "c.content <> ''"];
  const params: unknown[] = [userId, queryText];
  let paramIdx = 2;
  if (opts.materialId) {
    clauses.push(`m.id = $${++paramIdx}`);
    params.push(opts.materialId);
  } else if (opts.knowledgeBaseId) {
    clauses.push(`m.knowledge_base_id = $${++paramIdx}`);
    params.push(opts.knowledgeBaseId);
  } else if (opts.examId) {
    clauses.push(`(m.exam_id = $${++paramIdx} OR m.exam_id IS NULL)`);
    params.push(opts.examId);
  }
  const where = clauses.join(" AND ");

  const rows = await query<{
    id: string;
    material_id: string;
    title: string;
    content: string;
    embedding: number[];
    lex: number;
  }>(
    `SELECT c.id, c.material_id, m.title, c.content, c.embedding,
            ts_rank(to_tsvector('english', c.content), plainto_tsquery('english', $2)) AS lex
     FROM chunks c
     JOIN materials m ON m.id = c.material_id
     WHERE ${where}
     ORDER BY lex DESC`,
    params
  );
  if (rows.length === 0) return [];

  let queryVector: number[] | null = null;
  try {
    queryVector = await embedText(userId, queryText.slice(0, 6000));
  } catch {
    // embeddings unavailable — lexical channel only
  }

  // Semantic channel (embedding cosine similarity)
  const semantic: { row: (typeof rows)[number]; s: number }[] = queryVector
    ? rows
        .map((row) => ({ row, s: cosineSimilarity(queryVector, row.embedding || []) }))
        .filter((x) => x.s > (opts.minScore ?? 0.15))
        .sort((a, b) => b.s - a.s)
        .slice(0, channelDepth)
    : [];

  // Lexical channel (full-text rank)
  const lexical: { row: (typeof rows)[number]; s: number }[] = rows
    .map((row) => ({ row, s: Number(row.lex) || 0 }))
    .filter((x) => x.s > 0)
    .slice(0, channelDepth);

  if (semantic.length === 0 && lexical.length === 0) return [];

  // Reciprocal Rank Fusion
  const rrf = new Map<string, number>();
  const meta = new Map<string, RAGResult>();
  const addChannel = (list: { row: (typeof rows)[number]; s: number }[]) => {
    list.forEach((x, rank) => {
      const bonus = 1 / (K + rank + 1);
      rrf.set(x.row.id, (rrf.get(x.row.id) ?? 0) + bonus);
      if (!meta.has(x.row.id)) {
        meta.set(x.row.id, {
          chunkId: x.row.id,
          materialId: x.row.material_id,
          title: x.row.title,
          content: x.row.content,
          score: 0,
        });
      }
    });
  };
  addChannel(lexical);
  addChannel(semantic);

  return [...rrf.entries()]
    .map(([id, score]) => ({ ...(meta.get(id) as RAGResult), score }))
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}