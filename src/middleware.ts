import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = new Set(["/login", "/register"]);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("token")?.value;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/") ||
    pathname === "/icon.svg" ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  if (pathname === "/login") {
    if (token) {
      return NextResponse.redirect(new URL("/dashboard", request.url));
    }
    return NextResponse.next();
  }

  if (pathname === "/") {
    return NextResponse.redirect(
      new URL(token ? "/dashboard" : "/login", request.url)
    );
  }

  if (!token && !PUBLIC_PATHS.has(pathname)) {
    const login = new URL("/login", request.url);
    login.searchParams.set("from", pathname);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
