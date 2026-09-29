"use client";

import { useActionState, useState } from "react";
import { AlertCircle, CheckCircle2, KeyRound, Loader2, Plug, Save, Server } from "lucide-react";
import { saveSettings, testAiConnection } from "@/lib/actions";
import type { ActionResult } from "@/lib/actions";
import type { UserSettingsRow } from "@/lib/data";
import type { AIConfig, AIProvider } from "@/lib/ai";
import { Badge, Card, Field } from "@/components/ui";
import { cn } from "@/lib/utils";

function ProviderCard({
  active,
  onClick,
  icon,
  title,
  desc,
  recommended,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  desc: string;
  recommended?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-start gap-3 rounded-xl border p-4 text-left transition-all",
        active
          ? "border-violet-400/50 bg-violet-500/10 ring-1 ring-inset ring-violet-400/30"
          : "border-white/8 bg-white/4 hover:border-white/20"
      )}
    >
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          active ? "bg-violet-500/20 text-violet-300" : "bg-white/6 text-foreground/60"
        )}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
          {title}
          {recommended && <span className="badge !text-[10px]">Recommended</span>}
        </div>
        <div className="mt-0.5 text-xs leading-relaxed text-foreground/55">{desc}</div>
      </div>
    </button>
  );
}

function testDetail(state: ActionResult | null): string | null {
  if (!state || !state.ok || !state.data || typeof state.data !== "object") return null;
  const d = (state.data as Record<string, unknown>).detail;
  return typeof d === "string" ? d : null;
}

export function SettingsForm({
  saved,
  effective,
  envProvider,
}: {
  saved: UserSettingsRow | null;
  effective: AIConfig | null;
  envProvider: AIProvider;
}) {
  const [provider, setProvider] = useState<AIProvider>(saved?.aiProvider ?? envProvider ?? "local");
  const [saveState, saveAction, savePending] = useActionState<ActionResult, FormData>(saveSettings, {} as ActionResult);
  const [testState, testAction, testPending] = useActionState<ActionResult, FormData>(testAiConnection, {} as ActionResult);

  const isOpenAI = provider === "openai";
  const detail = testDetail(testState);

  return (
    <form action={saveAction} className="space-y-6">
      <Card className="space-y-5">
        <div>
          <h2 className="font-semibold">AI provider</h2>
          <p className="mt-0.5 text-sm text-foreground/60">
            Pick how PrepDesk reaches a model — a local OpenAI-compatible server or OpenAI&apos;s API with your key.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <ProviderCard
            active={provider === "local"}
            onClick={() => setProvider("local")}
            icon={<Server className="h-4 w-4" />}
            title="Local model"
            desc="Ollama, LM Studio or any OpenAI-compatible local server. Keys stay on your machine."
            recommended
          />
          <ProviderCard
            active={provider === "openai"}
            onClick={() => setProvider("openai")}
            icon={<KeyRound className="h-4 w-4" />}
            title="OpenAI (API key)"
            desc="Use gpt-4o-mini / text-embedding-3-small with your OpenAI API key."
          />
        </div>
        <input type="hidden" name="provider" value={provider} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Base URL">
            <input
              name="baseUrl"
              className="input"
              defaultValue={saved?.aiBaseUrl ?? ""}
              placeholder={isOpenAI ? "https://api.openai.com/v1" : "http://localhost:11434/v1"}
              spellCheck={false}
            />
          </Field>
          <Field label={isOpenAI ? "OpenAI API key" : "API key"}>
            <input
              name="apiKey"
              type="password"
              className="input"
              autoComplete="off"
              placeholder={saved?.hasApiKey ? "Saved — leave blank to keep" : isOpenAI ? "sk-…" : "ollama"}
            />
          </Field>
          <Field label="Chat model">
            <input
              name="chatModel"
              className="input"
              defaultValue={saved?.aiModel ?? ""}
              placeholder={isOpenAI ? "gpt-4o-mini" : "llama3.2"}
              spellCheck={false}
            />
          </Field>
          <Field label="Embedding model">
            <input
              name="embeddingModel"
              className="input"
              defaultValue={saved?.aiEmbeddingModel ?? ""}
              placeholder={isOpenAI ? "text-embedding-3-small" : "nomic-embed-text"}
              spellCheck={false}
            />
          </Field>
        </div>

        <label className="flex items-start gap-3 rounded-xl border border-white/8 bg-white/4 px-3.5 py-3">
          <input
            type="checkbox"
            name="assistantEnabled"
            defaultChecked={saved ? saved.assistantEnabled : true}
            className="mt-0.5 h-4 w-4 accent-violet-500"
          />
          <div>
            <div className="text-sm font-medium">Enable AI Assistant</div>
            <div className="text-xs text-foreground/55">
              Allow the study-assistant bot to answer questions using your materials.
            </div>
          </div>
        </label>

        {effective && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/8 bg-black/20 px-3.5 py-2.5 text-xs text-foreground/60">
            <span className="font-medium text-foreground/80">Currently effective:</span>
            <Badge color={effective.provider === "openai" ? "sky" : "violet"}>
              {effective.provider === "openai" ? "OpenAI" : "Local"}
            </Badge>
            <span>{effective.model}</span>
            <span className="hidden truncate text-foreground/40 sm:inline">· {effective.baseUrl}</span>
          </div>
        )}
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={savePending} className="btn btn-primary">
          {savePending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save settings
        </button>
        <button type="submit" formAction={testAction} disabled={testPending || savePending} className="btn btn-secondary">
          {testPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plug className="h-4 w-4" />}
          Test connection
        </button>
      </div>

      <div className="space-y-2">
        {saveState && saveState.ok && (
          <p className="flex items-center gap-2 text-sm text-emerald-400">
            <CheckCircle2 className="h-4 w-4 shrink-0" /> Settings saved.
          </p>
        )}
        {saveState && !saveState.ok && "error" in saveState && saveState.error && (
          <p className="flex items-center gap-2 text-sm text-rose-400">
            <AlertCircle className="h-4 w-4 shrink-0" /> {saveState.error}
          </p>
        )}
        {testState && testState.ok && detail && (
          <p className="flex items-center gap-2 text-sm text-emerald-400">
            <CheckCircle2 className="h-4 w-4 shrink-0" /> {detail}
          </p>
        )}
        {testState && !testState.ok && "error" in testState && testState.error && (
          <p className="flex items-center gap-2 text-sm text-rose-400">
            <AlertCircle className="h-4 w-4 shrink-0" /> Test failed — {testState.error}
          </p>
        )}
      </div>
    </form>
  );
}