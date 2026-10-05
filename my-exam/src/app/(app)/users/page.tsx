import { redirect } from "next/navigation";
import { Users, GraduationCap, NotebookPen, ShieldCheck } from "lucide-react";
import { getCurrentUser, isAdmin } from "@/lib/auth";
import { listUsers, getUserGrants, listExams, GENERAL_EXAM } from "@/lib/data";
import { Card, Badge } from "@/components/ui";
import { UserRoleControl } from "@/components/user-role-control";
import { UserAccessControl } from "@/components/user-access-control";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function UsersAdminPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (!isAdmin(user)) redirect("/dashboard");
  const [users, exams] = await Promise.all([listUsers(), listExams()]);
  const grants = await Promise.all(users.map((u) => getUserGrants(u.id)));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Users &amp; roles</h1>
        <p className="mt-1 text-sm text-foreground/60">
          Approve accounts, assign roles and decide which content each user can see and practise. Admins manage
          everything; users can only view and practise what you share with them.
        </p>
      </div>

      <Card className="overflow-hidden p-0">
        <ul className="divide-y divide-white/8">
          {users.map((u, i) => {
            const own = u.id === user.id;
            const g = grants[i];
            const roleBadge = {
              admin: "border-violet-400/40 bg-violet-500/15 text-violet-200",
              user: "border-white/10 bg-white/5",
            }[u.role];
            return (
              <li key={u.id} className="flex flex-col gap-3 p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-sm font-bold text-white">
                    {u.name.slice(0, 1).toUpperCase() || "U"}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-semibold">{u.name}</span>
                      <span className={`badge ${roleBadge}`}>{u.role === "admin" ? "Admin" : "User"}</span>
                      {own && <span className="tag">you</span>}
                      {u.role !== "admin" && (
                        <Badge color={u.approved ? "emerald" : "amber"}>
                          {u.approved ? "Approved" : "Pending"}
                        </Badge>
                      )}
                    </div>
                    <div className="truncate text-xs text-foreground/55">{u.email}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-foreground/45">
                      <span className="flex items-center gap-1">
                        <GraduationCap className="h-3 w-3" /> {u.examCount} exam{u.examCount === 1 ? "" : "s"}
                      </span>
                      <span className="flex items-center gap-1">
                        <NotebookPen className="h-3 w-3" /> {u.questionCount} question{u.questionCount === 1 ? "" : "s"}
                      </span>
                      <span>Joined {formatDate(u.createdAt)}</span>
                      {u.lastSeen && <span>Active {formatDate(u.lastSeen)}</span>}
                    </div>
                  </div>
                  <div className="sm:w-32">
                    <UserRoleControl userId={u.id} role={u.role} changeable={!own} />
                  </div>
                </div>

                {u.role === "user" && (
                  <div className="grid gap-3 lg:grid-cols-[340px_1fr] lg:items-start">
                    <div className="lg:max-w-80">
                      <UserAccessControl
                        userId={u.id}
                        approved={u.approved}
                        canManage={!own}
                        general={g.general}
                        grantedExamIds={g.examIds}
                        exams={exams.map((e) => ({ id: e.id, title: e.title }))}
                      />
                    </div>
                    <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-foreground/45 lg:pt-2">
                      <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      Once approved, this user sees only the training content checked above — the exam pages, topic
                      weightages, training documents and question bank for those exams ({GENERAL_EXAM} = the
                      general-knowledge bank) — and can practise from them. They cannot edit, upload, generate or
                      delete anything.
                    </p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </Card>

      {users.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-foreground/55">
          <Users className="h-4 w-4" /> No users yet.
        </div>
      )}
    </div>
  );
}