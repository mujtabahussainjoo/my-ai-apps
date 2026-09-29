"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { setQuestionTopic } from "@/lib/actions";
import type { TopicNode } from "@/lib/data";

/**
 * Lets a question be filed under a different topic or subtopic.
 *
 * Most questions are filed automatically from their wording, but a question
 * about, say, storing an API key shares no vocabulary with any subtopic name,
 * so it stays uncategorised until someone puts it where it belongs.
 */
export function QuestionTopicSelect({
  questionId,
  topics,
  value,
}: {
  questionId: string;
  topics: TopicNode[];
  value: string | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  if (topics.length === 0) return null;

  return (
    <label className="mt-2 flex items-center gap-1.5 text-[11px] text-foreground/50">
      <span className="shrink-0">Filed under</span>
      <select
        aria-label="Topic for this question"
        disabled={pending}
        value={value ?? ""}
        onChange={(e) => {
          const next = e.target.value || null;
          startTransition(async () => {
            await setQuestionTopic(questionId, next);
            router.refresh();
          });
        }}
        className="min-w-0 flex-1 rounded border border-white/10 bg-white/5 px-1.5 py-1 text-[11px] text-foreground/80 outline-none focus:border-white/25 disabled:opacity-50"
      >
        <option value="">Uncategorised</option>
        {topics.map((t) => (
          <optgroup key={t.id} label={t.name}>
            <option value={t.id}>{t.name} (topic)</option>
            {(t.children ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                ↳ {c.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {pending && <span className="shrink-0">saving…</span>}
    </label>
  );
}
