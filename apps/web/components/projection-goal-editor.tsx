"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  AssumptionVersionResponse,
  GoalResponse,
  GoalVersionResponse,
  CreateGoalRequest,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import {
  projectionSelectionHref,
  type ProjectionQuery,
} from "../lib/projection-query";
import { useProjectionCommand } from "./projection-command";
import { ExactField, ScheduleFields, emptySchedule } from "./projection-fields";
import styles from "./projection-workspace.module.css";
export function ProjectionGoalEditor({
  accountId,
  query,
  assumption,
  goal,
  version,
  canWrite,
}: Readonly<{
  accountId: string;
  query: ProjectionQuery;
  assumption: AssumptionVersionResponse;
  goal?: GoalResponse;
  version?: GoalVersionResponse;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const [name, setName] = useState(version?.metadata.name ?? "");
  const [description, setDescription] = useState(
    version?.metadata.description ?? "",
  );
  const [content, setContent] = useState<CreateGoalRequest["content"]>(
    () =>
      version?.content ?? {
        assumption_version_id: assumption.id,
        target: {
          amount: "0",
          currency: assumption.content.reporting_currency,
        },
        target_date: "",
        months: 12,
        basis: "real",
        probability_objective: "0.8",
        schedule: emptySchedule(assumption.content.reporting_currency),
      },
  );
  const action = useProjectionCommand((result) => {
    if (result.kind === "goal")
      router.push(
        projectionSelectionHref(query, {
          view: "goals",
          goal: result.value.id,
          goal_version: result.value.current_version_id,
        }),
      );
    if (result.kind === "goal_version")
      router.push(
        projectionSelectionHref(query, {
          view: "goals",
          goal: result.value.goal_id,
          goal_version: result.value.id,
        }),
      );
  });
  function change(next: typeof content) {
    action.changed();
    setContent(next);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = {
      metadata: { name, description },
      content: { ...content, assumption_version_id: assumption.id },
    };
    action.submit((idempotency_key) =>
      goal
        ? {
            kind: "create_goal_version",
            account_id: accountId,
            goal_id: goal.id,
            if_match: `"${goal.id}:${goal.revision}"`,
            body,
            idempotency_key,
          }
        : { kind: "create_goal", account_id: accountId, body, idempotency_key },
    );
  }
  return (
    <form
      aria-label="Projection goal"
      className={styles.form}
      onSubmit={submit}
    >
      <fieldset disabled={!canWrite || action.pending}>
        <legend>
          {goal ? "Save an immutable goal version" : "Create a goal"}
        </legend>
        <p>
          Assumption version: <code>{assumption.id}</code> ·{" "}
          {assumption.metadata.name}. Saving keeps the target, probability
          objective and cash-flow schedule together. A modeled objective being
          met never marks the goal accepted or achieved.
        </p>
        <label>
          Goal name
          <input
            required
            maxLength={120}
            value={name}
            onChange={(event) => {
              action.changed();
              setName(event.target.value);
            }}
          />
        </label>
        <label>
          Description
          <textarea
            maxLength={1024}
            value={description}
            onChange={(event) => {
              action.changed();
              setDescription(event.target.value);
            }}
          />
        </label>
        <div className={styles.fields}>
          <ExactField
            label={`Target amount (${content.target.currency})`}
            required
            value={content.target.amount}
            onChange={(event) =>
              change({
                ...content,
                target: { ...content.target, amount: event.target.value },
              })
            }
          />
          <label>
            Target date
            <input
              type="date"
              required
              value={content.target_date}
              onChange={(event) =>
                change({ ...content, target_date: event.target.value })
              }
            />
          </label>
          <label>
            Goal horizon (months)
            <input
              type="number"
              min={1}
              max={600}
              step={1}
              required
              value={content.months}
              onChange={(event) =>
                change({ ...content, months: Number(event.target.value) })
              }
            />
          </label>
          <label>
            Target basis
            <select
              value={content.basis}
              onChange={(event) =>
                change({
                  ...content,
                  basis: event.target.value as "nominal" | "real",
                })
              }
            >
              <option value="real">Real purchasing power</option>
              <option value="nominal">Nominal money</option>
            </select>
          </label>
          <ExactField
            label="Probability objective (ratio)"
            required
            value={content.probability_objective}
            onChange={(event) =>
              change({ ...content, probability_objective: event.target.value })
            }
          />
        </div>
        <p>
          The target date must equal the terminal monthly boundary of any run
          using this version. Real targets use the saved modeled inflation
          assumption.
        </p>
        <ScheduleFields
          value={content.schedule}
          onChange={(schedule) => change({ ...content, schedule })}
        />
        <Button type="submit">
          {action.pending
            ? "Saving goal…"
            : goal
              ? "Save goal version"
              : "Create goal"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Goal write access required">
          Saving goals requires goals:write.
        </Notice>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}
