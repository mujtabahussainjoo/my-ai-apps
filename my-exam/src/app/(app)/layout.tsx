import { redirect } from "next/navigation";
import { getCurrentUser, isApproved } from "@/lib/auth";
import { AppShell } from "@/components/shell";

export const dynamic = "force-dynamic";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  if (!isApproved(user)) redirect("/pending");

  return <AppShell userName={user.name} userRole={user.role} userEmail={user.email}>{children}</AppShell>;
}