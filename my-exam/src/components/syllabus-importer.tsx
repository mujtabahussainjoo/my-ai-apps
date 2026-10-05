"use client";

import { useActionState, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  FileUp,
  Loader2,
  Scale,
  Sparkles,
  Upload,
  Wand2,
  X,
} from "lucide-react";
import { Button, ErrorText, Field } from "@/components/ui";
import { applySyllabus, balanceTopicWeights, previewSyllabus } from "@/lib/actions";
import type { ActionResult, SyllabusPreview } from "@/lib/actions";
import {
  flattenSyllabus,
  normalizeWeights,
  suggestedPresetFor,
  sumLeafWeight,
  SYLLABUS_PRESETS,
  type SyllabusNode,
} from "@/lib/syllabus";

type Tab = "preset" | "text" | "file";

const EMPTY: ActionResult = {} as ActionResult;

/**
 * Imports a whole syllabus as topics with % weightage.
 *
 * Parsing and writing are deliberately two steps. The parse returns a review
 * tree the user can correct — an AI reading a PDF gets the shape right far more
 * often than it gets the percentages right, and silently writing a plan that
 * sums to 90% is worse than not writing one at all.
 */
export function SyllabusImporter({
  examId,
  examTitle,
  topicCount,
  currentTotal,
}: {
  examId: string;
  examTitle: string;
  topicCount: number;
  currentTotal: number;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("preset");
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(
    previewSyllabus,
    EMPTY
  );
  const [plan, setPlan] = useState<SyllabusNode[] | null>(null);
  const [origin, setOrigin] = useState<string>("");
  const [rawTotal, setRawTotal] = useState<number | null>(null);

  const suggested = useMemo(() => suggestedPresetFor(examTitle), [examTitle]);

  // Lifting a fresh preview into editable state. Adjusting during render rather
  // than in an effect avoids the extra render pass React flags here, and the
  // guard keeps it to exactly once per distinct action result.
  const [seenState, setSeenState] = useState(state);
  if (state !== seenState) {
    setSeenState(state);
    const data = state && "ok" in state && state.ok ? (state.data as SyllabusPreview | undefined) : undefined;
    if (data?.nodes?.length) {
      setPlan(data.nodes);
      setOrigin(data.origin);
      setRawTotal(data.rawTotal);
    }
  }

  if (plan) {
    return (
      <SyllabusReview
        examId={examId}
        plan={plan}
        setPlan={setPlan}
        origin={origin}
        rawTotal={rawTotal}
        topicCount={topicCount}
        onDiscard={() => {
          setPlan(null);
          setRawTotal(null);
          router.refresh();
        }}
      />
    );
  }

  return (
    <div className="card space-y-4 border-violet-400/25 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2">
          <Scale className="mt-0.5 h-4 w-4 text-violet-300" />
          <div>
            <h3 className="font-semibold">Import your syllabus</h3>
            <p className="mt-0.5 text-sm text-foreground/55">
              Brings in every topic with its % weightage, so mocks are drawn in the right proportions.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => router.refresh()}
          className="rounded-lg p-1 text-foreground/50 hover:text-foreground"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {topicCount > 0 && (
        <p className="flex items-start gap-2 rounded-lg border border-amber-400/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This exam already has {topicCount} topic{topicCount === 1 ? "" : "s"} worth {currentTotal}%. Importing
          replaces them.
        </p>
      )}

      <div className="flex flex-wrap gap-1.5">
        {([
          ["preset", "Official blueprint", Sparkles],
          ["text", "Paste syllabus", Wand2],
          ["file", "Upload file", Upload],
        ] as const).map(([key, label, Icon]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              tab === key
                ? "bg-violet-500/20 text-violet-200 border border-violet-400/30"
                : "border border-white/10 text-foreground/60 hover:border-white/20 hover:text-foreground"
            }`}
          >
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </div>

      <form action={formAction} className="space-y-4">
        <input type="hidden" name="examId" value={examId} />

        {tab === "preset" && (
          <div className="space-y-2">
            {SYLLABUS_PRESETS.map((p) => (
              <div
                key={p.id}
                className={`rounded-xl border p-3.5 ${
                  p.id === suggested?.id ? "border-violet-400/30 bg-violet-500/5" : "border-white/8 bg-white/3"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold">{p.label}</div>
                    <div className="mt-0.5 text-[11px] text-foreground/50">{p.source}</div>
                  </div>
                  {p.id === suggested?.id && (
                    <span className="shrink-0 rounded-md bg-violet-500/20 px-1.5 py-0.5 text-[10px] font-bold text-violet-200">
                      MATCHES
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs text-foreground/55">{p.description}</p>
                <input type="hidden" name="presetId" value={p.id} />
                <Button type="submit" className="mt-3 w-full" disabled={pending}>
                  {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Use this blueprint
                </Button>
              </div>
            ))}
            {!suggested && (
              <p className="text-xs text-foreground/45">
                Nothing matched “{examTitle}” automatically — this blueprint still applies if you are preparing for the
                Claude Certified Developer exams.
              </p>
            )}
          </div>
        )}

        {tab === "text" && (
          <>
            <Field label="Syllabus text">
              <textarea
                name="text"
                rows={10}
                className="input font-mono text-xs"
                placeholder={
                  "Domain 1: Applications and Integration — 33.1%\n" +
                  "  Claude Application Design (8.6%)\n" +
                  "  Software Engineering Foundations — 7.4%\n" +
                  "Domain 2: Agents and Workflows — 14.7%\n" +
                  "  Agent Architecture (4.5%)"
                }
                required
              />
            </Field>
            <p className="text-xs text-foreground/45">
              If your outline already shows percentages they are read directly and exactly — no AI needed. Without them,
              the model works out a split from how the document is organised.
            </p>
            <Button type="submit" className="w-full" disabled={pending}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
              {pending ? "Reading syllabus…" : "Read syllabus"}
            </Button>
          </>
        )}

        {tab === "file" && (
          <>
            {/* Without this the action cannot tell an upload from a paste, and
                reads the (absent) `text` field instead of the file. */}
            <input type="hidden" name="kind" value="file" />
            <Field label="Exam guide or syllabus document">
              <input name="file" type="file" accept=".pdf,.txt,.md,.docx,.csv" className="input" required />
            </Field>
            <p className="flex items-start gap-1.5 text-xs text-foreground/45">
              <FileUp className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              PDF, Word, Markdown, text or CSV, up to 15MB. The document is read for its topic list only — it is not
              added to your training materials.
            </p>
            <Button type="submit" className="w-full" disabled={pending}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {pending ? "Reading document…" : "Read document"}
            </Button>
          </>
        )}

        <ErrorText>{state && "error" in state ? state.error : ""}</ErrorText>
      </form>
    </div>
  );
}

function SyllabusReview({
  examId,
  plan,
  setPlan,
  origin,
  rawTotal,
  topicCount,
  onDiscard,
}: {
  examId: string;
  plan: SyllabusNode[];
  setPlan: React.Dispatch<React.SetStateAction<SyllabusNode[] | null>>;
  origin: string;
  rawTotal: number | null;
  topicCount: number;
  onDiscard: () => void;
}) {
  const [mode, setMode] = useState<"replace" | "merge">(topicCount > 0 ? "merge" : "replace");
  const [state, applyAction, pending] = useActionState<ActionResult, FormData>(applySyllabus, EMPTY);
  const wasPending = useRef(false);

  useEffect(() => {
    if (pending) {
      wasPending.current = true;
      return;
    }
    if (!wasPending.current) return;
    wasPending.current = false;
    if (state && "ok" in state && state.ok) onDiscard();
  }, [pending, state, onDiscard]);

  const setLeafWeight = (path: number[], weight: number) => {
    setPlan((prev) => (prev ? withLeafWeight(prev, path, weight) : prev));
  };

  const rows = flattenSyllabus(plan);
  const leafTotal = sumLeafWeight(plan);

  return (
    <div className="card space-y-4 border-violet-400/25 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">Review before saving</h3>
          <p className="mt-0.5 text-xs text-foreground/50">{origin}</p>
          {rawTotal !== null && Math.abs(rawTotal - 100) > 0.5 && (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-amber-300/85">
              <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0" />
              <span>
                The document&apos;s own percentages added up to {Math.round(rawTotal)}%, so they have been rescaled
                to 100%. Edit any weight below if that is not what you want.
              </span>
            </p>
          )}
        </div>
        <Button variant="ghost" onClick={onDiscard} disabled={pending}>
          <X className="h-4 w-4" /> Discard
        </Button>
      </div>

      <div className="max-h-96 space-y-1 overflow-y-auto pr-1">
        {rows.map(({ node, depth }, i) => {
          const path = pathTo(i, plan);
          const isLeaf = !node.children?.length;
          return (
            <div
              key={`${node.name}-${i}`}
              className="flex items-center gap-3 rounded-lg border border-white/8 bg-white/3 px-3 py-2"
              style={{ marginLeft: `${depth * 16}px` }}
            >
              <div className="min-w-0 flex-1">
                <div className={`truncate text-sm ${depth === 0 ? "font-semibold" : "text-foreground/80"}`}>
                  {node.name}
                </div>
                {node.note && <div className="truncate text-[11px] text-foreground/45">{node.note}</div>}
              </div>
              {isLeaf ? (
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={node.weight}
                    onChange={(e) => setLeafWeight(path, Number(e.target.value))}
                    className="input w-16 py-1 text-right text-sm font-bold"
                    aria-label={`Weightage for ${node.name}`}
                  />
                  <span className="text-xs text-foreground/45">%</span>
                </div>
              ) : (
                <span className="shrink-0 text-[11px] text-foreground/40">
                  sum of {node.children?.length} subtopics
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div className="rounded-xl border border-white/8 bg-white/3 p-3.5">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium">Total weightage</span>
          <span
            className={`font-bold tabular-nums ${Math.abs(leafTotal - 100) <= 1 ? "text-emerald-400" : "text-amber-400"}`}
          >
            {leafTotal}% / 100%
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.min(100, leafTotal)}%`,
              background: Math.abs(leafTotal - 100) <= 1 ? "#10b981" : "#f59e0b",
            }}
          />
        </div>
        {Math.abs(leafTotal - 100) > 1 && (
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-foreground/50">
              Weights do not need to be tidy to be saved, but a balanced split makes mocks match the real paper.
            </p>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setPlan(() => normalizeWeights(structuredClone(plan)))}
            >
              <Scale className="h-3.5 w-3.5" /> Rebalance to 100%
            </Button>
          </div>
        )}
      </div>

      <form action={applyAction} className="space-y-3">
        <input type="hidden" name="examId" value={examId} />
        <input type="hidden" name="mode" value={mode} />
        <input type="hidden" name="plan" value={JSON.stringify(plan)} />

        {topicCount > 0 && (
          <div className="flex flex-wrap gap-2">
            {(
              [
                ["merge", "Merge into existing topics", "Updates matching topics by name and leaves the rest alone."],
                ["replace", "Replace all topics", "Clears the current topic tree first. Questions are kept."],
              ] as const
            ).map(([value, label, hint]) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                title={hint}
                className={`flex-1 rounded-lg border px-3 py-2 text-left text-xs transition ${
                  mode === value
                    ? "border-violet-400/40 bg-violet-500/15 text-violet-100"
                    : "border-white/10 text-foreground/55 hover:border-white/20"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
          {pending ? "Saving…" : `Save ${rows.length} topic${rows.length === 1 ? "" : "s"}`}
        </Button>
        <ErrorText>{state && "error" in state ? state.error : ""}</ErrorText>
      </form>

      <BalanceExisting examId={examId} />
    </div>
  );
}

/** Rescales the topics already saved, for plans typed in by hand. */
function BalanceExisting({ examId }: { examId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <button
      type="button"
      className="text-xs text-foreground/45 underline decoration-dotted hover:text-foreground/70"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        setErr(null);
        const res = await balanceTopicWeights({ examId });
        setBusy(false);
        if (!res.ok) {
          setErr(res.error);
          return;
        }
        router.refresh();
      }}
    >
      {busy ? "Rebalancing…" : "Rebalance the topics already saved instead"}
      <ErrorText>{err}</ErrorText>
    </button>
  );
}

/** Index path of the nth flattened row, so a leaf can be edited in place. */
function pathTo(index: number, nodes: SyllabusNode[]): number[] {
  let remaining = index;
  const walk = (list: SyllabusNode[], prefix: number[]): number[] | null => {
    for (let i = 0; i < list.length; i++) {
      if (remaining === 0) return [...prefix, i];
      remaining -= 1;
      const kids = list[i].children ?? [];
      if (kids.length > 0) {
        const found = walk(kids, [...prefix, i]);
        if (found) return found;
      }
    }
    return null;
  };
  return walk(nodes, []) ?? [index];
}

/** Returns a copy of the tree with one leaf's weightage replaced. */
function withLeafWeight(nodes: SyllabusNode[], path: number[], weight: number): SyllabusNode[] {
  const next = structuredClone(nodes);
  let siblings: SyllabusNode[] | undefined = next;
  let target: SyllabusNode | undefined;
  for (const index of path) {
    target = siblings?.[index];
    if (!target) return nodes;
    siblings = target.children;
  }
  if (target) target.weight = Math.max(0, Math.min(100, Math.round(weight) || 0));
  return next;
}
