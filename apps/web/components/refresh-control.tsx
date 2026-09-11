"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { Button, Notice } from "@trading212/ui";

import {
  synchronizationRunSchema,
  type SynchronizationRun,
} from "../lib/refresh-contract";
import { formatDateTime } from "../lib/format";

const presentations = {
  queued: { title: "Synchronization queued", tone: "info" },
  running: { title: "Synchronization running", tone: "info" },
  succeeded: { title: "Synchronization completed", tone: "positive" },
  partial: { title: "Synchronization partially completed", tone: "warning" },
  failed: { title: "Synchronization failed", tone: "danger" },
  cancelled: { title: "Synchronization cancelled", tone: "warning" },
} as const;

export function RefreshControl({
  accountId,
  demo,
}: Readonly<{ accountId: string; demo: boolean }>) {
  return <AccountRefresh key={accountId} accountId={accountId} demo={demo} />;
}

function AccountRefresh({
  accountId,
  demo,
}: Readonly<{ accountId: string; demo: boolean }>) {
  const router = useRouter();
  const request = useRef<AbortController | null>(null);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<SynchronizationRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => request.current?.abort(), []);

  async function refresh(checkRun?: string): Promise<void> {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError(null);
    try {
      const query = new URLSearchParams({ account: accountId });
      if (checkRun) query.set("run", checkRun);
      const response = await fetch(`/api/refresh?${query}`, {
        method: checkRun ? "GET" : "POST",
        headers: { accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok)
        throw new Error("Synchronization response unavailable.");
      const run = synchronizationRunSchema.parse(await response.json());
      if (run.account_id !== accountId || (checkRun && run.id !== checkRun)) {
        throw new Error(
          "Synchronization response does not match the selected run.",
        );
      }
      if (controller.signal.aborted) return;
      setResult(run);
      if (run.status === "succeeded" || run.status === "partial")
        router.refresh();
    } catch {
      if (!controller.signal.aborted) {
        setError(
          "Synchronization status could not be confirmed. Check the existing run before starting another request.",
        );
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  const active = result?.status === "queued" || result?.status === "running";
  const presentation = result ? presentations[result.status] : null;
  return (
    <div className="refresh-control">
      <Button disabled={pending || active} onClick={() => void refresh()}>
        <RefreshCw
          aria-hidden="true"
          className={pending ? "spin" : undefined}
          size={17}
        />
        {pending
          ? "Checking synchronization…"
          : demo
            ? "Run demo synchronization"
            : "Synchronize now"}
      </Button>
      {result && presentation ? (
        <Notice title={presentation.title} tone={presentation.tone}>
          <p>
            {result.completed_at ? "Finished" : "Requested"} at{" "}
            {formatDateTime(result.completed_at ?? result.requested_at)}.
          </p>
          {result.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
          {active ? (
            <Button disabled={pending} onClick={() => void refresh(result.id)}>
              Check status
            </Button>
          ) : null}
        </Notice>
      ) : null}
      {error ? (
        <Notice title="Synchronization unavailable" tone="danger">
          <p>{error}</p>
        </Notice>
      ) : null}
    </div>
  );
}
