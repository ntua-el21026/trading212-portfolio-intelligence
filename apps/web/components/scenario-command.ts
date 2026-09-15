"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import {
  submitScenarioCommand,
  type ScenarioActionCommand,
  type ScenarioActionResult,
} from "../lib/scenario-actions";
import { useNavigationVersionRef } from "./navigation-intent";

export function useScenarioCommand(
  done: (result: Extract<ScenarioActionResult, { ok: true }>) => void,
) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const identity = useRef<string | null>(null);
  const mounted = useRef(true);
  const navigation = useNavigationVersionRef();
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  function changed() {
    identity.current = null;
    setError(null);
  }
  function submit(build: (idempotencyKey: string) => ScenarioActionCommand) {
    if (pending) return;
    const stamp = navigation.current;
    identity.current ??= crypto.randomUUID();
    const command = build(identity.current);
    setError(null);
    start(async () => {
      try {
        const result = await submitScenarioCommand(command);
        if (!mounted.current || navigation.current !== stamp) return;
        if (result.ok) {
          identity.current = null;
          done(result);
        } else setError(result.message);
      } catch {
        if (mounted.current && navigation.current === stamp)
          setError(
            "The request could not be completed. Retry preserves its identity.",
          );
      }
    });
  }
  return { pending, error, changed, submit };
}
