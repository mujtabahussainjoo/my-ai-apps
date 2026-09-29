"use client";

import { useEffect, useRef, useState } from "react";
import { useActionState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, Bot, Eraser, Library, Loader2, Send, Sparkles } from "lucide-react";
import { clearAssistantChat, sendChatMessage } from "@/lib/actions";
import type { ChatActionResult } from "@/lib/actions";
import type { ChatMessageRow, ChatSource } from "@/lib/data";
import { cn } from "@/lib/utils";

type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
};

export function AssistantChat({
  initialMessages,
  disabled,
}: {
  initialMessages: ChatMessageRow[];
  disabled: boolean;
}) {
  const router = useRouter();
  const [messages, setMessages] = useState<UiMessage[]>(
    initialMessages.map((m) => ({ id: m.id, role: m.role, content: m.content, sources: m.sources }))
  );
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const [state, sendAction, isPending] = useActionState<ChatActionResult | null, FormData>(
    sendChatMessage,
    null
  );

  // Adjust state during render when the server action result changes
  // (avoids cascading renders from setState-in-effect).
  const [prevResult, setPrevResult] = useState<ChatActionResult | null>(null);
  if (state !== prevResult) {
    setPrevResult(state);
    if (state) {
      if (state.ok) {
        setMessages((m) => [
          ...m,
          { id: `u-${Date.now()}`, role: "user", content: state.userMessage },
          { id: `a-${Date.now()}`, role: "assistant", content: state.reply, sources: state.sources },
        ]);
        setInput("");
        setError(null);
      } else if (state.error) {
        setError(state.error);
      }
    }
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isPending]);

  async function handleClear() {
    const res = await clearAssistantChat();
    if (res.ok) {
      setMessages([]);
      setError(null);
      router.refresh();
    }
  }

  const suggestions = [
    "Summarise the key concepts in my training materials",
    "Quiz me on the topics I've uploaded",
    "Explain the hardest part of my notes simply",
  ];

  return (
    <div className="card flex h-[calc(100svh-230px)] min-h-[500px] flex-col overflow-hidden p-0">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500">
            <Bot className="h-4 w-4 text-white" />
          </div>
          <span>PrepDesk Assistant</span>
          {isPending && <span className="text-xs text-foreground/45">thinking…</span>}
        </div>
        <button
          type="button"
          onClick={handleClear}
          title="Clear conversation"
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-foreground/50 transition-colors hover:bg-white/6 hover:text-foreground"
        >
          <Eraser className="h-3.5 w-3.5" /> Clear
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {!disabled && messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-500/15 text-violet-300">
              <Sparkles className="h-7 w-7" />
            </div>
            <div className="max-w-md space-y-1">
              <p className="text-lg font-semibold">How can I help you study?</p>
              <p className="text-sm text-foreground/60">
                I search your training materials using hybrid retrieval (keyword + semantic) and answer with citations.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setInput(s)}
                  className="rounded-full border border-white/10 bg-white/4 px-3 py-1.5 text-xs text-foreground/70 transition-colors hover:border-violet-400/40 hover:text-violet-200"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {disabled && (
          <div className="flex flex-col items-center justify-center gap-3 px-6 text-center">
            <AlertCircle className="h-8 w-8 text-amber-400" />
            <p className="max-w-md text-sm text-foreground/60">
              The AI Assistant is currently disabled. Enable it from <span className="font-semibold text-foreground/80">Settings →</span>{" "}
              the &ldquo;Enable AI Assistant&rdquo; toggle.
            </p>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={cn("flex gap-2.5", m.role === "user" && "justify-end")}>
            {m.role === "assistant" && (
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
                <Bot className="h-4 w-4" />
              </div>
            )}
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm",
                m.role === "user"
                  ? "bg-gradient-to-r from-indigo-500 to-violet-500 text-white"
                  : "bg-white/6 text-foreground/90"
              )}
            >
              <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
              {m.role === "assistant" && m.sources && m.sources.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-white/10 pt-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-foreground/40">
                    Sources
                  </div>
                  {m.sources.map((s, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-[11px] text-foreground/55">
                      <Library className="mt-0.5 h-3 w-3 shrink-0" />
                      <span className="min-w-0">
                        <span className="truncate font-medium text-foreground/70">{s.title}</span>
                        {s.snippet && <span className="block truncate opacity-80">“{s.snippet}”</span>}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {isPending && (
          <div className="flex gap-2.5">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
              <Bot className="h-4 w-4" />
            </div>
            <div className="rounded-2xl bg-white/6 px-4 py-3">
              <span className="inline-flex gap-1.5">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-foreground/50" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-foreground/50 [animation-delay:0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-foreground/50 [animation-delay:0.3s]" />
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <div className="mx-4 mb-2 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Input */}
      <form action={sendAction} className="border-t border-white/8 p-3">
        <div className="flex items-center gap-2">
          <input
            name="message"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={disabled ? "Assistant is disabled — enable it in Settings" : "Ask about your materials…"}
            disabled={disabled || isPending}
            maxLength={8000}
            className="input flex-1"
          />
          <button
            type="submit"
            disabled={disabled || isPending || !input.trim()}
            className="btn btn-primary shrink-0"
            aria-label="Send"
          >
            {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </form>
    </div>
  );
}