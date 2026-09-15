"use client";
import {
  useEffect,
  useRef,
  useState,
  useTransition,
  type FormEvent,
} from "react";
import { useRouter } from "next/navigation";
import type {
  CreateScenarioRunRequest,
  ScenarioRunResponse,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import { scenarioHref, type ScenarioQuery } from "../lib/scenario-query";
import { useScenarioCommand } from "./scenario-command";
import { useNavigationVersionRef } from "./navigation-intent";
import styles from "./scenario-workspace.module.css";

export function ScenarioRunForm({
  accountId,
  query,
  prepared,
  canWrite,
}: Readonly<{
  accountId: string;
  query: ScenarioQuery;
  prepared: CreateScenarioRunRequest;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const action = useScenarioCommand((result) => {
    if (result.kind === "run")
      router.push(
        scenarioHref(query, {
          view: "result",
          run: result.value.id,
          component_cursor: null,
          runs_cursor: null,
        }),
      );
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    action.submit((idempotency_key) => ({
      kind: "create_run",
      account_id: accountId,
      body: prepared,
      idempotency_key,
    }));
  }
  return (
    <form
      onSubmit={submit}
      className={styles.form}
      aria-label="Create scenario run"
    >
      <p>
        The worker uses these saved inputs and this immutable assumption
        version. Preparation does not calculate a new X-ray.
      </p>
      <Button type="submit" disabled={!canWrite || action.pending}>
        {action.pending ? "Creating scenario run…" : "Create scenario run"}
      </Button>
      {!canWrite ? (
        <Notice title="Additional access required">
          Run creation requires portfolio:read, analytics:read and
          scenarios:write. Historical replay also requires activity:read.
        </Notice>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}

export function ScenarioJobControls({
  run,
  canWrite,
}: Readonly<{ run: ScenarioRunResponse; canWrite: boolean }>) {
  const router = useRouter();
  const navigation = useNavigationVersionRef();
  const polls = useRef(0);
  const [paused, setPaused] = useState(false);
  const [refreshing, refresh] = useTransition();
  const active = run.state === "queued" || run.state === "running";
  const action = useScenarioCommand(() => router.refresh());
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
      <Button
        variant="secondary"
        disabled={refreshing}
        onClick={() => {
          polls.current = 0;
          setPaused(false);
          refresh(() => router.refresh());
        }}
      >
        Refresh scenario status
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
          {action.pending ? "Cancelling…" : "Cancel scenario run"}
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
