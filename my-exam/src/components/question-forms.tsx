"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Wand2, Plus, Trash2 } from "lucide-react";
import { Button, Field, ErrorText } from "@/components/ui";
import { addQuestion, deleteQuestion, generateQuestions } from "@/lib/actions";

type Option = { text: string; correct: boolean };

export function GenerateQuestionsPanel({
  exams,
  examId,
}: {
  exams: { id: string; title: string }[];
  examId: string;
}) {
  const router = useRouter();
  const [selectedExam, setSelectedExam] = useState(examId);
  const [type, setType] = useState("mcq");
  const [count, setCount] = useState(8);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const res = await generateQuestions({
      examId: selectedExam || null,
      topicIds: [],
      type,
      count,
    });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    const created = (res as { data?: { created?: number } }).data?.created ?? 0;
    setMsg(`Added ${created} ${type === "true_false" ? "true/false" : type} question${created === 1 ? "" : "s"} to your bank.`);
    router.refresh();
  };

  return (
    <div className="card space-y-4 p-5">
      <div className="flex items-center gap-2">
        <Wand2 className="h-4 w-4 text-violet-300" />
        <h3 className="font-semibold">Generate with AI</h3>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Exam">
          <select className="input" value={selectedExam} onChange={(e) => setSelectedExam(e.target.value)}>
            <option value="">General knowledge</option>
            {exams.map((e) => (
              <option key={e.id} value={e.id}>
                {e.title}
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
        <Field label="Count">
          <input type="number" min={1} max={20} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
        </Field>
        <div className="flex items-end">
          <Button onClick={run} disabled={busy} className="w-full">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
            Generate
          </Button>
        </div>
      </div>
      {msg && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
      {err && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}
    </div>
  );
}

export function ManualQuestionForm({
  examId,
  topics,
}: {
  examId: string;
  topics: { id: string; name: string }[];
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
        <Field label="Topic">
          <select name="topicId" className="input" defaultValue="">
            <option value="">Unassigned</option>
            {topics.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
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

      {type === "mcq" && (
        <div className="space-y-2">
          <label className="label">Options — select the correct one</label>
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
              />
            </div>
          ))}
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