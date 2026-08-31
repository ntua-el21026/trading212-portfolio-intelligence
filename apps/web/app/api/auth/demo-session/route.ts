import { NextResponse } from "next/server";

import { createLocalDemoSession, SESSION_COOKIE } from "../../../../lib/auth";
import { assertSameOrigin } from "../../../../lib/runtime";

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    const session = await createLocalDemoSession();
    const origin = new URL(request.headers.get("origin") ?? request.url);
    const response = NextResponse.redirect(new URL("/", origin), 303);
    response.cookies.set(SESSION_COOKIE, session.token, {
      expires: session.expiresAt,
      httpOnly: true,
      path: "/",
      sameSite: "strict",
      secure: origin.protocol === "https:",
    });
    return response;
  } catch {
    return NextResponse.json(
      { error: "Local demo access is unavailable." },
      { status: 403 },
    );
  }
}
