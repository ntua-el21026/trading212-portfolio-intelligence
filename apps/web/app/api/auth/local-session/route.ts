import { NextResponse } from "next/server";

import {
  createLocalApiSession,
  CSRF_COOKIE,
  SESSION_COOKIE,
} from "../../../../lib/auth";
import { assertSameOrigin } from "../../../../lib/runtime";

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    const session = await createLocalApiSession();
    const origin = new URL(request.headers.get("origin") ?? request.url);
    const response = NextResponse.redirect(new URL("/", origin), 303);
    const cookieOptions = {
      expires: session.expiresAt,
      httpOnly: true,
      path: "/",
      sameSite: "strict" as const,
      secure: origin.protocol === "https:",
    };
    response.cookies.set(SESSION_COOKIE, session.token, cookieOptions);
    response.cookies.set(CSRF_COOKIE, session.csrfToken, cookieOptions);
    return response;
  } catch {
    return NextResponse.json(
      { error: "Secure local API access is unavailable." },
      { status: 403 },
    );
  }
}
