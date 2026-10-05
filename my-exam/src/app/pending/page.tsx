import Link from "next/link";
import { ShieldQuestion } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { logoutAction } from "@/lib/actions";
import { Card } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function PendingPage() {
  const user = await getCurrentUser();

  return (
    <div className="flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-md p-8 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-violet-500/15 text-violet-300">
          <ShieldQuestion className="h-6 w-6" />
        </div>
        <h1 className="text-xl font-bold tracking-tight">Account pending approval</h1>
        <p className="mt-2 text-sm text-foreground/60">
          Your account
          {user ? (
            <>
              {" "}
              (<span className="font-medium text-foreground/80">{user.email}</span>)
            </>
          ) : null}{" "}
          is waiting for an admin to approve it. You&apos;ll be able to sign in and study as soon as you&apos;re approved.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Link href="/login" className="btn btn-secondary">
            Back to login
          </Link>
          {user && (
            <form action={logoutAction}>
              <button type="submit" className="btn">
                Sign out
              </button>
            </form>
          )}
        </div>
      </Card>
    </div>
  );
}