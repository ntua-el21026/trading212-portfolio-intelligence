import { NextResponse } from "next/server";

import { getWebAccess } from "../../../lib/auth";
import { requestRefresh } from "../../../lib/api-adapter";
import { assertSameOrigin } from "../../../lib/runtime";

export async function POST(request: Request) {
  try {
    assertSameOrigin(request);
    if (!(await getWebAccess())) {
      return NextResponse.json(
        { error: "Authentication required." },
        { status: 401 },
      );
    }
    return NextResponse.json(await requestRefresh());
  } catch {
    return NextResponse.json(
      { error: "The read-only synchronization request could not be started." },
      { status: 503 },
    );
  }
}
