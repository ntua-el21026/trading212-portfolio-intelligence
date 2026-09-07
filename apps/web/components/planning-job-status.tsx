"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ContributionPlanJob } from "@trading212/api-contracts";
import { Notice } from "@trading212/ui";

import { titleCase } from "../lib/format";

export function PlanningJobStatus({
  job,
  paused = false,
}: Readonly<{ job: ContributionPlanJob; paused?: boolean }>) {
  const router = useRouter();
  const [polls, setPolls] = useState(0);
  const [pending, startTransition] = useTransition();
  const active = job.state === "queued" || job.state === "running";
  useEffect(() => {
    if (paused || !active || polls >= 60) return;
    const timer = window.setTimeout(() => {
      if (document.visibilityState === "visible") {
        startTransition(() => router.refresh());
        setPolls((value) => value + 1);
      } else {
        setPolls((value) => value + 1);
      }
    }, 5_000);
    return () => window.clearTimeout(timer);
  }, [active, polls, router, paused]);
  if (job.state === "succeeded") return null;
  return (
    <Notice
      title={`Calculation ${titleCase(job.state).toLowerCase()}`}
      tone={job.state === "failed" ? "danger" : "info"}
    >
      <p>
        {active
          ? "Your request is stored durably. The result will appear after the worker completes its calculation."
          : "This request has no finalized allocation result. Review its status before calculating a new revision."}
      </p>
      {job.failure_code ? <p>Reason: {titleCase(job.failure_code)}</p> : null}
      {paused ? (
        <p className="muted">
          Status checks are paused while you edit. Your original revision
          precondition is retained until you leave the editor.
        </p>
      ) : null}
      {!paused && active && polls < 60 ? (
        <p className="muted">
          Checking every five seconds while this page is visible.
        </p>
      ) : null}
      {!paused ? (
        <button
          type="button"
          disabled={pending}
          onClick={() => {
            setPolls(0);
            startTransition(() => router.refresh());
          }}
        >
          {pending ? "Checking…" : "Check calculation status"}
        </button>
      ) : null}
    </Notice>
  );
}
