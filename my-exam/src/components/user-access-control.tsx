"use client";

import { useState, useTransition } from "react";
import { CheckCircle2, Clock } from "lucide-react";
import { setUserApproval, setContentGrant } from "@/lib/actions";

/**
 * Admin-only per-user access controls: approval toggle plus which content the
 * user may see (the general-knowledge bank and individual exams).
 */
export function UserAccessControl({
  userId,
  approved,
  canManage,
  general,
  grantedExamIds,
  exams,
}: {
  userId: string;
  approved: boolean;
  canManage: boolean;
  general: boolean;
  grantedExamIds: string[];
  exams: { id: string; title: string }[];
}) {
  const [pending, startTransition] = useTransition();
  const [isApproved, setIsApproved] = useState(approved);
  const [granted, setGranted] = useState<Set<string>>(new Set(grantedExamIds));
  const [hasGeneral, setHasGeneral] = useState(general);

  if (!canManage) {
    return (
      <div className="flex items-center gap-2 text-xs text-foreground/55">
        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        {approved ? "Approved" : "Pending approval"}
      </div>
    );
  }

  const run = (action: () => Promise<{ ok: boolean }>, rollback?: () => void) => {
    startTransition(async () => {
      const res = await action();
      if (!res.ok) rollback?.();
    });
  };

  const toggleApproval = (next: boolean) => {
    const prev = isApproved;
    setIsApproved(next);
    run(() => setUserApproval(userId, next), () => setIsApproved(prev));
  };

  const toggleExam = (examId: string, next: boolean) => {
    const prev = new Set(granted);
    setGranted((cur) => {
      const copy = new Set(cur);
      if (next) copy.add(examId);
      else copy.delete(examId);
      return copy;
    });
    run(() => setContentGrant(userId, examId, next), () => setGranted(prev));
  };

  const toggleGeneral = (next: boolean) => {
    const prev = hasGeneral;
    setHasGeneral(next);
    run(() => setContentGrant(userId, null, next), () => setHasGeneral(prev));
  };

  return (
    <div className="space-y-2 rounded-xl border border-white/8 bg-white/3 p-3">
      <label className="flex cursor-pointer items-center gap-2 text-xs font-medium text-foreground/80">
        <input
          type="checkbox"
          checked={isApproved}
          disabled={pending}
          onChange={(e) => toggleApproval(e.target.checked)}
          className="h-3.5 w-3.5 accent-violet-500"
        />
        {isApproved ? (
          <span className="flex items-center gap-1 text-emerald-400">
            <CheckCircle2 className="h-3.5 w-3.5" /> Approved
          </span>
        ) : (
          <span className="flex items-center gap-1 text-amber-300">
            <Clock className="h-3.5 w-3.5" /> Pending approval
          </span>
        )}
      </label>

      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-foreground/45">
          Can see &amp; practise
        </div>
        <div className="space-y-1">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-foreground/75">
            <input
              type="checkbox"
              checked={hasGeneral}
              disabled={pending}
              onChange={(e) => toggleGeneral(e.target.checked)}
              className="h-3.5 w-3.5 accent-violet-500"
            />
            General knowledge question bank
          </label>
          {exams.length === 0 && (
            <p className="text-[11px] text-foreground/45">No exams exist yet — create some first.</p>
          )}
          {exams.map((e) => (
            <label key={e.id} className="flex cursor-pointer items-center gap-2 text-xs text-foreground/75">
              <input
                type="checkbox"
                checked={granted.has(e.id)}
                disabled={pending}
                onChange={(ev) => toggleExam(e.id, ev.target.checked)}
                className="h-3.5 w-3.5 accent-violet-500"
              />
              <span className="truncate">{e.title}</span>
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}