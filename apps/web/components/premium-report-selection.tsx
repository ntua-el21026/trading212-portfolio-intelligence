"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Notice, Surface } from "@trading212/ui";
import {
  submitPremiumReportCommand,
  submitPremiumReportV3Command,
} from "../lib/premium-report-actions";
import {
  premiumReportSourceHref,
  type PremiumReportSource,
  type PremiumReportSourceV3,
} from "../lib/premium-report-query";
import { formatDateTime } from "../lib/format";
import { useNavigationVersionRef } from "./navigation-intent";
import styles from "./report-view.module.css";

const FORMATS = ["pdf", "csv", "json", "xlsx"] as const;
type Format = (typeof FORMATS)[number];
export function PremiumReportSelection({
  source,
  canCreate,
}: Readonly<{
  source: PremiumReportSource | PremiumReportSourceV3;
  canCreate: boolean;
}>) {
  const profile = "profile" in source ? source.profile : "report_sections_v2";
  const family = "family" in source ? source.family : "risk";
  const router = useRouter();
  const navigation = useNavigationVersionRef();
  const [formats, setFormats] = useState<Format[]>(["pdf"]);
  const [ttl, setTtl] = useState("7");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const identity = useRef<{ selection: string; key: string } | null>(null);
  const alive = useRef(true);
  const selection = `${profile}:${family}:${source.accountId}:${source.runId}:${source.resultDigest}`;
  const activeSelection = useRef(selection);
  useEffect(() => {
    alive.current = true;
    activeSelection.current = selection;
    return () => {
      alive.current = false;
    };
  }, [selection]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || !canCreate || !formats.length) return;
    const stamp = navigation.current;
    const fingerprint = JSON.stringify([selection, formats, ttl]);
    if (identity.current?.selection !== fingerprint)
      identity.current = {
        selection: fingerprint,
        key: `${profile === "report_sections_v3" ? "premium-report" : "risk-report"}:${crypto.randomUUID()}`,
      };
    setPending(true);
    setError(null);
    try {
      const values = {
        account_id: source.accountId,
        expected_result_digest: source.resultDigest,
        idempotency_key: identity.current.key,
        formats,
        ttl_days: Number(ttl),
      };
      const response =
        profile === "report_sections_v3"
          ? await submitPremiumReportV3Command({
              ...values,
              profile_version: profile,
              premium_run: { family, run_id: source.runId },
            })
          : await submitPremiumReportCommand({
              ...values,
              risk_run_id: source.runId,
            });
      if (
        !alive.current ||
        activeSelection.current !== selection ||
        navigation.current !== stamp
      )
        return;
      if (!response.ok) {
        setError(`${response.code}: ${response.message}`);
        return;
      }
      if (
        response.job.account_id !== source.accountId ||
        (profile === "report_sections_v3" &&
          (!("profile_version" in response.job) ||
            response.job.profile_version !== profile))
      ) {
        setError("The report response could not be verified.");
        return;
      }
      router.push(premiumReportSourceHref(source, response.job.job_id));
    } catch {
      if (
        alive.current &&
        activeSelection.current === selection &&
        navigation.current === stamp
      )
        setError(
          "The request could not complete. Your choices and retry identity are preserved.",
        );
    } finally {
      if (alive.current && activeSelection.current === selection)
        setPending(false);
    }
  }
  return (
    <Surface aria-label={`Create ${family} report`} className={styles.surface}>
      <h2>Report from {source.name}</h2>
      <p>
        The report copies this saved analysis, including unavailable values and
        complete source evidence. It does not recalculate {family}.
      </p>
      <dl className={styles.definition}>
        <dt>{family === "scenario" ? "Scenario run" : "Risk run"}</dt>
        <dd className="mono">{source.runId}</dd>
        <dt>Snapshot</dt>
        <dd className="mono">{source.snapshotId}</dd>
        <dt>{family === "scenario" ? "Report period" : "Historical window"}</dt>
        <dd>
          {source.startDate} to {source.endDate}
        </dd>
        <dt>Currency</dt>
        <dd>{source.currency}</dd>
        <dt>Source cutoff</dt>
        <dd>{formatDateTime(source.sourceCutoff)}</dd>
      </dl>
      <form onSubmit={submit} className={`target-form ${styles.selectionForm}`}>
        <fieldset disabled={pending || !canCreate} className={styles.formats}>
          <legend>Report formats</legend>
          {FORMATS.map((format) => (
            <label key={format} className={styles.choice}>
              <input
                type="checkbox"
                checked={formats.includes(format)}
                onChange={(event) => {
                  const selected = new Set(formats);
                  if (event.target.checked) selected.add(format);
                  else selected.delete(format);
                  setFormats(FORMATS.filter((item) => selected.has(item)));
                }}
              />{" "}
              {format.toUpperCase()}
            </label>
          ))}
        </fieldset>
        <label>
          Requested retention (days)
          <input
            type="number"
            min="1"
            max="30"
            step="1"
            required
            value={ttl}
            disabled={pending || !canCreate}
            onChange={(event) => setTtl(event.target.value)}
          />
        </label>
        <p>Source permissions or expiry may shorten retention.</p>
        <Button
          type="submit"
          disabled={pending || !canCreate || !formats.length}
        >
          {pending ? "Creating report…" : `Create ${family} report`}
        </Button>
      </form>
      {!canCreate ? (
        <Notice title="Report creation unavailable">
          {family === "risk"
            ? "This session needs report creation, analytics and activity read access."
            : "This session needs report creation and analytics read access. Historical replay also requires activity read access."}
        </Notice>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </Surface>
  );
}
