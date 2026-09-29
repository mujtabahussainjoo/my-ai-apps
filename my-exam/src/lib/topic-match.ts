/**
 * Chooses which topic a question belongs to.
 *
 * Generation used to look the topic up by exact string equality against a name
 * the model returned, from a map that resolved to `null` whenever a material was
 * selected - which is every time, so every question ended up with no topic at
 * all. Matching on the wording of the question instead is both more reliable and
 * not dependent on the model cooperating.
 */

export type MatchableTopic = {
  id: string;
  name: string;
  parentId: string | null;
  parentName?: string | null;
};

const STOP_WORDS = new Set([
  "what", "which", "how", "why", "when", "where", "who", "does", "do", "did", "is", "are", "was",
  "were", "the", "a", "an", "of", "in", "to", "for", "and", "or", "but", "that", "this", "these",
  "those", "it", "its", "you", "your", "yours", "we", "our", "they", "their", "with", "as", "by",
  "on", "at", "from", "be", "been", "being", "can", "could", "will", "would", "should", "may",
  "might", "must", "there", "here", "if", "then", "than", "so", "not", "no", "yes", "about", "into",
  "over", "than", "them", "he", "she", "his", "her", "have", "has", "had", "use", "used", "using",
  "mean", "means", "meanings", "called", "call", "known", "know",
]);

/** Lowercased content words with simple plural folding. */
function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2 && !STOP_WORDS.has(w))
    .map((w) => (w.endsWith("ies") ? `${w.slice(0, -3)}y` : w.endsWith("s") && !w.endsWith("ss") ? w.slice(0, -1) : w));
}

/**
 * Inverse document frequency over the topic set. A question about "sampling"
 * should not be filed under "Tokens" merely because both are mentioned, so terms
 * that appear in many subtopics count for less.
 */
function idf(allDocs: Set<string>[]): Map<string, number> {
  const freq = new Map<string, number>();
  for (const doc of allDocs) for (const t of doc) freq.set(t, (freq.get(t) ?? 0) + 1);
  const n = Math.max(1, allDocs.length);
  const out = new Map<string, number>();
  for (const [t, c] of freq) out.set(t, Math.log(1 + n / c));
  return out;
}

function scoreTopic(text: string, lower: string, topic: MatchableTopic, weights: Map<string, number>): number {
  const name = topic.name.toLowerCase();
  let score = 0;
  // The subtopic name appearing verbatim in the question is the strongest signal.
  if (name.length > 6 && lower.includes(name)) score += 12;
  const own = new Set(tokenize(topic.name));
  const parent = new Set(tokenize(topic.parentName ?? ""));
  for (const t of new Set(tokenize(text))) {
    const w = weights.get(t) ?? 1;
    if (own.has(t)) score += w * 2;
    // A parent match is weaker: it is right at topic level but says nothing
    // about which subtopic, so it is only a tie-breaker.
    if (parent.has(t) && !own.has(t)) score += w * 0.4;
  }
  // Prefer the more specific match when two score equally.
  return score / (1 + own.size * 0.08);
}

export type TopicMatch = { topicId: string; score: number; name: string };

/** Best-scoring topics for a question, strongest first. */
export function rankTopics(
  text: string,
  topics: MatchableTopic[],
  options: { limit?: number; minScore?: number } = {}
): TopicMatch[] {
  const { limit = 3, minScore = 2.5 } = options;
  if (!text || topics.length === 0) return [];
  const docs = topics.map((t) => new Set([...tokenize(t.name), ...tokenize(t.parentName ?? "")]));
  const weights = idf(docs);
  const lower = text.toLowerCase();
  return topics
    .map((t) => ({ topicId: t.id, name: t.name, score: scoreTopic(text, lower, t, weights) }))
    .filter((r) => r.score >= minScore)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

/** The single best topic, or null when nothing is a convincing match. */
export function matchTopic(
  text: string,
  topics: MatchableTopic[],
  options: { minScore?: number } = {}
): string | null {
  return rankTopics(text, topics, { ...options, limit: 1 })[0]?.topicId ?? null;
}
