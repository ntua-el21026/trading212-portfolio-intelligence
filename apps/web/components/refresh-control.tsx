"use client";

import { CheckCircle2, RefreshCw } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Notice } from "@trading212/ui";

import type { RefreshRunResponse } from "../lib/contracts";
import { formatDateTime, titleCase } from "../lib/format";

export function RefreshControl({ demo }: Readonly<{ demo: boolean }>) {
  const [isPending, startTransition] = useTransition();
  const [result, setResult] = useState<RefreshRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh(): void {
    setError(null);
    startTransition(async () => {
      try {
        const response = await fetch("/api/refresh", {
          method: "POST",
          headers: { accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error("Refresh request failed");
        }
        setResult((await response.json()) as RefreshRunResponse);
      } catch {
        setResult(null);
        setError(
          "Synchronization could not be started. No portfolio data was changed.",
        );
      }
    });
  }

  return (
    <div className="refresh-control">
      <Button disabled={isPending} onClick={refresh}>
        <RefreshCw
          aria-hidden="true"
          className={isPending ? "spin" : undefined}
          size={17}
        />
        {isPending
          ? "Synchronizing…"
          : demo
            ? "Run demo synchronization"
            : "Synchronize now"}
      </Button>
      {result ? (
        <Notice title="Synchronization completed" tone="positive">
          <p>
            <CheckCircle2 aria-hidden="true" size={15} />{" "}
            {titleCase(result.status)} at{" "}
            {formatDateTime(result.completed_at ?? result.requested_at)}.
          </p>
          {result.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
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
