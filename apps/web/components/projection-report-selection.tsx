"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Notice, Surface } from "@trading212/ui";
import { submitProjectionReportCommand } from "../lib/projection-report-actions";
import {
  projectionReportSourceHref,
  type ProjectionReportSource,
} from "../lib/projection-report-query";
import { formatDateTime } from "../lib/format";
import { useNavigationVersionRef } from "./navigation-intent";
import styles from "./report-view.module.css";

const FORMATS = ["pdf", "csv", "json", "xlsx"] as const;
type Format = (typeof FORMATS)[number];
export function ProjectionReportSelection({
  source,
  canCreate,
}: Readonly<{ source: ProjectionReportSource; canCreate: boolean }>) {
  const router = useRouter();
  const navigation = useNavigationVersionRef();
  const [formats, setFormats] = useState<Format[]>(["pdf"]);
  const [ttl, setTtl] = useState("7");
  const [includeGoal, setIncludeGoal] = useState(source.goalVersionId !== null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const identity = useRef<{ selection: string; key: string } | null>(null);
  const alive = useRef(true);
  const selection = JSON.stringify([
    source.profile,
    source.accountId,
    source.runId,
    source.resultDigest,
    source.captureDigest,
    source.snapshotId,
    source.snapshotValuation,
    source.sourceCutoff,
  ]);
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
    const fingerprint = JSON.stringify([selection, formats, ttl, includeGoal]);
    if (identity.current?.selection !== fingerprint)
      identity.current = {
        selection: fingerprint,
        key: `projection-report:${crypto.randomUUID()}`,
      };
    setPending(true);
    setError(null);
    try {
      const response = await submitProjectionReportCommand({
        profile_version: "report_sections_v4",
        premium_run: { family: "projection", run_id: source.runId },
        account_id: source.accountId,
        snapshot_id: source.snapshotId,
        expected_result_digest: source.resultDigest,
        expected_capture_digest: source.captureDigest,
        expected_snapshot_valuation: source.snapshotValuation,
        expected_snapshot_cutoff: source.sourceCutoff,
        include_goal: includeGoal,
        formats,
        ttl_days: Number(ttl),
        idempotency_key: identity.current.key,
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
        response.job.profile_version !== "report_sections_v4"
      ) {
        setError("The report response could not be verified.");
        return;
      }
      router.push(projectionReportSourceHref(source, response.job.job_id));
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
    <Surface aria-label="Create projection report" className={styles.surface}>
      <h2>Create a report from the saved projection</h2>
      <p>
        Every saved path, checkpoint, variant and source proof is copied. Goal
        results remain model estimates; reaching an objective never accepts a
        goal automatically.
      </p>
      <dl className={styles.definition}>
        <dt>Projection run</dt>
        <dd className="mono">{source.runId}</dd>
        <dt>Projection currency</dt>
        <dd>{source.currency}</dd>
        <dt>Model dates</dt>
        <dd>
          {source.anchorDate} to {source.terminalDate}
        </dd>
        <dt>Original observed valuation</dt>
        <dd>
          {source.originalValuation
            ? formatDateTime(source.originalValuation)
            : "No observed valuation; modeled starting value"}
        </dd>
        <dt>Original source cutoff</dt>
        <dd>
          {source.originalCutoff
            ? formatDateTime(source.originalCutoff)
            : "Not supplied by every original source"}
        </dd>
        <dt>Report-context snapshot</dt>
        <dd className="mono">{source.snapshotId}</dd>
        <dt>Snapshot valuation</dt>
        <dd>{formatDateTime(source.snapshotValuation)}</dd>
        <dt>Report-context cutoff</dt>
        <dd>{formatDateTime(source.sourceCutoff)}</dd>
      </dl>
      {source.snapshotCurrency !== source.currency ? (
        <Notice title="Original snapshot currency">
          The selected snapshot retains {source.snapshotCurrency} values.
          Projection values remain {source.currency}; this report does not
          convert source money.
        </Notice>
      ) : null}
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
        {source.goalVersionId ? (
          <label className={styles.choice}>
            <input
              type="checkbox"
              checked={includeGoal}
              disabled={pending || !canCreate}
              onChange={(event) => setIncludeGoal(event.target.checked)}
            />
            Include the pinned goal section
          </label>
        ) : (
          <p>
            No goal is pinned to this projection. Its absence will be explicit
            in the report.
          </p>
        )}
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
        <p>
          Original source permissions and expiry may shorten retention. A
          complete report that exceeds existing size or page limits fails
          without trimming saved paths.
        </p>
        <Button
          type="submit"
          disabled={pending || !canCreate || !formats.length}
        >
          {pending ? "Creating report…" : "Create projection report"}
        </Button>
      </form>
      {!canCreate ? (
        <Notice title="Report creation unavailable">
          This session needs report creation and analytics read access. Licensed
          historical calibration also requires activity read access.
        </Notice>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </Surface>
  );
}
