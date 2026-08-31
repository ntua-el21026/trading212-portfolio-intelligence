import { NextResponse } from "next/server";

import {
  CSRF_COOKIE,
  revokeApiSession,
  revokeLocalDemoSession,
  SESSION_COOKIE,
} from "../../../../lib/auth";
import { assertSameOrigin, isExplicitDemoMode } from "../../../../lib/runtime";

function cookieValue(header: string | null, name: string): string | undefined {
  return header
    ?.split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    const cookieHeader = request.headers.get("cookie");
    const token = cookieValue(cookieHeader, SESSION_COOKIE);
    const csrfToken = cookieValue(cookieHeader, CSRF_COOKIE);
    if (isExplicitDemoMode()) {
      await revokeLocalDemoSession(token);
    } else if (cookieHeader && csrfToken) {
      try {
        await revokeApiSession(cookieHeader, csrfToken);
      } catch {
        return NextResponse.json(
          {
            error:
              "Server session revocation could not be confirmed. Retry sign-out.",
          },
          { status: 503 },
        );
      }
    }
    const origin = new URL(request.headers.get("origin") ?? request.url);
    const response = NextResponse.redirect(new URL("/sign-in", origin), 303);
    const expiredCookie = {
      expires: new Date(0),
      httpOnly: true,
      path: "/",
      sameSite: "strict",
      secure: origin.protocol === "https:",
    } as const;
    response.cookies.set(SESSION_COOKIE, "", expiredCookie);
    response.cookies.set(CSRF_COOKIE, "", expiredCookie);
    return response;
  } catch {
    return NextResponse.json(
      { error: "Sign-out request rejected." },
      { status: 403 },
    );
  }
}
