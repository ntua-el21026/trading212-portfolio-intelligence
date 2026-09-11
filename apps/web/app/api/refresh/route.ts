import { NextResponse } from "next/server";

import { getWebAccess } from "../../../lib/auth";
import { loadRefreshRun, requestRefresh } from "../../../lib/api-adapter";
import { accountIdSchema } from "../../../lib/account-selection";
import { synchronizationRunSchema } from "../../../lib/refresh-contract";
import { assertSameOrigin } from "../../../lib/runtime";

function parameters(request: Request, check: boolean) {
  const query = new URL(request.url).searchParams;
  const keys = Array.from(query.keys());
  const allowed = check ? ["account", "run"] : ["account"];
  if (
    keys.length !== allowed.length ||
    allowed.some((key) => query.getAll(key).length !== 1)
  ) {
    return null;
  }
  const account = accountIdSchema.safeParse(query.get("account"));
  const run = check ? accountIdSchema.safeParse(query.get("run")) : null;
  if (!account.success || (run && !run.success)) return null;
  return { accountId: account.data, runId: run?.success ? run.data : null };
}

async function respond(request: Request, check: boolean) {
  try {
    if (!check) assertSameOrigin(request);
    if (!(await getWebAccess())) {
      return NextResponse.json(
        { error: "Authentication required." },
        { status: 401, headers: { "Cache-Control": "private, no-store" } },
      );
    }
    const selection = parameters(request, check);
    if (!selection) {
      return NextResponse.json(
        { error: "A valid account and run selection is required." },
        { status: 400, headers: { "Cache-Control": "private, no-store" } },
      );
    }
    const run =
      check && selection.runId
        ? await loadRefreshRun(selection.accountId, selection.runId)
        : await requestRefresh(selection.accountId);
    const parsed = synchronizationRunSchema.parse(run);
    if (
      parsed.account_id !== selection.accountId ||
      (check && parsed.id !== selection.runId)
    ) {
      throw new Error("Synchronization selection mismatch.");
    }
    return NextResponse.json(parsed, {
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "The synchronization status could not be confirmed." },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }
}

export async function POST(request: Request) {
  return respond(request, false);
}
export async function GET(request: Request) {
  return respond(request, true);
}
