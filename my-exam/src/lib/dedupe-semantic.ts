/**
 * Semantic near-duplicate detection for generated questions.
 *
 * Token overlap alone cannot separate "the basic unit of text that Claude uses"
 * from "the basic unit of input for Claude" (0.5 overlap) from genuinely
 * different questions that share a frame ("the main purpose of the prompt in
 * building X" vs "...of the API pattern in building X"). The app already loads a
 * small embedding model for retrieval, so questions are compared by meaning
 * instead. Embeddings are only requested for the handful of candidates that the
 * cheap lexical check cannot rule out, and any failure falls back to that check.
 */
import { embedTexts } from "@/lib/ai";
import { isNearDuplicate } from "@/lib/generate";

/** Cosine similarity of two equal-length vectors. */
export function cosine(a: number[], b: number[]): number {
  if (a.length !== b.length || a.length === 0) return 0;
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/** Pairs whose embeddings are more similar than `threshold`. */
/**
 * Threshold calibration, measured on the real bank: genuine rephrasings of one
 * question scored 0.78-0.97 while genuinely different questions scored
 * 0.43-0.77, so 0.85 catches the clear repeats without discarding good ones.
 */
export const SEMANTIC_DUPLICATE_THRESHOLD = 0.85;

export function findSemanticDuplicates(
  candidates: string[],
  existing: string[],
  vectors: number[][],
  threshold = SEMANTIC_DUPLICATE_THRESHOLD
): Set<number> {
  const dupes = new Set<number>();
  if (candidates.length === 0 || existing.length === 0) return dupes;
  // `vectors` holds every candidate followed by every existing question, so the
  // existing block starts after the candidate block - not after `existing`.
  const existingOffset = candidates.length;
  for (let i = 0; i < candidates.length; i++) {
    for (let j = 0; j < existing.length; j++) {
      if (cosine(vectors[i], vectors[existingOffset + j]) >= threshold) {
        dupes.add(i);
        break;
      }
    }
  }
  return dupes;
}

/**
 * Which candidate questions duplicate something in `existing`.
 *
 * Returns indices into `candidates`. Lexical duplicates are caught without any
 * model call; the rest are resolved by embedding similarity.
 */
export async function findDuplicateCandidates(
  userId: string | null,
  candidates: string[],
  existing: string[],
  options: { threshold?: number } = {}
): Promise<Set<number>> {
  const dupes = new Set<number>();
  if (candidates.length === 0 || existing.length === 0) return dupes;

  const lexicallyUnclear: number[] = [];
  candidates.forEach((c, i) => {
    if (existing.some((e) => isNearDuplicate(e, c))) dupes.add(i);
    else lexicallyUnclear.push(i);
  });
  if (lexicallyUnclear.length === 0) return dupes;

  try {
    const vectors = await embedTexts(userId, [...lexicallyUnclear.map((i) => candidates[i]), ...existing]);
    const semantic = findSemanticDuplicates(
      lexicallyUnclear.map((i) => candidates[i]),
      existing,
      vectors,
      options.threshold ?? SEMANTIC_DUPLICATE_THRESHOLD
    );
    semantic.forEach((k) => dupes.add(lexicallyUnclear[k]));
  } catch {
    // Embeddings unavailable: the lexical check has already done the work it can.
  }
  return dupes;
}
