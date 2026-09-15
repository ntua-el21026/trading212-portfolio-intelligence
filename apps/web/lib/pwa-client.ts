"use client";

import { useSyncExternalStore } from "react";

interface InstallEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}
type PwaState = Readonly<{
  online: boolean;
  installed: boolean;
  canInstall: boolean;
  installing: boolean;
  shell: "pending" | "ready" | "unavailable";
  installError: boolean;
}>;
const initial: PwaState = {
  online: true,
  installed: false,
  canInstall: false,
  installing: false,
  shell: "pending",
  installError: false,
};
let state = initial;
let installEvent: InstallEvent | null = null;
const listeners = new Set<() => void>();
let mounted = false;

function publish(next: Partial<PwaState>) {
  state = { ...state, ...next };
  for (const notify of listeners) notify();
}

export function startPwaClient(): () => void {
  if (mounted) return () => {};
  mounted = true;
  let active = true;
  const media = window.matchMedia("(display-mode: standalone)");
  const connectivity = () => publish({ online: navigator.onLine });
  const installed = () => {
    installEvent = null;
    publish({ installed: true, canInstall: false, installing: false });
  };
  const display = () => publish({ installed: media.matches });
  const beforeInstall = (event: Event) => {
    if (
      !("prompt" in event) ||
      typeof event.prompt !== "function" ||
      !("userChoice" in event)
    )
      return;
    event.preventDefault();
    installEvent = event as InstallEvent;
    publish({ canInstall: true, installError: false });
  };
  connectivity();
  display();
  window.addEventListener("online", connectivity);
  window.addEventListener("offline", connectivity);
  window.addEventListener("beforeinstallprompt", beforeInstall);
  window.addEventListener("appinstalled", installed);
  media.addEventListener("change", display);
  if (window.isSecureContext && "serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .then(() => navigator.serviceWorker.ready)
      .then(() => {
        if (active) publish({ shell: "ready" });
      })
      .catch(() => {
        if (active) publish({ shell: "unavailable" });
      });
  } else publish({ shell: "unavailable" });
  return () => {
    active = false;
    mounted = false;
    installEvent = null;
    window.removeEventListener("online", connectivity);
    window.removeEventListener("offline", connectivity);
    window.removeEventListener("beforeinstallprompt", beforeInstall);
    window.removeEventListener("appinstalled", installed);
    media.removeEventListener("change", display);
    publish({ canInstall: false, installing: false });
  };
}

export async function requestPwaInstall(): Promise<void> {
  const event = installEvent;
  if (!event || state.installing) return;
  installEvent = null;
  publish({ installing: true, canInstall: false, installError: false });
  try {
    await event.prompt();
    const choice = await event.userChoice;
    // Acceptance is not evidence the browser has installed the application;
    // only the appinstalled event or standalone display confirms installation.
    publish({
      installing: false,
      installError: !["accepted", "dismissed"].includes(choice.outcome),
    });
  } catch {
    publish({ installing: false, installError: true });
  }
}

export function usePwaState(): PwaState {
  return useSyncExternalStore(
    (notify) => {
      listeners.add(notify);
      return () => {
        listeners.delete(notify);
      };
    },
    () => state,
    () => initial,
  );
}
