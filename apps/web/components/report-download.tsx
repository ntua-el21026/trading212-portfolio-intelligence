"use client";

import { useState } from "react";
import type { ReportArtifactMetadata } from "@trading212/api-contracts";
import { Button } from "@trading212/ui";

export function ReportDownloadButton({
  accountId,
  parentId,
  family,
  artifact,
}: Readonly<{
  accountId: string;
  parentId: string;
  family: "reports" | "exports";
  artifact: ReportArtifactMetadata;
}>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function download() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/${family}/${encodeURIComponent(parentId)}/artifacts/${encodeURIComponent(artifact.artifact_id)}/download`,
        {
          method: "POST",
          redirect: "error",
          cache: "no-store",
          signal: AbortSignal.timeout(30_000),
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ account_id: accountId }),
        },
      );
      if (!response.ok)
        throw new Error(
          response.status === 410
            ? "This artifact expired. Create a new report from available sources."
            : "The download could not complete. Refresh its status and check your access.",
        );
      if (
        response.redirected ||
        response.headers.has("location") ||
        !response.headers
          .get("cache-control")
          ?.split(",")
          .map((value) => value.trim().toLowerCase())
          .includes("no-store") ||
        response.headers.get("x-content-type-options") !== "nosniff" ||
        response.headers.get("content-type") !== artifact.mime_type ||
        response.headers.get("content-length") !==
          String(artifact.byte_length) ||
        response.headers.get("x-artifact-sha256") !== artifact.content_digest
      )
        throw new Error("The artifact could not be verified.");
      const reader = response.body?.getReader();
      if (!reader) throw new Error("The artifact has no content.");
      const chunks: Uint8Array[] = [];
      let length = 0;
      try {
        while (true) {
          const item = await reader.read();
          if (item.done) break;
          length += item.value.byteLength;
          if (length > 10 * 1024 * 1024 || length > artifact.byte_length) {
            await reader.cancel();
            throw new Error("The artifact exceeds its size limit.");
          }
          chunks.push(item.value);
        }
      } finally {
        reader.releaseLock();
      }
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      const digest = Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        (value) => value.toString(16).padStart(2, "0"),
      ).join("");
      if (length !== artifact.byte_length || digest !== artifact.content_digest)
        throw new Error("The artifact could not be verified.");
      const url = URL.createObjectURL(
        new Blob([bytes], { type: artifact.mime_type }),
      );
      try {
        const link = document.createElement("a");
        link.href = url;
        link.download = `portfolio-artifact-${artifact.artifact_id}.${artifact.format}`;
        document.body.append(link);
        link.click();
        link.remove();
      } finally {
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (failure) {
      setError(
        failure instanceof Error &&
          [
            "This artifact expired. Create a new report from available sources.",
            "The download could not complete. Refresh its status and check your access.",
            "The artifact could not be verified.",
            "The artifact has no content.",
            "The artifact exceeds its size limit.",
          ].includes(failure.message)
          ? failure.message
          : "The download could not complete. Your report selection is preserved.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <Button disabled={busy} onClick={download}>
        {busy ? "Downloading…" : `Download ${artifact.format.toUpperCase()}`}
      </Button>
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}
