import { cache } from "react";
import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { queryOne } from "@/lib/db";

export const SESSION_COOKIE = "exam_session";
const SESSION_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

export type Role = "admin" | "user";

export type SessionUser = {
  id: string;
  email: string;
  name: string;
  role: Role;
  approved: boolean;
};

export function isAdmin(user: Pick<SessionUser, "role"> | null): boolean {
  return user?.role === "admin";
}

/** Admins bypass approval; regular users must be approved before using the app. */
export function isApproved(user: Pick<SessionUser, "role" | "approved"> | null): boolean {
  return !!user && (user.approved || isAdmin(user));
}

/**
 * Builds a SQL predicate that scopes rows to the user's own records — or to
 * everything when the user is an admin. The placeholder always sits at
 * `paramIdx` and `params` must contain the user id there, so downstream
 * queries keep their parameter numbering unchanged.
 */
export function scoped(user: Pick<SessionUser, "id" | "role">, column: string, paramIdx = 1): string {
  return isAdmin(user) ? `(${column} = $${paramIdx} OR TRUE)` : `${column} = $${paramIdx}`;
}

function secretKey() {
  const secret = process.env.SESSION_SECRET;
  if (!secret) throw new Error("SESSION_SECRET is not configured");
  return new TextEncoder().encode(secret);
}

export async function createSession(userId: string): Promise<string> {
  const token = await new SignJWT({ sub: userId })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_MAX_AGE}s`)
    .sign(secretKey());
  return token;
}

/** Verifies a token without touching the database (safe for proxy/edge). */
export async function verifyToken(token: string | undefined): Promise<string | null> {
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, secretKey());
    const sub = payload.sub;
    return typeof sub === "string" ? sub : null;
  } catch {
    return null;
  }
}

export async function setSessionCookie(token: string): Promise<void> {
  const store = await cookies();
  store.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
}

export async function deleteSessionCookie(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}

/** Returns the current session user (DB-backed, memoized per request), or null if logged out. */
export const getCurrentUser = cache(async (): Promise<SessionUser | null> => {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;
  const userId = await verifyToken(token);
  if (!userId) return null;
  const user = await queryOne<{ id: string; email: string; name: string; role: string; approved: boolean }>(
    "SELECT id, email, name, role, approved FROM users WHERE id = $1",
    [userId]
  );
  if (!user) return null;
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role === "admin" ? "admin" : "user",
    approved: user.approved,
  };
});

export async function requireUser(): Promise<SessionUser> {
  const user = await getCurrentUser();
  if (!user) {
    throw new Error("UNAUTHORIZED");
  }
  return user;
}

/** Requires a logged-in user with the admin role (throws FORBIDDEN otherwise). */
export async function requireAdmin(): Promise<SessionUser> {
  const user = await requireUser();
  if (!isAdmin(user)) throw new Error("FORBIDDEN");
  return user;
}