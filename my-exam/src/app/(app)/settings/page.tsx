import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getUserSettings } from "@/lib/data";
import { aiConfig, aiConfigForUser } from "@/lib/ai";
import { SettingsForm } from "@/components/settings-form";
import { DiagnosticsPanel } from "@/components/diagnostics-panel";
import { eventSummary, listEvents, type DiagLevel } from "@/lib/diagnostics";

export const dynamic = "force-dynamic";

const LEVELS = new Set<DiagLevel>(["info", "warn", "error"]);

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ log?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const { log } = await searchParams;
  const filter: DiagLevel | "all" = LEVELS.has(log as DiagLevel) ? (log as DiagLevel) : "all";

  const [saved, effective, events, summary] = await Promise.all([
    getUserSettings(user.id),
    aiConfigForUser(user.id).catch(() => null),
    listEvents(user.id, { limit: 150, level: filter }),
    eventSummary(user.id),
  ]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Configure the AI model that powers PrepDesk&apos;s generation, feedback and study assistant.
        </p>
      </div>
      <SettingsForm saved={saved ?? null} effective={effective ?? null} envProvider={aiConfig().provider} />
      <DiagnosticsPanel events={events} filter={filter} summary={summary} />
    </div>
  );
}
