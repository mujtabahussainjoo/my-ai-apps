"use client";

import { useEffect, useRef, useState } from "react";
import { Play, Pause, Square, TimerReset } from "lucide-react";
import { logStudy } from "@/lib/actions";

function fmt(sec: number) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

export function StudyTimer() {
  const [active, setActive] = useState(false);
  const [paused, setPaused] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const lastTick = useRef<number>(0);
  const loggedAt = useRef<number>(0);

  useEffect(() => {
    if (!active || paused) return;
    lastTick.current = Date.now();
    const id = setInterval(() => {
      const now = Date.now();
      setElapsed((e) => e + Math.min(60, (now - lastTick.current) / 1000));
      lastTick.current = now;
      if (!loggedAt.current) loggedAt.current = lastTick.current;
      if (now - loggedAt.current >= 60_000) {
        loggedAt.current = now;
        logStudy(60).catch(() => {});
      }
    }, 1000);
    return () => clearInterval(id);
  }, [active, paused]);

  const stop = () => {
    if (elapsed >= 10) logStudy(Math.round(elapsed)).catch(() => {});
    setActive(false);
    setPaused(false);
    setElapsed(0);
    loggedAt.current = 0;
  };

  return (
    <div className="card flex items-center gap-4 p-5">
      <div className="flex-1">
        <div className="label mb-1">Focus timer</div>
        <div className="font-mono text-3xl font-bold tracking-tight tabular-nums">{fmt(Math.round(elapsed))}</div>
      </div>
      <button
        className="btn btn-primary p-3"
        onClick={() => {
          if (!active) {
            setActive(true);
            setPaused(false);
          } else setPaused((p) => !p);
        }}
      >
        {!active ? <Play className="h-5 w-5" /> : paused ? <Play className="h-5 w-5" /> : <Pause className="h-5 w-5" />}
      </button>
      <button className="btn btn-secondary p-3" onClick={stop} disabled={!active && elapsed === 0}>
        <Square className="h-5 w-5" />
      </button>
      {elapsed >= 10 && active === false && (
        <button
          className="btn btn-secondary p-3"
          onClick={() => setElapsed(0)}
          title="Reset"
        >
          <TimerReset className="h-5 w-5" />
        </button>
      )}
    </div>
  );
}