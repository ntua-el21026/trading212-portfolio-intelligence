"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { parseAlertUrl } from "../lib/alert-query";

const subscribe = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

export function AlertQueryBoundary({
  children,
  fallback,
}: Readonly<{ children: ReactNode; fallback: ReactNode }>) {
  const search = useSearchParams();
  const hydrated = useSyncExternalStore(
    subscribe,
    clientSnapshot,
    serverSnapshot,
  );
  try {
    // Preserve server HTML during hydration, then validate keys omitted by server props.
    if (hydrated) parseAlertUrl(search);
  } catch {
    return fallback;
  }
  return children;
}
