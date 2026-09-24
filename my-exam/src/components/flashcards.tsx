"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FlipHorizontal2, Check, X, Trash2, Loader2, Plus, Wand2, Layers } from "lucide-react";
import { Button, Field } from "@/components/ui";
import { reviewFlashcard, deleteFlashcard, addFlashcard, generateFlashcards } from "@/lib/actions";

type Card = {
  id: string;
  front: string;
  back: string;
  box: number;
  examTitle?: string | null;
  topicName?: string | null;
};

export function FlashReview({ cards, onDone }: { cards: Card[]; onDone?: () => void }) {
  const [order, setOrder] = useState<Card[]>(cards);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [results, setResults] = useState<{ right: number; wrong: number }>({ right: 0, wrong: 0 });
  const [busy, setBusy] = useState(false);

  const card = order[index];

  const rate = async (correct: boolean) => {
    if (!card || busy) return;
    setBusy(true);
    setFlipped(false);
    setResults((r) => ({ ...r, right: r.right + (correct ? 1 : 0), wrong: r.wrong + (correct ? 0 : 1) }));
    await reviewFlashcard(card.id, correct);
    setBusy(false);
    if (index + 1 < order.length) {
      setIndex(index + 1);
      setFlipped(false);
    } else {
      onDone?.();
      setOrder([]);
      setIndex(0);
    }
  };

  if (order.length === 0) {
    return (
      <div className="card flex flex-col items-center gap-2 p-10 text-center">
        <Layers className="h-8 w-8 text-violet-300" />
        <h3 className="text-lg font-semibold">Session complete 🎉</h3>
        <p className="text-sm text-foreground/60">
          {results.right} right · {results.wrong} wrong
        </p>
        <Button variant="secondary" onClick={() => window.location.reload()}>
          Back to deck
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between text-sm text-foreground/55">
        <span>
          Card {index + 1} / {order.length}
        </span>
        <span className="flex gap-2">
          <span className="text-emerald-400">{results.right} ✓</span>
          <span className="text-rose-400">{results.wrong} ✗</span>
        </span>
      </div>

      <button
        onClick={() => setFlipped((f) => !f)}
        className="card relative block min-h-64 w-full cursor-pointer p-8 text-center transition-transform hover:border-violet-400/30"
      >
        {card.examTitle && (
          <span className="absolute left-4 top-3 text-[11px] font-medium uppercase tracking-wider text-foreground/40">
            {card.examTitle}
          </span>
        )}
        {card.topicName && (
          <span className="absolute right-4 top-3 tag">{card.topicName}</span>
        )}
        <div className="flex items-center justify-center gap-1.5 text-xs font-semibold text-foreground/50">
          <FlipHorizontal2 className="h-3.5 w-3.5" /> {flipped ? "Answer" : "Question"} · tap to flip
        </div>
        <p className="mx-auto mt-6 max-w-md text-xl font-semibold leading-relaxed">
          {flipped ? card.back : card.front}
        </p>
        {flipped && (
          <div className="mt-8 flex items-center justify-center gap-3">
            <RatedPill box={card.box + (results.wrong <= 0 ? 1 : 0)} />
          </div>
        )}
      </button>

      {flipped && (
        <div className="grid grid-cols-2 gap-3">
          <Button variant="danger" className="flex-col py-4" onClick={() => rate(false)} disabled={busy}>
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <X className="h-5 w-5" />}
            <span className="text-xs font-normal opacity-80">Again — move back to box 1</span>
          </Button>
          <Button variant="primary" className="flex-col py-4 !bg-emerald-500 !shadow-emerald-900/40" onClick={() => rate(true)} disabled={busy}>
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Check className="h-5 w-5" />}
            <span className="text-xs font-normal opacity-80">Got it — move up the ladder</span>
          </Button>
        </div>
      )}
    </div>
  );
}

function RatedPill({ box }: { box: number }) {
  const labels = ["Box 1 · daily", "Box 2 · every 2d", "Box 3 · every 5d", "Box 4 · every 12d", "Box 5 · every 25d"];
  return <span className="tag text-xs text-violet-300">{labels[Math.min(box, 4)]}</span>;
}

export function AddFlashcardForm({ examId, topics }: { examId: string; topics: { id: string; name: string }[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const fd = new FormData(e.target as HTMLFormElement);
    setBusy(true);
    setErr(null);
    setMsg(null);
    const res = await addFlashcard({
      examId: fd.get("examId") as string | null,
      topicId: (fd.get("topicId") as string) || null,
      front: String(fd.get("front") ?? ""),
      back: String(fd.get("back") ?? ""),
    });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    setMsg("Card added.");
    (e.target as HTMLFormElement).reset();
    router.refresh();
  };

  return (
    <form onSubmit={submit} className="card space-y-4 p-5">
      <input type="hidden" name="examId" value={examId} />
      <h3 className="flex items-center gap-2 font-semibold">
        <Plus className="h-4 w-4 text-emerald-300" /> Add a card
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Front">
          <input name="front" className="input" required placeholder="Question / prompt" />
        </Field>
        <Field label="Back">
          <input name="back" className="input" required placeholder="Answer" />
        </Field>
      </div>
      <Field label="Topic (optional)">
        <select name="topicId" className="input" defaultValue="">
          <option value="">Unassigned</option>
          {topics.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </Field>
      {err && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}
      {msg && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
      <Button type="submit" disabled={busy}>
        {busy && <Loader2 className="h-4 w-4 animate-spin" />} Add card
      </Button>
    </form>
  );
}

export function GenerateFlashcardsPanel({ examId }: { examId: string }) {
  const router = useRouter();
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    const res = await generateFlashcards({ examId: examId || null, topicIds: [], count });
    setBusy(false);
    if (!res.ok) {
      setErr(res.error);
      return;
    }
    const created = (res as { data?: { created?: number } }).data?.created ?? 0;
    setMsg(`Generated ${created} flashcards from your materials.`);
    router.refresh();
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        run();
      }}
      className="card space-y-3 p-5"
    >
      <h3 className="flex items-center gap-2 font-semibold">
        <Wand2 className="h-4 w-4 text-violet-300" /> Generate with AI
      </h3>
      <div className="flex items-end gap-2">
        <div className="w-28">
          <Field label="Count">
            <input type="number" min={1} max={30} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
          </Field>
        </div>
        <Button type="submit" disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
          Generate
        </Button>
      </div>
      {msg && <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">{msg}</div>}
      {err && <div className="rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{err}</div>}
    </form>
  );
}

export function DeleteFlashCardButton({ id }: { id: string }) {
  const router = useRouter();
  return (
    <button
      title="Delete card"
      className="rounded-lg p-1.5 text-foreground/50 opacity-0 transition-opacity hover:bg-rose-500/10 hover:text-rose-400 group-hover:opacity-100"
      onClick={async () => {
        if (!confirm("Delete this card?")) return;
        await deleteFlashcard(id);
        router.refresh();
      }}
    >
      <Trash2 className="h-4 w-4" />
    </button>
  );
}

export function DeckPlayground({
  dueCards,
  recentCards,
}: {
  dueCards: Card[];
  recentCards: Card[];
}) {
  const [mode, setMode] = useState<"list" | "review">("list");
  const router = useRouter();

  if (mode === "review") {
    return <FlashReview cards={dueCards} onDone={() => { setMode("list"); router.refresh(); }} />;
  }

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center justify-between gap-3 p-5">
        <div>
          <h2 className="font-semibold">Today&apos;s review queue</h2>
          <p className="text-sm text-foreground/55">
            {dueCards.length} card{dueCards.length === 1 ? "" : "s"} due for spaced repetition.
          </p>
        </div>
        <Button onClick={() => setMode("review")} disabled={dueCards.length === 0} className="px-6">
          <FlipHorizontal2 className="h-4 w-4" /> Start review
        </Button>
      </div>

      <h3 className="flex items-center gap-2 pt-2 text-sm font-semibold text-foreground/60">
        <Layers className="h-4 w-4" /> Recent cards
      </h3>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {recentCards.map((c) => (
          <div key={c.id} className="card group flex items-start justify-between gap-3 p-4">
            <div className="min-w-0">
              <div className="prose-answer text-sm font-medium leading-snug">{c.front}</div>
              {c.back && <div className="prose-answer mt-1 text-xs text-foreground/55">{c.back}</div>}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {c.examTitle && <span className="tag">{c.examTitle}</span>}
                {c.topicName && <span className="tag">{c.topicName}</span>}
                <span className="tag text-violet-300">Box {min(c.box, 5)}</span>
              </div>
            </div>
            <DeleteFlashCardButton id={c.id} />
          </div>
        ))}
      </div>
    </div>
  );
}

function min(a: number, b: number) {
  return a < b ? a : b;
}