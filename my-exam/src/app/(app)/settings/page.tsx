import { redirect } from "next/navigation";
import Link from "next/link";
import { getCurrentUser, isAdmin } from "@/lib/auth";
import { getUserSettings } from "@/lib/data";
import { aiConfig, aiConfigForUser } from "@/lib/ai";
import { SettingsForm } from "@/components/settings-form";
import { DiagnosticsPanel } from "@/components/diagnostics-panel";
import { eventSummary, listEvents, type DiagLevel } from "@/lib/diagnostics";
import { Users, ArrowRight } from "lucide-react";
import { Card } from "@/components/ui";

export const dynamic = "force-dynamic";

const LEVELS = new Set<DiagLevel>(["info", "warn", "error"]);

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ log?: string }>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const admin = isAdmin(user);

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

      {admin && (
        <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300">
              <Users className="h-5 w-5" />
            </div>
            <div>
              <h2 className="font-semibold">Users &amp; access</h2>
              <p className="mt-0.5 text-sm text-foreground/55">
                Approve signed-up accounts, assign admin/user roles and decide which exams and question-bank content
                each user can see and practise.
              </p>
            </div>
          </div>
          <Link href="/users" className="btn btn-primary shrink-0">
            Manage users <ArrowRight className="h-4 w-4" />
          </Link>
        </Card>
      )}

      <SettingsForm saved={saved ?? null} effective={effective ?? null} envProvider={aiConfig().provider} />
      <DiagnosticsPanel events={events} filter={filter} summary={summary} />
    </div>
  );
}
