import { redirect } from "next/navigation";
import { Layers, Flame } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { listExams, listTopics, listFlashcards } from "@/lib/data";
import { now } from "@/lib/db";
import { EmptyState } from "@/components/ui";
import { DeckPlayground, AddFlashcardForm, GenerateFlashcardsPanel } from "@/components/flashcards";

export const dynamic = "force-dynamic";

export default async function FlashcardsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const exams = await listExams();
  const activeExam = exams[0] ?? null;

  const [allCards, currentTime] = await Promise.all([
    listFlashcards({ limit: 1000 }),
    now(),
  ]);
  const nowMs = currentTime.getTime();
  const dueCards = allCards
    .filter((c) => new Date(c.dueAt).getTime() <= nowMs)
    .sort((a, b) => new Date(a.dueAt).getTime() - new Date(b.dueAt).getTime())
    .slice(0, 30);
  const recentCards = allCards.slice(0, 8);

  const boxes = [0, 1, 2, 3, 4].map(
    (b) => allCards.filter((c) => c.box === b).length
  );

  const topics = activeExam ? await listTopics(activeExam.id) : [];

  const anyDue = dueCards.length > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Flashcards</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Spaced repetition with the Leitner ladder — cards you miss drop back to the daily queue.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        <StatBlock label="Total cards" value={allCards.length} />
        <StatBlock label="Due today" value={dueCards.length} accent={anyDue ? "text-amber-300" : ""} />
        <StatBlock label="Reviews done" value={allCards.reduce((s, c) => s + c.reps, 0)} />
        <div className="card p-4">
          <div className="label mb-2">Deck ladder</div>
          <div className="flex items-end gap-1.5">
            {boxes.map((b, i) => (
              <div key={i} className="flex flex-1 flex-col items-center gap-1">
                <div
                  className="w-full rounded-t-md bg-gradient-to-t from-indigo-500/70 to-violet-400/90 transition-all"
                  style={{ height: `${Math.max(6, (b / Math.max(1, allCards.length)) * 64)}px` }}
                />
                <span className="text-[10px] text-foreground/50">{i + 1}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {anyDue && (
        <div className="flex items-center gap-2 rounded-2xl border border-amber-400/25 bg-amber-500/8 px-4 py-3 text-sm text-amber-200">
          <Flame className="h-4 w-4" />
          You have <strong className="mx-1">{dueCards.length}</strong> card{dueCards.length === 1 ? "" : "s"} to review today —
          {dueCards.length <= 10 ? " a quick win!" : " carve out 5 minutes for the queue."}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <div className="space-y-5">
          {activeExam ? (
            <>
              <GenerateFlashcardsPanel examId={activeExam.id} />
              <AddFlashcardForm examId={activeExam.id} topics={topics} />
            </>
          ) : (
            <EmptyState
              icon={<Layers className="h-6 w-6" />}
              title="Create an exam first"
              description="Flashcards are tied to exams so AI can generate them from that exam's materials."
            />
          )}
        </div>

        <div>
          {allCards.length === 0 ? (
            <EmptyState
              icon={<Layers className="h-6 w-6" />}
              title="No cards yet"
              description="Generate a deck from your training materials, or add your own cards."
            />
          ) : (
            <DeckPlayground dueCards={dueCards} recentCards={recentCards} />
          )}
        </div>
      </div>
    </div>
  );
}

function StatBlock({ label, value, accent = "" }: { label: string; value: number; accent?: string }) {
  return (
    <div className="card p-4">
      <div className={`text-3xl font-bold tracking-tight ${accent}`}>{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wider text-foreground/50">{label}</div>
    </div>
  );
}