import { redirect } from "next/navigation";
import { Bot, LibraryBig } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { getChatMessages, getUserSettings } from "@/lib/data";
import { aiConfigForUser } from "@/lib/ai";
import { AssistantChat } from "@/components/assistant-chat";
import { Badge } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function AssistantPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [chat, settings, cfg] = await Promise.all([
    getChatMessages(user.id),
    getUserSettings(user.id),
    aiConfigForUser(user.id).catch(() => null),
  ]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Bot className="h-6 w-6 text-violet-400" />
            AI Assistant
          </h1>
          <p className="mt-1 text-sm text-foreground/60">
            Ask anything about your study materials — answers are grounded in your notes via hybrid RAG search.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge color={cfg?.provider === "openai" ? "sky" : "violet"}>
            {cfg?.provider === "openai" ? "OpenAI" : "Local model"}
          </Badge>
          {cfg && <Badge color="slate">{cfg.model}</Badge>}
          {settings && !settings.assistantEnabled && (
            <Badge color="amber">
              <LibraryBig className="mr-1 h-3 w-3" /> Disabled in Settings
            </Badge>
          )}
        </div>
      </div>

      <AssistantChat
        initialMessages={chat.messages}
        disabled={settings ? !settings.assistantEnabled : false}
      />
    </div>
  );
}