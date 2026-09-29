"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Wand2, Plus, Trash2 } from "lucide-react";
import { Button, Field, ErrorText } from "@/components/ui";
import { addQuestion, createTopic, deleteQuestion, generateQuestions } from "@/lib/actions";

type Option = { text: string; correct: boolean };

export function GenerateQuestionsPanel({
  exams,
  examId,
  knowledgeBases,
  defaultKnowledgeBaseId,
  topicsByExam,
  materials,
}: {
  exams: { id: string; title: string }[];
  examId: string;
  knowledgeBases?: { id: string; name: string }[];
  defaultKnowledgeBaseId?: string | null;
  topicsByExam?: Record<string, { id: string; name: string; parentId: string | null }[]>;
  materials?: { id: string; title: string; knowledgeBaseName: string | null }[];
}) {
  const router = useRouter();
  const [selectedExam, setSelectedExam] = useState(examId);
  const [selectedKb, setSelectedKb] = useState(defaultKnowledgeBaseId ?? "");
  const [selectedTopic, setSelectedTopic] = useState("");
  const [selectedMaterial, setSelectedMaterial] = useState("");
  const [type, setType] = useState("mcq");
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const res = await generateQuestions({
      examId: selectedExam || null,
      knowledgeBaseId: selectedKb || null,
      topicIds: selectedMaterial ? [] : selectedTopic ? [selectedTopic] : [],
      materialId: selectedMaterial || null,
      type,
      count,
    });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    const created = (res as { data?: { created?: number }; warning?: string }).data?.created ?? 0;
    const warning = (res as { warning?: string }).warning;
    if (warning) setErr(warning);
    else
      setMsg(
        `Added ${created} ${type === "true_false" ? "true/false" : type} question${created === 1 ? "" : "s"} to your bank.`
      );
    router.refresh();
  };

  // Subtopic options = the titles the user uploaded (chapters/sections).
  const materialOptions = materials ?? [];
  const multiKb = new Set(materialOptions.map((m) => m.knowledgeBaseName)).size > 1;
  const useMaterialTargets = materialOptions.length > 0;
  const topicOptions = buildTopicOptions(topicsByExam?.[selectedExam]);
  // When the exam changes, drop any topic that belongs to the previous exam.
  const effectiveTopic = topicOptions.some((t) => t.id === selectedTopic) ? selectedTopic : "";
  const effectiveMaterial = materialOptions.some((m) => m.id === selectedMaterial) ? selectedMaterial : "";

  const PRESETS = [10, 25, 50, 100, 250, 500, 1000];
  const MAX_COUNT = 1000;
  const setCountSafe = (n: number) => setCount(Math.min(MAX_COUNT, Math.max(1, Math.round(n) || 1)));

  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-center gap-2">
        <Wand2 className="h-4 w-4 text-violet-300" />
        <h3 className="font-semibold">Generate with AI</h3>
      </div>
      {knowledgeBases && knowledgeBases.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Generate from">
            <select className="input" value={selectedKb} onChange={(e) => setSelectedKb(e.target.value)}>
              <option value="">All my training materials</option>
              {knowledgeBases.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Exam">
            <select
              className="input"
              value={selectedExam}
              onChange={(e) => {
                setSelectedExam(e.target.value);
                setSelectedTopic("");
              }}
            >
              <option value="">General knowledge</option>
              {exams.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.title}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_7rem_auto]">
        <Field label="Subtopic">
          <select
            className="input"
            value={useMaterialTargets ? effectiveMaterial : effectiveTopic}
            onChange={(e) => {
              const v = e.target.value;
              if (useMaterialTargets) {
                setSelectedMaterial(v);
                setSelectedTopic("");
              } else {
                setSelectedTopic(v);
                setSelectedMaterial("");
              }
            }}
          >
            <option value="">{useMaterialTargets ? "All my materials" : "All topics"}</option>
            {useMaterialTargets
              ? materialOptions.map((m) => (
                  <option key={m.id} value={m.id}>
                    {multiKb && m.knowledgeBaseName ? `${m.knowledgeBaseName} · ${m.title}` : m.title}
                  </option>
                ))
              : topicOptions.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
          </select>
        </Field>
        <Field label="Type">
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="mcq">Multiple choice</option>
            <option value="true_false">True / false</option>
            <option value="short">Short answer</option>
          </select>
        </Field>
        <Field label="Number of questions">
          <input
            type="number"
            min={1}
            max={MAX_COUNT}
            className="input"
            value={count}
            onChange={(e) => setCountSafe(Number(e.target.value))}
          />
        </Field>
        <div className="flex items-end">
          <Button onClick={run} disabled={busy} className="w-full">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            Generate
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-foreground/50">Pick a count:</span>
        {PRESETS.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => setCountSafe(n)}
            className={`tag cursor-pointer transition-colors ${
              count === n ? "border-violet-400/50 bg-violet-500/15 text-violet-200" : "text-foreground/60 hover:text-foreground"
            }`}
          >
            {n}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-foreground/45">
          Reads your whole material — nothing is skipped. Large counts (e.g. 500–1000) run in batches and save as they go.
        </span>
      </div>
      {msg && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
      {err && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}
    </div>
  );
}

type TopicOption = { id: string; name: string; parentId?: string | null };

/**
 * Creates a topic or subtopic without leaving the question bank, so adding a
 * question to a subtopic is never blocked on a trip to the exam page.
 */
function QuickTopicForm({
  defaultExamId,
  exams,
  topicsByExam,
  onCreated,
}: {
  defaultExamId: string;
  exams: { id: string; title: string }[];
  topicsByExam: Record<string, TopicOption[]>;
  onCreated?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [targetExam, setTargetExam] = useState(defaultExamId || exams[0]?.id || "");
  const [parentId, setParentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setOpen(true);
          setDone(null);
        }}
        className="flex w-full items-center gap-2 rounded-xl border border-dashed border-white/15 px-3 py-2 text-xs text-foreground/60 hover:border-violet-400/40 hover:text-foreground/85"
      >
        <Plus className="h-4 w-4" /> New topic or subtopic
      </button>
    );
  }

  const add = async () => {
    const trimmed = name.trim();
    if (!trimmed || !targetExam) return;
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.set("examId", targetExam);
    fd.set("name", trimmed);
    fd.set("parentId", parentId);
    fd.set("weightage", "10");
    fd.set("description", "");
    const res = await createTopic({} as unknown as FormData, fd);
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    setName("");
    setParentId("");
    setDone(`Added "${trimmed}" — pick it in Topic / subtopic above.`);
    onCreated?.();
  };

  return (
    <div className="space-y-2 rounded-xl border border-white/10 bg-white/3 p-3">
      <p className="text-xs font-semibold">New topic or subtopic</p>
      <input
        className="input"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="e.g. How LLMs Behave"
      />
      <div className="grid gap-2 sm:grid-cols-2">
        <select className="input" value={targetExam} onChange={(e) => setTargetExam(e.target.value)}>
          {exams.map((e) => (
            <option key={e.id} value={e.id}>
              {e.title}
            </option>
          ))}
        </select>
        <select className="input" value={parentId} onChange={(e) => setParentId(e.target.value)}>
          <option value="">— top-level topic —</option>
          {(topicsByExam[targetExam] ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              Subtopic of: {t.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" onClick={add} disabled={busy || !name.trim()}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} Add topic
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            setOpen(false);
            setErr(null);
          }}
        >
          Cancel
        </Button>
      </div>
      {done && <p className="text-xs text-emerald-300">{done}</p>}
      {err && <p className="text-xs text-rose-300">{err}</p>}
    </div>
  );
}

export function ManualQuestionForm({
  examId,
  exams,
  topicsByExam,
}: {
  examId: string;
  exams: { id: string; title: string }[];
  topicsByExam: Record<string, { id: string; name: string; parentId?: string | null }[]>;
}) {
  const router = useRouter();
  const [type, setType] = useState("mcq");
  const [options, setOptions] = useState<Option[]>([
    { text: "", correct: true },
    { text: "", correct: false },
    { text: "", correct: false },
    { text: "", correct: false },
  ]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const topicTotal = Object.values(topicsByExam).reduce((n, list) => n + list.length, 0);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setMsg(null);
    const fd = new FormData();
    fd.set("examId", examId || "");
    fd.set("type", type);
    const form = e.target as HTMLFormElement;
    new FormData(form).forEach((v, k) => fd.set(k, v));
    if (type === "mcq") {
      options.forEach((_, i) => fd.set(`option${i + 1}`, options[i].text));
      fd.set("correctIndex", String(options.findIndex((o) => o.correct)));
    }
    const res = await addQuestion({} as unknown as FormData, fd);
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    setMsg("Question added.");
    form.reset();
    router.refresh();
  };

  return (
    <form onSubmit={submit} className="card space-y-4 p-5">
      <div className="flex items-center gap-2">
        <Plus className="h-4 w-4 text-emerald-300" />
        <h3 className="font-semibold">Add a question manually</h3>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Type">
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="mcq">Multiple choice</option>
            <option value="true_false">True / false</option>
            <option value="short">Short answer</option>
            <option value="interview">Interview</option>
          </select>
        </Field>
        <Field label="Topic / subtopic">
          <select name="topicId" className="input" defaultValue="">
            <option value="">Unassigned</option>
            {exams.map((e) => {
              const list = topicsByExam[e.id] ?? [];
              if (list.length === 0) return null;
              return (
                <optgroup key={e.id} label={e.title}>
                  {list.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.parentId ? `↳ ${t.name}` : t.name}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </select>
        </Field>
        <Field label="Category (optional)">
          <input name="category" className="input" placeholder="e.g. security" />
        </Field>
      </div>

      <Field label={type === "true_false" ? "Statement" : "Question"}>
        <textarea
          name="prompt"
          className="input"
          rows={2}
          required
          placeholder={type === "true_false" ? "HTTP is stateless by design." : "Type the question…"}
        />
      </Field>

      {topicTotal === 0 && (
        <p className="rounded-xl border border-amber-400/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          This exam has no topics yet, so questions can&apos;t be filed under a subtopic. Create one
          below — or add topics on the exam page.
        </p>
      )}

      <QuickTopicForm
        defaultExamId={examId}
        exams={exams}
        topicsByExam={topicsByExam}
        onCreated={() => router.refresh()}
      />

      {type === "mcq" && (
        <div className="space-y-2">
          <label className="label">Options — 4 or 5, select the correct one</label>
          {options.map((opt, i) => (
            <div key={i} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setOptions(options.map((o, j) => ({ ...o, correct: j === i })))}
                className={`h-9 w-9 shrink-0 rounded-lg border text-xs font-bold ${
                  opt.correct
                    ? "border-emerald-400/50 bg-emerald-500/15 text-emerald-300"
                    : "border-white/10 bg-white/4 text-foreground/50"
                }`}
                title="Mark correct"
              >
                {opt.correct ? "✓" : String.fromCharCode(65 + i)}
              </button>
              <input
                className="input"
                value={opt.text}
                onChange={(e) => setOptions(options.map((o, j) => (j === i ? { ...o, text: e.target.value } : o)))}
                placeholder={`Option ${String.fromCharCode(65 + i)}`}
                required={i < 4}
              />
              {options.length > 4 && (
                <button
                  type="button"
                  onClick={() => {
                    const wasCorrect = options[i].correct;
                    const next = options.filter((_, j) => j !== i);
                    setOptions(wasCorrect ? next.map((o, j) => ({ ...o, correct: j === 0 })) : next);
                  }}
                  className="h-9 w-9 shrink-0 rounded-lg border border-white/10 bg-white/4 text-foreground/50 hover:border-rose-400/40 hover:text-rose-300"
                  title="Remove option"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
          {options.length < 5 && (
            <Button type="button" variant="secondary" onClick={() => setOptions([...options, { text: "", correct: false }])}>
              <Plus className="h-4 w-4" /> Add 5th option
            </Button>
          )}
          {options.length < 4 && (
            <p className="text-xs text-rose-300">An MCQ needs at least 4 options.</p>
          )}
        </div>
      )}

      {type === "true_false" && (
        <Field label="Correct answer">
          <select name="correct" className="input" defaultValue="true">
            <option value="true">True</option>
            <option value="false">False</option>
          </select>
        </Field>
      )}

      {(type === "short" || type === "interview") && (
        <Field label="Model answer">
          <textarea name="answer" className="input" rows={3} required placeholder="The model answer / ideal response…" />
        </Field>
      )}

      <Field label="Explanation (optional)">
        <input name="explanation" className="input" placeholder="Why the answer is correct" />
      </Field>

      <ErrorText>{err}</ErrorText>
      {msg && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}

      <div className="flex justify-end">
        <Button type="submit" disabled={busy}>
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          Add to bank
        </Button>
      </div>
    </form>
  );
}

export function DeleteQuestionButton({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="rounded-lg p-2 text-foreground/50 hover:bg-rose-500/10 hover:text-rose-400"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Delete this question?")) return;
        setBusy(true);
        await deleteQuestion(id);
        router.refresh();
      }}
      title="Delete"
    >
      <Trash2 className="h-4 w-4" />
    </button>
  );
}
function buildTopicOptions(
  topics?: { id: string; name: string; parentId: string | null }[]
): { id: string; name: string; depth: number }[] {
  if (!topics || topics.length === 0) return [];
  const byId = new Map(topics.map((t) => [t.id, t]));
  const parentIds = new Set(topics.map((t) => t.parentId).filter(Boolean));
  // Generate only into subtopics (leaf topics). A topic that has children is
  // a group, not a generation target.
  return topics
    .filter((t) => !parentIds.has(t.id))
    .map((t) => {
      const parent = t.parentId ? byId.get(t.parentId) : undefined;
      return {
        id: t.id,
        name: parent ? `${parent.name} → ${t.name}` : t.name,
        depth: 0,
      };
    });
}
