"use client";

import Link from "next/link";
import { useActionState } from "react";
import { FileText, Loader2, AlertCircle } from "lucide-react";
import { loginAction, registerAction } from "@/lib/actions";
import type { ActionResult } from "@/lib/actions";

function AuthCard({
  mode,
}: {
  mode: "login" | "register";
}) {
  const action = mode === "login" ? loginAction : registerAction;
  const [state, formAction, pending] = useActionState<ActionResult, FormData>(action, {} as ActionResult);
  const isLogin = mode === "login";

  return (
    <div className="flex min-h-svh items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 shadow-xl shadow-violet-900/40">
            <FileText className="h-7 w-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">
            Prep<span className="grad-text">Desk</span>
          </h1>
          <p className="mt-1 text-sm text-foreground/60">
            {isLogin ? "Welcome back — keep the streak alive." : "Create your study space in seconds."}
          </p>
        </div>

        <form action={formAction} className="card space-y-4 p-6">
          {!isLogin && (
            <div>
              <label className="label" htmlFor="name">
                Your name
              </label>
              <input id="name" name="name" className="input" placeholder="Ada Lovelace" autoComplete="name" />
            </div>
          )}
          <div>
            <label className="label" htmlFor="email">
              Email
            </label>
            <input id="email" name="email" className="input" type="email" placeholder="you@example.com" autoComplete="email" />
          </div>
          <div>
            <label className="label" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              name="password"
              className="input"
              type="password"
              placeholder={isLogin ? "••••••••" : "At least 8 characters"}
              autoComplete={isLogin ? "current-password" : "new-password"}
            />
          </div>

          {state && "error" in state && state.error ? (
            <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-sm text-rose-300">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {state.error}
            </div>
          ) : null}

          <button type="submit" disabled={pending} className="btn btn-primary w-full py-3">
            {pending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> One moment…
              </>
            ) : isLogin ? (
              "Log in"
            ) : (
              "Create account"
            )}
          </button>

          <p className="text-center text-sm text-foreground/60">
            {isLogin ? (
              <>
                New here?{" "}
                <Link href="/register" className="font-semibold text-violet-300 hover:text-violet-200">
                  Create an account
                </Link>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <Link href="/login" className="font-semibold text-violet-300 hover:text-violet-200">
                  Log in
                </Link>
              </>
            )}
          </p>
        </form>
      </div>
    </div>
  );
}

export default AuthCard;