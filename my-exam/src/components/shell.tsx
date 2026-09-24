"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LayoutDashboard,
  GraduationCap,
  Library,
  NotebookPen,
  Zap,
  Trophy,
  Layers,
  Mic,
  LogOut,
  Menu,
  X,
  FileText,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { logoutAction } from "@/lib/actions";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/exams", label: "Exams & Weightage", icon: GraduationCap },
  { href: "/materials", label: "Training Materials", icon: Library },
  { href: "/question-bank", label: "Question Bank", icon: NotebookPen },
  { href: "/quiz", label: "Practice Quiz", icon: Zap },
  { href: "/mock", label: "Mock Exams", icon: Trophy },
  { href: "/flashcards", label: "Flashcards", icon: Layers },
  { href: "/interview", label: "Interview Coach", icon: Mic },
];

export function AppShell({ userName, children }: { userName: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  const nav = (
    <nav className="flex flex-1 flex-col gap-1 px-3">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => setOpen(false)}
            className={cn(
              "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
              active
                ? "bg-gradient-to-r from-indigo-500/25 to-violet-500/15 text-white ring-1 ring-inset ring-violet-400/25"
                : "text-foreground/65 hover:bg-white/6 hover:text-foreground"
            )}
          >
            <Icon className={cn("h-[18px] w-[18px]", active ? "text-violet-300" : "text-foreground/45 group-hover:text-foreground/80")} />
            {label}
            {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-violet-400" />}
          </Link>
        );
      })}
    </nav>
  );

  const bottom = (
    <div className="mt-auto space-y-3 border-t border-white/8 p-3">
      <div className="flex items-center gap-3 rounded-xl bg-white/4 px-3 py-2.5">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-sm font-bold text-white">
          {userName.slice(0, 1).toUpperCase() || "U"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{userName}</div>
          <div className="flex items-center gap-1 text-[11px] text-emerald-400">
            <TrendingUp className="h-3 w-3" /> actively preparing
          </div>
        </div>
        <form action={logoutAction}>
          <button
            type="submit"
            title="Sign out"
            className="rounded-lg p-1.5 text-foreground/45 transition-colors hover:bg-white/8 hover:text-rose-400"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </form>
      </div>
      <div className="rounded-xl border border-white/8 bg-white/4 p-3 text-[11px] leading-relaxed text-foreground/50">
        <span className="font-semibold text-foreground/80">PrepDesk</span> — study smarter with AI-generated exams built from
        your own materials.
      </div>
    </div>
  );

  return (
    <div className="flex min-h-svh">
      {/* Desktop sidebar */}
      <aside className="glass sticky top-0 hidden h-svh w-64 shrink-0 flex-col border-r border-white/8 md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 shadow-lg shadow-violet-900/40">
            <FileText className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="text-[15px] font-bold leading-none tracking-tight">
              Prep<span className="grad-text">Desk</span>
            </div>
            <div className="mt-1 text-[10px] font-medium uppercase tracking-widest text-foreground/40">AI exam studio</div>
          </div>
        </div>
        {nav}
        {bottom}
      </aside>

      {/* Mobile top bar */}
      <div className="fixed inset-x-0 top-0 z-40 flex items-center justify-between border-b border-white/8 bg-[#0b0b14]/95 px-4 py-3 backdrop-blur md:hidden">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-500">
            <FileText className="h-4 w-4 text-white" />
          </div>
          <span className="font-bold">
            Prep<span className="grad-text">Desk</span>
          </span>
        </div>
        <button onClick={() => setOpen(!open)} className="rounded-lg p-2 text-foreground/70" aria-label="Toggle menu">
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {open && (
        <div className="fixed inset-0 z-30 flex md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="glass relative flex w-72 flex-col py-14">
            {nav}
            {bottom}
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="min-w-0 flex-1 px-4 pb-16 pt-20 sm:px-6 md:pt-8 lg:px-10">
        <div className="mx-auto max-w-6xl">{children}</div>
      </main>
    </div>
  );
}