"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import {
  submitAggregationCommand,
  type AggregationCommand,
  type AggregationCommandResult,
} from "../lib/aggregation-actions";
import { useNavigationVersionRef } from "./navigation-intent";
export function useAggregationCommand(
  done: (value: Extract<AggregationCommandResult, { ok: true }>) => void,
) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<{ code: string; message: string } | null>(
    null,
  );
  const identity = useRef<{ payload: string; key: string } | null>(null);
  const alive = useRef(true);
  const navigation = useNavigationVersionRef();
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  function submit(build: (key: string) => AggregationCommand) {
    if (pending) return;
    const payload = JSON.stringify(build("identity-preview"));
    if (identity.current?.payload !== payload)
      identity.current = { payload, key: crypto.randomUUID() };
    const command = build(identity.current.key),
      intent = navigation.current;
    setError(null);
    start(async () => {
      try {
        const result = await submitAggregationCommand(command);
        if (!alive.current || navigation.current !== intent) return;
        if (result.ok) {
          identity.current = null;
          done(result);
        } else setError({ code: result.code, message: result.message });
      } catch {
        if (alive.current && navigation.current === intent)
          setError({
            code: "SOURCE_UNAVAILABLE",
            message:
              "The request could not complete. Retry preserves its identity.",
          });
      }
    });
  }
  return { pending, error, submit };
}
