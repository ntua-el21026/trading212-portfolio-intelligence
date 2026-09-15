"use client";

import { useEffect } from "react";
import { startPwaClient, usePwaState } from "../lib/pwa-client";
import styles from "./pwa.module.css";

export function PwaRuntime() {
  useEffect(startPwaClient, []);
  const state = usePwaState();
  return state.online ? null : (
    <aside className={styles.offline} role="status">
      Offline. Displayed information may be stale; reconnect before loading or
      saving changes.
    </aside>
  );
}
