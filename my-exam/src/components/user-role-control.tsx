"use client";

import { useState, useTransition } from "react";
import { ShieldCheck } from "lucide-react";
import { setUserRole } from "@/lib/actions";
import { cn } from "@/lib/utils";

export function UserRoleControl({
  userId,
  role,
  changeable,
}: {
  userId: string;
  role: "admin" | "user";
  changeable: boolean;
}) {
  const [current, setCurrent] = useState<"admin" | "user">(role);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const save = (next: "admin" | "user") => {
    if (next === current) {
      setMessage(null);
      return;
    }
    setMessage(null);
    startTransition(async () => {
      const res = await setUserRole(userId, next);
      if (res.ok) setCurrent(next);
      else setMessage(res.error);
    });
  };

  if (!changeable) {
    return (
      <span
        className={cn(
          "badge",
          current === "admin" ? "border-violet-400/40 bg-violet-500/15 text-violet-200" : "border-white/10 bg-white/5"
        )}
      >
        {current === "admin" ? "Admin" : "User"}
      </span>
    );
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex items-center gap-1.5">
        {current === "admin" && <ShieldCheck className="h-3.5 w-3.5 text-violet-300" />}
        <select
          value={current}
          onChange={(e) => save(e.target.value as "admin" | "user")}
          disabled={pending}
          className="input w-auto px-2 py-1.5 text-xs"
          aria-label="Role"
        >
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      {message && <span className="text-[11px] text-rose-400">{message}</span>}
    </div>
  );
}