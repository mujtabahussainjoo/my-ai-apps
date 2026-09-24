"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
} from "recharts";
import { formatDate } from "@/lib/utils";

const TOOLTIP_STYLE = {
  background: "#16161f",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: 12,
  fontSize: 12,
  color: "#ececf1",
};

export function AccuracyArea({ data }: { data: { label: string; accuracy: number | null; studyMins: number }[] }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="acc" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.5} />
              <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="label" tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#ececf1" }} formatter={(value, name) => [`${value ?? "—"}%`, name ?? "Accuracy"]} />
          <Area type="monotone" dataKey="accuracy" stroke="#a78bfa" strokeWidth={2} fill="url(#acc)" connectNulls />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function WeightagePie({ data }: { data: { name: string; value: number; color: string }[] }) {
  return (
    <div className="flex items-center gap-4">
      <div className="h-44 w-44 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius={46} outerRadius={72} paddingAngle={3} strokeWidth={0}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.color} />
              ))}
            </Pie>
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value, name) => [`${value ?? 0}%`, name ?? ""]} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex-1 space-y-1.5">
        {data.length === 0 && <li className="text-sm text-foreground/50">No topics yet.</li>}
        {data.map((d) => (
          <li key={d.name} className="flex items-center gap-2 text-sm">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />
            <span className="flex-1 truncate text-foreground/80">{d.name}</span>
            <span className="font-semibold">{d.value}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MasteryBars({ data }: { data: { topic: string; pct: number; total: number; correct: number; color: string }[] }) {
  const all = data.length > 0 ? data : [{ topic: "No practice yet", pct: 0, total: 0, correct: 0, color: "#8b5cf6" }];
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={all} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
          <XAxis dataKey="topic" tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 10 }} axisLine={false} tickLine={false} interval={0} angle={-18} height={40} textAnchor="end" />
          <YAxis domain={[0, 100]} tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(value, name, item) => {
            const payload = (item?.payload ?? {}) as { topic?: string; total?: number; correct?: number };
            return [`${value ?? 0}%`, payload.topic ? `${payload.topic} (${payload.correct}/${payload.total})` : (name ?? "")];
          }} />
          <Bar dataKey="pct" radius={[6, 6, 0, 0]}>
            {all.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MiniSpark({ data, color }: { data: number[]; color: string }) {
  const d = data.map((v, i) => ({ i, v }));
  return (
    <svg viewBox="0 0 100 32" className="h-8 w-full">
      {d.length > 1 && (
        <polyline
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
          points={d.map((p, i) => `${(i / (d.length - 1)) * 100},${32 - p.v * 0.28}`).join(" ")}
        />
      )}
      {d.length > 1 && (
        <polyline
          fill={color}
          opacity={0.12}
          stroke="none"
          points={`0,32 ${d.map((p, i) => `${(i / (d.length - 1)) * 100},${32 - p.v * 0.28}`).join(" ")} 100,32`}
        />
      )}
    </svg>
  );
}

export { formatDate };