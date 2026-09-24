import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, verifyToken } from "@/lib/auth";

const PUBLIC_PATHS = ["/", "/login", "/register"];
const STATIC_STARTS = ["/_next", "/favicon", "/icons", "/fonts", "/images", "/_vercel"];

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isStatic = STATIC_STARTS.some((s) => pathname.startsWith(s));
  if (isStatic) return NextResponse.next();

  const publicPath = PUBLIC_PATHS.includes(pathname);
  const token = request.cookies.get(SESSION_COOKIE)?.value;
  const userId = await verifyToken(token);

  if (!publicPath && !userId) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }

  if (publicPath && userId) {
    // Already signed in — go to dashboard unless it's the root landing page
    if (pathname !== "/") {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|trpc|_next/static|_next/image|favicon.ico).*)"],
};