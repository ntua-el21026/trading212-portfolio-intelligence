"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { Button, Notice } from "@trading212/ui";
import type {
  Account,
  AggregateFxBinding,
  AggregateSelectionResponse,
  FxObservationReferencePage,
} from "@trading212/api-contracts";
import {
  loadAggregateFxChoices,
  type AggregateFxSnapshotChoice,
} from "../lib/aggregation-fx-actions";
import { formatDateTime } from "../lib/format";
import { useNavigationVersionRef } from "./navigation-intent";
import styles from "./aggregation.module.css";

export function AggregateFxPicker({
  index,
  value,
  selection,
  accounts,
  change,
  remove,
}: Readonly<{
  index: number;
  value: AggregateFxBinding;
  selection: AggregateSelectionResponse;
  accounts: readonly Account[];
  change: (value: AggregateFxBinding) => void;
  remove: () => void;
}>) {
  const [direction, setDirection] = useState<"direct" | "inverse">("direct");
  const [snapshots, setSnapshots] = useState<AggregateFxSnapshotChoice[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [snapshotCursor, setSnapshotCursor] = useState<string | null>(null);
  const [observations, setObservations] =
    useState<FxObservationReferencePage | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const generation = useRef(0);
  const alive = useRef(true);
  const navigation = useNavigationVersionRef();
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      generation.current += 1;
    };
  }, []);
  useEffect(() => {
    generation.current += 1;
  }, [selection.selection_id, selection.revision]);
  function reset(next: AggregateFxBinding, nextDirection = direction) {
    generation.current += 1;
    setDirection(nextDirection);
    setSnapshots([]);
    setSnapshotId("");
    setSnapshotCursor(null);
    setObservations(null);
    setLoaded(false);
    setError(null);
    change({ ...next, fx_observation_id: "" });
  }
  function load(
    kind: "snapshots" | "observations",
    cursor: string | null = null,
    snapshot = snapshotId,
  ) {
    const stamp = ++generation.current;
    const intent = navigation.current;
    const current = () =>
      alive.current &&
      generation.current === stamp &&
      navigation.current === intent;
    setError(null);
    // Changing pages clears the binding: every submitted ID must still be explicitly visible.
    change({ ...value, fx_observation_id: "" });
    if (kind === "snapshots") {
      setSnapshots([]);
      setSnapshotId("");
      setObservations(null);
      setSnapshotCursor(null);
      setLoaded(false);
    } else {
      setSnapshotId(snapshot);
      setObservations(null);
    }
    start(async () => {
      try {
        const context = {
          selection_id: selection.selection_id,
          revision: selection.revision,
          account_id: value.account_id,
          currency: value.currency,
          direction,
          cursor,
        };
        const result = await loadAggregateFxChoices(
          kind === "snapshots"
            ? { ...context, kind }
            : { ...context, kind, snapshot_id: snapshot },
        );
        if (!current()) return;
        if (!result.ok) {
          setError(result.message);
          return;
        }
        if (result.kind !== kind) {
          setError(
            "The FX selection context changed. Reload the saved sources.",
          );
          return;
        }
        if (result.kind === "snapshots") {
          if (result.account_id !== value.account_id) {
            setError("The FX account did not match.");
            return;
          }
          setSnapshots(result.items);
          setSnapshotCursor(result.next_cursor);
          setLoaded(true);
        } else {
          if (
            result.page.account_id !== value.account_id ||
            result.page.snapshot_id !== snapshot
          ) {
            setError("The FX source did not match.");
            return;
          }
          setObservations(result.page);
        }
      } catch {
        if (current())
          setError(
            "Saved FX observations could not be loaded. Retry this selection.",
          );
      }
    });
  }
  const canLoad =
    Boolean(value.account_id) &&
    /^[A-Z]{3}$/.test(value.currency) &&
    value.currency !== selection.content.reporting_currency;
  return (
    <fieldset disabled={pending} className={styles.stack}>
      <legend>Saved FX reference {index + 1}</legend>
      <div className={styles.fields}>
        <label>
          <span>FX account {index + 1}</span>
          <select
            required
            value={value.account_id}
            onChange={(event) =>
              reset({ ...value, account_id: event.target.value })
            }
          >
            <option value="">Choose an included account</option>
            {selection.content.members.map((member) => (
              <option key={member.account_id} value={member.account_id}>
                {accounts.find((account) => account.id === member.account_id)
                  ?.display_name ?? member.account_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Original currency {index + 1}</span>
          <input
            required
            maxLength={3}
            pattern="[A-Z]{3}"
            value={value.currency}
            onChange={(event) =>
              reset({ ...value, currency: event.target.value })
            }
          />
        </label>
        <label>
          <span>FX direction {index + 1}</span>
          <select
            value={direction}
            onChange={(event) =>
              reset(
                value,
                event.target.value === "inverse" ? "inverse" : "direct",
              )
            }
          >
            <option value="direct">
              Original currency → {selection.content.reporting_currency}
            </option>
            <option value="inverse">
              {selection.content.reporting_currency} → original currency
              (inverse)
            </option>
          </select>
        </label>
      </div>
      <div className={styles.toolbar}>
        <Button
          type="button"
          disabled={!canLoad}
          onClick={() => load("snapshots")}
        >
          Load saved FX sources {index + 1}
        </Button>
        {snapshotCursor ? (
          <Button
            type="button"
            onClick={() => load("snapshots", snapshotCursor)}
          >
            Next FX sources {index + 1}
          </Button>
        ) : null}
        <Button type="button" onClick={remove}>
          Remove FX reference {index + 1}
        </Button>
      </div>
      {pending ? <p role="status">Loading saved FX choices…</p> : null}
      {loaded && !snapshots.length ? (
        <p>
          No saved FX sources match this direction and source cutoff. Remove
          this reference to retain an explicitly incomplete conversion.
        </p>
      ) : null}
      {snapshots.length ? (
        <label>
          <span>Saved FX source {index + 1}</span>
          <select
            required
            value={snapshotId}
            onChange={(event) => {
              if (event.target.value)
                load("observations", null, event.target.value);
              else {
                generation.current += 1;
                setSnapshotId("");
                setObservations(null);
                change({ ...value, fx_observation_id: "" });
              }
            }}
          >
            <option value="">Choose a saved source</option>
            {snapshots.map((snapshot) => (
              <option
                key={snapshot.snapshot_id}
                value={snapshot.snapshot_id}
                disabled={
                  snapshot.availability === "unavailable" ||
                  snapshot.availability === "failed"
                }
              >
                {snapshot.provider} · known{" "}
                {formatDateTime(snapshot.first_observed_at)} ·{" "}
                {snapshot.available_count} available · {snapshot.availability}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {observations ? (
        <>
          <p>
            Observations are bounded by the selected account’s saved valuation
            and the aggregate cutoff. Source known{" "}
            {formatDateTime(observations.first_observed_at)}; retained until{" "}
            {formatDateTime(observations.expires_at)}.
          </p>
          <label>
            <span>Saved FX observation {index + 1}</span>
            <select
              required
              value={value.fx_observation_id}
              onChange={(event) =>
                change({ ...value, fx_observation_id: event.target.value })
              }
            >
              <option value="">Choose an exact saved observation</option>
              {observations.items.map((observation) => (
                <option
                  key={observation.observation_id}
                  value={observation.observation_id}
                  disabled={
                    observation.state !== "available" ||
                    observation.rate === null
                  }
                >
                  {observation.session_date} ·{" "}
                  {observation.rate ?? "unavailable"} {observations.quote}/
                  {observations.base} · {observation.state}
                </option>
              ))}
            </select>
          </label>
          {!observations.items.length ? (
            <p>No retained observations on this page.</p>
          ) : null}
          {observations.next_cursor ? (
            <Button
              type="button"
              onClick={() => load("observations", observations.next_cursor)}
            >
              Older FX observations {index + 1}
            </Button>
          ) : null}
          {value.fx_observation_id ? (
            <p>
              Selected reference: <code>{value.fx_observation_id}</code>
            </p>
          ) : null}
        </>
      ) : null}
      {error ? <Notice title="FX selection unavailable">{error}</Notice> : null}
    </fieldset>
  );
}
