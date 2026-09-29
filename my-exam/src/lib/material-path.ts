/**
 * Turning an uploaded file path into a material title.
 *
 * Folder uploads arrive with a relative path like
 * `Anthropic Course/02 Tokens/basics.pdf`, and the folder a file came from is
 * the only thing that distinguishes `intro.pdf` in one chapter from the same
 * filename in another. Titles therefore mirror the folder structure instead of
 * collapsing every file down to its basename.
 */

/** Extensions `extractTextFromFile` can actually turn into text. */
const READABLE_EXTENSIONS = new Set([
  "pdf",
  "txt",
  "md",
  "markdown",
  "csv",
  "json",
  "html",
  "htm",
  "docx",
]);

/** Files that ride along with every folder but are never study material. */
const IGNORED_NAMES = new Set([
  ".ds_store",
  "thumbs.db",
  "desktop.ini",
  ".gitkeep",
  ".gitignore",
  "package.json",
  "package-lock.json",
  "yarn.lock",
  "pnpm-lock.yaml",
]);

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0) return "";
  return name.slice(dot + 1).toLowerCase();
}

/**
 * Builds a material title that mirrors the directory and file pattern exactly as
 * it was uploaded, so the title and the stored source read the same way.
 *
 *   `2. Anthropic/1. Module/MSO Foundations/1. Orientation.md`
 *     -> `2. Anthropic/1. Module/MSO Foundations/1. Orientation`
 *
 * Folder and file names are left exactly as they are — no spaces injected
 * around the separators and no rewriting of `-` or `_` — because those marks are
 * how the material was named on disk. Only the file extension is dropped, since
 * a title reading `...Orientation.md` adds nothing; the full path including the
 * extension is still kept in `source`.
 */
export function titleFromPath(path: string, fallback = "Untitled"): string {
  const segments = path
    .split("/")
    .map((s) => s.trim())
    .filter(Boolean);
  if (segments.length === 0) return fallback;

  const last = segments[segments.length - 1];
  const ext = extensionOf(last);
  const stem = ext ? last.slice(0, last.length - ext.length - 1) : last;
  const cleaned = [...segments.slice(0, -1), stem].filter(Boolean);

  return cleaned.length > 0 ? cleaned.join("/") : fallback;
}

/**
 * Whether a file should be skipped when a whole folder is uploaded.
 *
 * Hidden files, lockfiles and anything `extractTextFromFile` cannot read are
 * reported back to the user rather than silently dropped, because a folder that
 * appears to upload successfully but quietly skips half its files is worse than
 * one that says so.
 */
export function classifyUpload(
  path: string
): { ok: true } | { ok: false; reason: string } {
  const segments = path.split("/").filter(Boolean);
  const name = segments[segments.length - 1] ?? "";
  if (!name) return { ok: false, reason: "no filename" };
  if (name.startsWith(".")) return { ok: false, reason: "hidden file" };
  if (IGNORED_NAMES.has(name.toLowerCase())) return { ok: false, reason: "system or lock file" };
  const ext = extensionOf(name);
  if (!ext) return { ok: false, reason: "no file extension" };
  if (!READABLE_EXTENSIONS.has(ext)) return { ok: false, reason: `.${ext} files are not supported` };
  // Folders that look like build output or version-control metadata.
  const ignoredDir = segments.slice(0, -1).find((s) => /^(node_modules|\.git|\.next|dist|build|__pycache__|\.venv)$/i.test(s));
  if (ignoredDir) return { ok: false, reason: `inside ${ignoredDir}/` };
  return { ok: true };
}

/** Human-readable reason a path is unsupported, for upload feedback. */
export function skipReason(path: string): string | null {
  const verdict = classifyUpload(path);
  return verdict.ok ? null : verdict.reason;
}
