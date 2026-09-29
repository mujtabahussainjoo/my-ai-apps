"use client";

import { Search } from "lucide-react";
import { Button } from "@/components/ui";

type Option = { value: string; label: string };

/**
 * Question-bank filter bar. Selects re-submit the form on change so the exam /
 * type / topic filters apply immediately; the search box submits on Enter, and
 * the Filter button is a visible affordance for the same action.
 */
export function QuestionBankFilters({
  exams,
  types,
  topics,
  examValue,
  typeValue,
  topicValue,
  qValue,
  modeValue,
}: {
  exams: Option[];
  types: Option[];
  topics: Option[];
  examValue: string;
  typeValue: string;
  topicValue: string;
  qValue: string;
  modeValue: string;
}) {
  const apply = (e: React.ChangeEvent<HTMLSelectElement>) => {
    e.currentTarget.form?.submit();
  };

  return (
    <form action="/question-bank" method="GET" className="flex flex-wrap items-end gap-3">
      <div className="w-full sm:w-56">
        <label className="label" htmlFor="qb-exam">
          Exam
        </label>
        <select id="qb-exam" name="exam" className="input" defaultValue={examValue} onChange={apply}>
          <option value="">All exams</option>
          {exams.map((e) => (
            <option key={e.value} value={e.value}>
              {e.label}
            </option>
          ))}
        </select>
      </div>

      <div className="w-full sm:w-40">
        <label className="label" htmlFor="qb-type">
          Type
        </label>
        <select id="qb-type" name="type" className="input" defaultValue={typeValue} onChange={apply}>
          <option value="">Any type</option>
          {types.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {examValue && topics.length > 0 && (
        <div className="w-full sm:w-56">
          <label className="label" htmlFor="qb-topic">
            Topic
          </label>
          <select id="qb-topic" name="topic" className="input" defaultValue={topicValue} onChange={apply}>
            <option value="">Any topic or subtopic</option>
            {topics.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="min-w-48 flex-1">
        <label className="label" htmlFor="qb-q">
          Search
        </label>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-foreground/40" />
          <input
            id="qb-q"
            name="q"
            className="input pl-9"
            placeholder="Search questions…"
            defaultValue={qValue}
          />
        </div>
      </div>

      <Button type="submit" variant="secondary" className="whitespace-nowrap">
        Filter
      </Button>

      {modeValue === "practice" && <input type="hidden" name="mode" value="practice" />}
    </form>
  );
}