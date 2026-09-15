"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  AssumptionVersionResponse,
  GoalVersionResponse,
  CreateProjectionRunRequest,
  SnapshotDetail,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import { projectionHref, type ProjectionQuery } from "../lib/projection-query";
import { useProjectionCommand } from "./projection-command";
import { ExactField, ScheduleFields, emptySchedule } from "./projection-fields";
import styles from "./projection-workspace.module.css";
export function ProjectionRunForm({
  accountId,
  query,
  assumption,
  goal,
  snapshot,
  defaultAnchor,
  canWrite,
}: Readonly<{
  accountId: string;
  query: ProjectionQuery;
  assumption: AssumptionVersionResponse;
  goal?: GoalVersionResponse;
  snapshot?: SnapshotDetail;
  defaultAnchor: string;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const currency = assumption.content.reporting_currency;
  const [initial, setInitial] = useState<
    CreateProjectionRunRequest["initial_basis"]
  >(() =>
    snapshot
      ? {
          kind: "observed_snapshot",
          snapshot_id: snapshot.id,
          modeled_value: null,
          modeled_anchor_date: null,
        }
      : {
          kind: "modeled_value",
          snapshot_id: null,
          modeled_value: { amount: "0", currency },
          modeled_anchor_date: defaultAnchor,
        },
  );
  const [schedule, setSchedule] = useState(
    () => goal?.content.schedule ?? emptySchedule(currency),
  );
  const [months, setMonths] = useState(goal?.content.months ?? 12);
  const [paths, setPaths] = useState(64),
    [seed, setSeed] = useState(0);
  const [retained, setRetained] = useState(`0,${goal?.content.months ?? 12}`);
  const [sensitivity, setSensitivity] = useState(false),
    [contributionDelta, setContributionDelta] = useState("0"),
    [meanDelta, setMeanDelta] = useState("0");
  const action = useProjectionCommand((result) => {
    if (result.kind === "run")
      router.push(
        projectionHref(query, {
          view: "result",
          run: result.value.id,
          point_cursor: null,
          runs_cursor: null,
        }),
      );
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: CreateProjectionRunRequest = {
      assumption_version_id: assumption.id,
      goal_version_id: goal?.id ?? null,
      initial_basis: initial,
      schedule: goal?.content.schedule ?? schedule,
      months: goal?.content.months ?? months,
      paths,
      seed,
      retained_months: retained
        .split(",")
        .map((value) =>
          /^\d+$/.test(value.trim()) ? Number(value.trim()) : NaN,
        ),
      allocation: assumption.content.assets.map(({ key, weight }) => ({
        key,
        weight,
      })),
      sensitivity: sensitivity
        ? {
            contribution_delta: { amount: contributionDelta, currency },
            annual_mean_log_delta: meanDelta,
          }
        : null,
    };
    action.submit((idempotency_key) => ({
      kind: "create_run",
      account_id: accountId,
      body,
      idempotency_key,
    }));
  }
  return (
    <form
      aria-label="Create projection run"
      className={styles.form}
      onSubmit={submit}
      onChange={action.changed}
    >
      <fieldset disabled={!canWrite || action.pending}>
        <legend>Run saved assumptions</legend>
        <p>
          Assumptions <code>{assumption.id}</code> · {assumption.metadata.name};
          currency {currency}. Allocation is copied exactly from this immutable
          version. A background worker retains the selected paths; refresh and
          pagination never recalculate them.
        </p>
        {goal ? (
          <Notice title="Immutable goal selected">
            Goal <code>{goal.id}</code> fixes the {goal.content.months}-month
            horizon, schedule and target date {goal.content.target_date}. The
            chosen initial anchor must match that date. Select a different goal
            version to change these constraints.
          </Notice>
        ) : null}
        <fieldset>
          <legend>Initial portfolio basis</legend>
          <label>
            Initial value source
            <select
              value={initial.kind}
              onChange={(event) => {
                action.changed();
                setInitial(
                  event.target.value === "observed_snapshot" && snapshot
                    ? {
                        kind: "observed_snapshot",
                        snapshot_id: snapshot.id,
                        modeled_value: null,
                        modeled_anchor_date: null,
                      }
                    : {
                        kind: "modeled_value",
                        snapshot_id: null,
                        modeled_value: { amount: "0", currency },
                        modeled_anchor_date: defaultAnchor,
                      },
                );
              }}
            >
              <option value="modeled_value">Explicit modeled value</option>
              {snapshot ? (
                <option value="observed_snapshot">
                  Selected saved snapshot
                </option>
              ) : null}
            </select>
          </label>
          {initial.kind === "observed_snapshot" ? (
            <p>
              Saved snapshot <code>{snapshot?.id}</code> · valuation{" "}
              {snapshot?.valuation_at} · source cutoff{" "}
              {snapshot?.source_cutoff_at}. The server captures its observed
              money and exact source clocks; no entered amount replaces them.
            </p>
          ) : (
            <div className={styles.fields}>
              <ExactField
                label={`Modeled initial value (${currency})`}
                required
                value={initial.modeled_value?.amount ?? ""}
                onChange={(event) =>
                  setInitial({
                    ...initial,
                    modeled_value: { amount: event.target.value, currency },
                  })
                }
              />
              <label>
                Modeled anchor date
                <input
                  type="date"
                  required
                  value={initial.modeled_anchor_date ?? ""}
                  onChange={(event) =>
                    setInitial({
                      ...initial,
                      modeled_anchor_date: event.target.value,
                    })
                  }
                />
              </label>
            </div>
          )}
        </fieldset>
        <div className={styles.fields}>
          <label>
            Projection horizon (months)
            <input
              type="number"
              min={1}
              max={600}
              step={1}
              value={months}
              required
              disabled={Boolean(goal)}
              onChange={(event) => setMonths(Number(event.target.value))}
            />
          </label>
          <label>
            Saved path count
            <input
              type="number"
              min={1}
              max={4096}
              step={1}
              required
              value={paths}
              onChange={(event) => setPaths(Number(event.target.value))}
            />
          </label>
          <label>
            Random seed
            <input
              type="number"
              min={0}
              max={4294967295}
              step={1}
              required
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
            />
          </label>
          <label>
            Retained months (comma separated)
            <input
              required
              value={retained}
              maxLength={600}
              onChange={(event) => setRetained(event.target.value)}
            />
          </label>
        </div>
        <p>
          Retain 2–121 unique months, including 0 and the terminal month. Work
          is bounded across assets × months × paths × variants to 1,000,000;
          retained bytes have a separate limit.
        </p>
        <ScheduleFields
          value={goal?.content.schedule ?? schedule}
          onChange={(value) => {
            action.changed();
            setSchedule(value);
          }}
          disabled={Boolean(goal)}
        />
        <fieldset>
          <legend>Sensitivity variants</legend>
          <label>
            <span>
              <input
                type="checkbox"
                checked={sensitivity}
                onChange={(event) => setSensitivity(event.target.checked)}
              />{" "}
              Include contribution and mean-return variants
            </span>
          </label>
          {sensitivity ? (
            <div className={styles.fields}>
              <ExactField
                label={`Monthly contribution delta (${currency})`}
                required
                value={contributionDelta}
                onChange={(event) => setContributionDelta(event.target.value)}
              />
              <ExactField
                label="Annual mean log return delta"
                required
                value={meanDelta}
                onChange={(event) => setMeanDelta(event.target.value)}
              />
            </div>
          ) : null}
          <p>
            When enabled, baseline, contribution-delta and mean-return-delta
            variants share absolute random path identities. These are
            alternative model assumptions, not recommendations.
          </p>
        </fieldset>
        <Button type="submit">
          {action.pending
            ? "Creating projection run…"
            : "Create projection run"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Run write access required">
          Run creation requires projections:write.
        </Notice>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}
