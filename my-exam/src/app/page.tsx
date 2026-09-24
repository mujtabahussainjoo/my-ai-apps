import Link from "next/link";
import {
  BrainCircuit,
  Zap,
  Library,
  Trophy,
  Layers,
  Mic,
  BarChart3,
  Scale,
  ArrowRight,
  Sparkles,
} from "lucide-react";
import { getCurrentUser } from "@/lib/auth";

const FEATURES = [
  {
    icon: Library,
    title: "Train on your own material",
    body: "Upload PDFs, word docs or paste notes, drop in weblinks. PrepDesk ingests everything into a searchable AI knowledge base.",
  },
  {
    icon: Zap,
    title: "AI question generation",
    body: "Generate MCQs, true/false and short-answer questions grounded in your documents using local or cloud AI.",
  },
  {
    icon: Scale,
    title: "Topic weightage system",
    body: "Assign a weight (%) to each topic. Mocks are built to mirror that exact split, and reports show your per-topic mastery.",
  },
  {
    icon: Trophy,
    title: "Timed mock exams",
    body: "Full-length, timer-driven mock exams weighted by your syllabus, with a detailed score breakdown.",
  },
  {
    icon: Layers,
    title: "Spaced-repetition flashcards",
    body: "AI-built flashcards with a Leitner review ladder so the cards you keep missing resurface sooner.",
  },
  {
    icon: Mic,
    title: "Interview coach",
    body: "AI interviewer that asks realistic questions and grades your answers with STAR feedback.",
  },
  {
    icon: BarChart3,
    title: "Progress dashboard",
    body: "Streaks, study time, accuracy trends and topic-mastery charts to keep you on track.",
  },
  {
    icon: BrainCircuit,
    title: "RAG-powered answers",
    body: "Every generated question is grounded in the materials you trained it on — no made-up facts.",
  },
];

export default async function LandingPage() {
  const user = await getCurrentUser();
  return (
    <div className="relative mx-auto max-w-6xl px-6 pb-24">
      <header className="flex items-center justify-between py-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 shadow-lg shadow-violet-900/40">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <span className="text-lg font-bold tracking-tight">
            Prep<span className="grad-text">Desk</span>
          </span>
        </div>
        <div className="flex items-center gap-3">
          {user ? (
            <Link href="/dashboard" className="btn btn-primary">
              Open dashboard <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <>
              <Link href="/login" className="text-sm font-medium text-foreground/70 hover:text-foreground">
                Log in
              </Link>
              <Link href="/register" className="btn btn-primary">
                Get started
              </Link>
            </>
          )}
        </div>
      </header>

      <section className="grid place-items-center py-20 text-center sm:py-28">
        <div className="rise mb-6 inline-flex items-center gap-2 rounded-full border border-violet-400/25 bg-violet-500/10 px-4 py-1.5 text-xs font-semibold text-violet-300">
          <Sparkles className="h-3.5 w-3.5" />
          Your personal AI exam studio
        </div>
        <h1 className="mx-auto max-w-4xl text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-6xl">
          Ace any exam, certification or interview —{" "}
          <span className="grad-text">built on the material you teach it</span>.
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-base text-foreground/65 sm:text-lg">
          Feed PrepDesk your syllabus, notes, PDFs and weblinks. It generates quizzes, weighted mock exams, flashcards and
          interview practice from your own content — then tracks your mastery topic by topic.
        </p>
        <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
          {user ? (
            <Link href="/dashboard" className="btn btn-primary px-6 py-3 text-base">
              Go to dashboard <ArrowRight className="h-4 w-4" />
            </Link>
          ) : (
            <>
              <Link href="/register" className="btn btn-primary px-6 py-3 text-base">
                Start preparing free <ArrowRight className="h-4 w-4" />
              </Link>
              <Link href="/login" className="btn btn-secondary px-6 py-3 text-base">
                I have an account
              </Link>
            </>
          )}
        </div>
      </section>

      <section
        className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="card group p-5 transition-all hover:-translate-y-1 hover:border-violet-400/30">
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500/20 to-fuchsia-500/20 text-violet-300 ring-1 ring-inset ring-white/10">
              <Icon className="h-5 w-5" />
            </div>
            <h3 className="mb-1.5 font-semibold">{title}</h3>
            <p className="text-sm leading-relaxed text-foreground/60">{body}</p>
          </div>
        ))}
      </section>

      <footer className="mt-24 flex flex-col items-center justify-between gap-3 border-t border-white/8 pt-8 text-sm text-foreground/50 sm:flex-row">
        <span>PrepDesk — 100% local AI optional, your data stays yours.</span>
        <span>Built with Next.js · Ollama · PostgreSQL</span>
      </footer>
    </div>
  );
}