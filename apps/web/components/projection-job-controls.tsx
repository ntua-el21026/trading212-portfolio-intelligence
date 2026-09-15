"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ProjectionRunResponse } from "@trading212/api-contracts";
import { Button } from "@trading212/ui";
import { useProjectionCommand } from "./projection-command";
import { useNavigationVersionRef } from "./navigation-intent";
import styles from "./projection-workspace.module.css";
export function ProjectionJobControls({
  run,
  canWrite,
}: Readonly<{
  run: Pick<ProjectionRunResponse, "id" | "account_id" | "state">;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const navigation = useNavigationVersionRef();
  const polls = useRef(0);
  const [paused, setPaused] = useState(false);
  const [refreshing, refresh] = useTransition();
  const active = run.state === "queued" || run.state === "running";
  const action = useProjectionCommand(() => router.refresh());
  useEffect(() => {
    if (!active || paused || refreshing) return;
    const stamp = navigation.current;
    const timer = setInterval(() => {
      if (
        navigation.current !== stamp ||
        document.visibilityState !== "visible"
      )
        return;
      if (polls.current++ >= 48) {
        setPaused(true);
        return;
      }
      refresh(() => router.refresh());
    }, 5000);
    return () => clearInterval(timer);
  }, [active, paused, refreshing, router, navigation]);
  return (
    <div className={styles.actions} aria-live="polite">
      <span role="status">Projection status: {run.state}</span>
      <Button
        variant="secondary"
        disabled={refreshing}
        onClick={() => {
          polls.current = 0;
          setPaused(false);
          refresh(() => router.refresh());
        }}
      >
        Refresh projection status
      </Button>
      {active && canWrite ? (
        <Button
          variant="secondary"
          disabled={action.pending}
          onClick={() =>
            action.submit((idempotency_key) => ({
              kind: "cancel_run",
              account_id: run.account_id,
              run_id: run.id,
              idempotency_key,
            }))
          }
        >
          {action.pending ? "Cancelling…" : "Cancel projection run"}
        </Button>
      ) : null}
      {paused && active ? (
        <p>
          Automatic refresh paused after four minutes. Refresh status to
          continue.
        </p>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </div>
  );
}
