import * as cheerio from "cheerio";
import { embedTexts } from "@/lib/ai";
import { query } from "@/lib/db";

const MAX_FILE_BYTES = 15 * 1024 * 1024;
const MAX_URL_BYTES = 2 * 1024 * 1024;

export async function extractTextFromFile(
  buffer: Buffer,
  filename: string
): Promise<string> {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  try {
    switch (ext) {
      case "txt":
      case "md":
      case "markdown":
      case "csv":
      case "json":
      case "html":
      case "htm":
        return buffer.toString("utf8");
      case "pdf": {
        const { PDFParse } = await import("pdf-parse");
        const parser = new PDFParse({ data: buffer });
        try {
          const result = await parser.getText();
          return result.text ?? "";
        } finally {
          await parser.destroy().catch(() => {});
        }
      }
      case "docx": {
        const mammoth = await import("mammoth");
        const result = await mammoth.extractRawText({ buffer });
        return result.value ?? "";
      }
      default:
        // Try to decode as plain text, otherwise reject
        return buffer.toString("utf8").replace(/^\uFEFF/, "");
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(`Could not read "${filename}": ${msg}`);
  }
}

/** Fetches a web page and converts it to plain text. */
export async function extractTextFromUrl(url: string): Promise<{ text: string; title: string }> {
  const parsed = new URL(url);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("Only http(s) URLs are supported");
  }
  const res = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      Accept: "text/html,text/plain,*/*",
    },
    redirect: "follow",
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`Failed to fetch URL (${res.status})`);
  const contentType = res.headers.get("content-type") ?? "";
  const body = Buffer.from(await res.arrayBuffer());

  if (body.length > MAX_URL_BYTES) {
    throw new Error("That URL returned too much content to store (max 2MB)");
  }

  if (contentType.includes("text/plain") || contentType.includes("text/markdown")) {
    return { text: body.toString("utf8"), title: parsed.hostname };
  }

  const html = body.toString("utf8");
  const $ = cheerio.load(html);
  $("script, style, noscript, svg, nav, footer, header, iframe, form, aside").remove();
  const title = $("title").first().text().trim() || parsed.hostname;
  const parts: string[] = [];
  $("h1, h2, h3, h4, h5, h6, p, li, pre, code, blockquote, td, th").each(
    (_i, el) => {
      const text = $(el).text().replace(/\s+/g, " ").trim();
      if (text && text.length > 2) parts.push(text);
    }
  );
  const text = parts.join("\n").slice(0, 200_000);
  if (text.length < 40) throw new Error("No readable content found on that page");
  return { text, title };
}

/** Splits text into overlapping chunks of roughly `size` characters. */
export function chunkText(raw: string, size = 1400, overlap = 200): string[] {
  const text = raw.replace(/\r\n/g, "\n").replace(/\s+\n/g, "\n").trim();
  if (!text) return [];
  const paragraphs = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

  const chunks: string[] = [];
  let current = "";
  for (const para of paragraphs) {
    if ((current + "\n\n" + para).length <= size) {
      current = current ? current + "\n\n" + para : para;
      continue;
    }
    if (current) chunks.push(current);
    // Very long paragraphs get split hard
    if (para.length > size) {
      let rest = para;
      while (rest.length > size) {
        chunks.push(rest.slice(0, size));
        rest = rest.slice(size - overlap);
      }
      current = rest;
    } else {
      current = para;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export type StoredChunk = { materialId: string; position: number; content: string };

/** Chunks, embeds and persists content for a material. */
export async function embedAndStoreChunks(
  materialId: string,
  rawText: string
): Promise<{ chunks: number; failed?: number }> {
  const chunks = chunkText(rawText);
  let failed = 0;
  const BATCH = 8;
  for (let i = 0; i < chunks.length; i += BATCH) {
    const batch = chunks.slice(i, i + BATCH);
    let vectors: number[][];
    try {
      vectors = await embedTexts(batch);
    } catch {
      failed += batch.length;
      continue;
    }
    for (let j = 0; j < batch.length; j++) {
      const embedding = vectors[j] ?? [];
      await query(
        `INSERT INTO chunks (material_id, content, position, embedding)
         VALUES ($1, $2, $3, $4::double precision[])`,
        [materialId, batch[j], i + j, embedding]
      );
    }
  }
  return { chunks: chunks.length - failed, failed };
}

export { MAX_FILE_BYTES };
export { MAX_URL_BYTES };