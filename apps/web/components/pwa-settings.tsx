"use client";

import { Button, Surface } from "@trading212/ui";
import { requestPwaInstall, usePwaState } from "../lib/pwa-client";

export function PwaSettings() {
  const state = usePwaState();
  return (
    <Surface className="settings-card" compact>
      <h2>Install &amp; offline access</h2>
      {state.installed ? (
        <p>This app is installed.</p>
      ) : state.canInstall ? (
        <Button
          type="button"
          disabled={state.installing}
          onClick={() => void requestPwaInstall()}
        >
          {state.installing
            ? "Opening install prompt…"
            : "Install Portfolio Intelligence"}
        </Button>
      ) : (
        <p>
          Use your browser menu to install this app or add it to the home screen
          when available. On iPhone or iPad, use Safari’s Share menu, then Add
          to Home Screen.
        </p>
      )}
      {state.installError ? (
        <p role="alert">
          The install prompt could not open. Use your browser’s install menu.
        </p>
      ) : null}
      <p>
        {state.shell === "ready"
          ? "The public offline shell is ready."
          : state.shell === "pending"
            ? "Checking public offline support…"
            : "Offline support is unavailable in this browser or connection."}{" "}
        Private account pages, research and reports require a connection.
      </p>
      <h3>Notifications</h3>
      <p>
        Push notifications are unavailable because delivery is not configured.
        No notification permission is requested.
      </p>
    </Surface>
  );
}
