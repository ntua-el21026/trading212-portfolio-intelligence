"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Notice, Surface } from "@trading212/ui";
import type { ResearchItemView } from "@trading212/api-contracts";
import { submitResearchReportCommand } from "../lib/research-report-actions";
import {
  researchReportHref,
  researchReportPinsSchema,
  type ResearchReportPins,
  type ResearchReportSource,
} from "../lib/research-report-query";
import { useNavigationVersionRef } from "./navigation-intent";

const FORMATS = ["pdf", "csv", "json", "xlsx"] as const;
type Format = (typeof FORMATS)[number];

export function ResearchReportSelection({
  item,
  source,
  initialPins,
  canCreate,
}: Readonly<{
  item: ResearchItemView;
  source: ResearchReportSource;
  initialPins: ResearchReportPins;
  canCreate: boolean;
}>) {
  const router = useRouter();
  const navigation = useNavigationVersionRef();
  const [notes, setNotes] = useState(initialPins.note_revision_ids.join("\n"));
  const [review, setReview] = useState(
    initialPins.review_acknowledgment_id ?? "",
  );
  const [formats, setFormats] = useState<Format[]>(["pdf"]);
  const [ttl, setTtl] = useState("7");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const identity = useRef<{ fingerprint: string; key: string } | null>(null);
  const alive = useRef(true);
  const selection = `${source.accountId}:${source.itemId}:${source.eventDigest}:${source.xrayResultDigest}`;
  const current = useRef(selection);
  useEffect(() => {
    alive.current = true;
    current.current = selection;
    return () => {
      alive.current = false;
    };
  }, [selection]);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || !canCreate || !formats.length) return;
    const parsed = researchReportPinsSchema.safeParse({
      family: "research",
      item_id: source.itemId,
      note_revision_ids: notes.split(/[\s,]+/).filter(Boolean),
      ...(review.trim() ? { review_acknowledgment_id: review.trim() } : {}),
    });
    if (!parsed.success) {
      setError(
        "Enter up to 64 distinct exact note revision IDs and an optional exact review acknowledgment ID.",
      );
      return;
    }
    const pins = parsed.data;
    const stamp = navigation.current;
    const fingerprint = JSON.stringify([selection, pins, formats, ttl]);
    if (identity.current?.fingerprint !== fingerprint)
      identity.current = {
        fingerprint,
        key: `research-report:${crypto.randomUUID()}`,
      };
    setPending(true);
    setError(null);
    try {
      const response = await submitResearchReportCommand({
        account_id: source.accountId,
        premium_run: pins,
        expected_event_digest: source.eventDigest,
        expected_xray_result_digest: source.xrayResultDigest,
        idempotency_key: identity.current.key,
        formats,
        ttl_days: Number(ttl),
      });
      if (
        !alive.current ||
        current.current !== selection ||
        navigation.current !== stamp
      )
        return;
      if (!response.ok) {
        setError(`${response.code}: ${response.message}`);
        return;
      }
      if (
        response.job.account_id !== source.accountId ||
        response.job.profile_version !== "report_sections_v3"
      ) {
        setError("The report response could not be verified.");
        return;
      }
      router.push(researchReportHref(source, pins, response.job.job_id));
    } catch {
      if (
        alive.current &&
        current.current === selection &&
        navigation.current === stamp
      )
        setError(
          "The request could not complete. Your exact choices and retry identity are preserved.",
        );
    } finally {
      if (alive.current && current.current === selection) setPending(false);
    }
  }

  return (
    <Surface aria-label="Create research report">
      <h2>Report from {source.name}</h2>
      <p>
        Copy this retained source revision and portfolio evidence. Choose exact
        owner revisions; no latest version is selected automatically.
      </p>
      <dl>
        <dt>Research item</dt>
        <dd>{source.itemId}</dd>
        <dt>Source revision</dt>
        <dd>{source.eventRevisionId}</dd>
        <dt>Snapshot</dt>
        <dd>{source.snapshotId}</dd>
        <dt>Portfolio valuation</dt>
        <dd>{source.valuationAt}</dd>
        <dt>X-ray source cutoff</dt>
        <dd>{source.xraySourceCutoff}</dd>
        <dt>Research source cutoff</dt>
        <dd>{source.sourceCutoff}</dd>
        <dt>Currency</dt>
        <dd>{source.currency}</dd>
      </dl>
      <form onSubmit={submit} className="target-form">
        <label>
          Exact owner note revision IDs (optional)
          <textarea
            value={notes}
            maxLength={2367}
            disabled={pending || !canCreate}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        <p>
          One revision UUID per line, up to 64. Empty means owner notes were not
          selected.
        </p>
        {item.owner_revisions.length ? (
          <details>
            <summary>Available owner revision references</summary>
            <ul>
              {item.owner_revisions.map((note) => (
                <li key={note.revision_id}>
                  {note.content.title} · revision {note.revision} ·{" "}
                  {note.created_at} · <code>{note.revision_id}</code>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {item.owner_revisions_omitted ? (
          <p>
            {item.owner_revisions_omitted} additional current note heads are
            outside this preview. Use Owner notes to inspect saved history.
          </p>
        ) : null}
        <label>
          Exact review acknowledgment ID (optional)
          <input
            value={review}
            maxLength={36}
            disabled={pending || !canCreate}
            onChange={(event) => setReview(event.target.value)}
          />
        </label>
        <p>Empty means review evidence was not selected.</p>
        {item.review ? (
          <p>
            Current acknowledgment for this exact source revision:{" "}
            <code>{item.review.acknowledgment_id}</code>
          </p>
        ) : null}
        <fieldset disabled={pending || !canCreate}>
          <legend>Report formats</legend>
          {FORMATS.map((format) => (
            <label key={format}>
              <input
                type="checkbox"
                checked={formats.includes(format)}
                onChange={(event) => {
                  const chosen = new Set(formats);
                  if (event.target.checked) chosen.add(format);
                  else chosen.delete(format);
                  setFormats(FORMATS.filter((value) => chosen.has(value)));
                }}
              />
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
        <p>Original source permissions and expiry may shorten retention.</p>
        <Button
          type="submit"
          disabled={pending || !canCreate || !formats.length}
        >
          {pending ? "Creating report…" : "Create research report"}
        </Button>
      </form>
      {!canCreate ? (
        <Notice title="Research report creation unavailable">
          Current research, portfolio, analytics and report creation access are
          required.
        </Notice>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </Surface>
  );
}
