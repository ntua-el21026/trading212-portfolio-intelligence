"use client";

import styles from "./report-view.module.css";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, Notice, Surface } from "@trading212/ui";
import type {
  ExportJobStatus,
  ReportJobStatus,
  PremiumReportJobStatus,
  PremiumReportJobStatusV3,
  PremiumReportJobStatusV4,
} from "@trading212/api-contracts";

import { formatDateTime, titleCase } from "../lib/format";

export function ReportJobStatusCard({
  job,
}: Readonly<{
  job:
    | ReportJobStatus
    | ExportJobStatus
    | PremiumReportJobStatus
    | PremiumReportJobStatusV3
    | PremiumReportJobStatusV4;
}>) {
  const router = useRouter();
  const [polls, setPolls] = useState(0);
  const [pending, startTransition] = useTransition();
  const active = job.state === "queued" || job.state === "running";
  useEffect(() => {
    if (!active || polls >= 60) return;
    const timer = window.setTimeout(() => {
      if (document.visibilityState === "visible")
        startTransition(() => router.refresh());
      setPolls((count) => count + 1);
    }, 5_000);
    return () => window.clearTimeout(timer);
  }, [active, polls, router]);
  return (
    <Surface className={styles.surface} aria-label="Report job status">
      <h2>
        {"report_type" in job
          ? titleCase(job.report_type)
          : `${titleCase(job.dataset)} export`}
      </h2>
      <Notice
        title={`Job ${job.state}`}
        tone={
          job.state === "failed"
            ? "danger"
            : job.state === "succeeded"
              ? "info"
              : "warning"
        }
      >
        <p>
          {active
            ? "Your request is stored. Artifacts become available together after generation completes."
            : job.state === "succeeded"
              ? "Generation completed. Each download rechecks your access and current source permissions."
              : "This job has no downloadable content. Review its state before creating another request."}
        </p>
        {job.failure_code ? <p>Reason: {titleCase(job.failure_code)}</p> : null}
        {active ? (
          <p>
            {polls < 60
              ? "Checking every five seconds while this page is visible."
              : "Automatic checks are paused. Check again when ready."}
          </p>
        ) : null}
      </Notice>
      <dl className={styles.definition}>
        <dt>Job</dt>
        <dd className="mono">{"job_id" in job ? job.job_id : job.export_id}</dd>
        <dt>Requested</dt>
        <dd>{formatDateTime(job.requested_at)}</dd>
        <dt>Expires</dt>
        <dd>{formatDateTime(job.expires_at)}</dd>
        <dt>Completed</dt>
        <dd>
          {job.completed_at
            ? formatDateTime(job.completed_at)
            : "Not completed"}
        </dd>
        <dt>Manifest digest</dt>
        <dd className="mono" style={{ overflowWrap: "anywhere" }}>
          {job.manifest_digest ?? "Not available"}
        </dd>
      </dl>
      {job.context ? (
        <details>
          <summary>Captured inputs and quality</summary>
          <p>
            {job.context.reporting_currency} · valuation{" "}
            {formatDateTime(job.context.valuation_at)} · source cutoff{" "}
            {formatDateTime(job.context.source_cutoff_at)}
          </p>
          <p>
            Quality: {job.context.quality.state} · availability:{" "}
            {job.context.quality.availability}
          </p>
          <p className="mono" style={{ overflowWrap: "anywhere" }}>
            Snapshot {job.context.snapshot_id} · input{" "}
            {job.context.input_digest}
          </p>
          <ul>
            {job.context.pins.map((pin) => (
              <li
                key={`${pin.family}:${pin.role}:${pin.subject_id}`}
                style={{ overflowWrap: "anywhere" }}
              >
                {titleCase(pin.family)} / {titleCase(pin.role)}:{" "}
                {pin.subject_id} · {pin.content_digest}
              </li>
            ))}
          </ul>
          <ul>
            {job.context.quality.warnings.map((warning) => (
              <li key={warning.key}>{warning.text}</li>
            ))}
          </ul>
          <p>
            {job.context.quality.warning_omitted_count} additional warning
            records are retained in the complete manifest.
          </p>
        </details>
      ) : (
        <p>
          The permitted tombstone remains; licensed input detail is no longer
          retained.
        </p>
      )}
      <Button
        variant="secondary"
        disabled={pending}
        onClick={() => {
          setPolls(0);
          startTransition(() => router.refresh());
        }}
      >
        {pending ? "Checking…" : "Check report status"}
      </Button>
    </Surface>
  );
}
