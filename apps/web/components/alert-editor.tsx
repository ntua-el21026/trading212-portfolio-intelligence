"use client";

import { useNavigationVersionRef } from "./navigation-intent";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button, Notice, Surface } from "@trading212/ui";
import type {
  AlertRuleDetail,
  NotificationDestination,
} from "@trading212/api-contracts";
import {
  submitAlertCommand,
  type AlertActionResult,
} from "../lib/alert-actions";
import { ALERT_FAMILIES, alertHref } from "../lib/alert-query";
import {
  ALERT_METRICS,
  alertDefinitionFromForm,
  type AlertEditorField,
  type AlertEditorMetric,
} from "../lib/alert-editor-model";
import { titleCase } from "../lib/format";
import styles from "./alert-view.module.css";
import { useAlertTransition } from "./alert-commands";

function PredicateControl({
  field,
  initial,
}: Readonly<{ field: AlertEditorField; initial?: unknown }>) {
  const value =
    initial === undefined || initial === null
      ? (field.initial ?? (field.optional ? "" : (field.options?.[0] ?? "")))
      : String(initial);
  const options = field.kind === "boolean" ? ["true", "false"] : field.options;
  return (
    <label>
      {field.label}
      {field.optional ? " (optional)" : ""}
      {options?.length ? (
        <select
          name={field.key}
          defaultValue={value}
          required={!field.optional}
        >
          {field.optional ? <option value="">All applicable</option> : null}
          {options.map((option) => (
            <option value={option} key={option}>
              {titleCase(option)}
            </option>
          ))}
        </select>
      ) : (
        <input
          name={field.key}
          defaultValue={value}
          required={!field.optional}
          type={field.kind === "integer" ? "number" : "text"}
          min={field.min}
          max={field.max}
          step={field.kind === "integer" ? 1 : undefined}
          maxLength={
            field.kind === "uuid" ? 36 : field.key === "currency" ? 3 : 80
          }
          pattern={field.key === "currency" ? "[A-Z]{3}" : undefined}
          inputMode={field.kind === "decimal" ? "decimal" : undefined}
        />
      )}
    </label>
  );
}

export function AlertEditor({
  accountId,
  rule,
  destinations,
  now,
  canWrite,
}: Readonly<{
  accountId: string;
  rule?: AlertRuleDetail;
  destinations: NotificationDestination[];
  now: string;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const navigationRef = useNavigationVersionRef();
  const initial = rule?.latest_version.definition;
  const [metric, setMetric] = useState<AlertEditorMetric>(
    ALERT_METRICS.find((item) => item.metric === initial?.predicate.metric) ??
      ALERT_METRICS[0],
  );
  const [schedule, setSchedule] = useState(
    initial?.schedule.kind ?? "interval",
  );
  const [pending, startChange] = useAlertTransition();
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<AlertActionResult | null>(null);
  const mounted = useRef(true);
  const retry = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  function submit(event: FormEvent<HTMLFormElement>) {
    const generation = navigationRef.current;
    event.preventDefault();
    if (pending) return;
    let definition;
    try {
      definition = alertDefinitionFromForm(
        new FormData(event.currentTarget),
        metric,
      );
    } catch {
      setFeedback({
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Review the predicate, exact decimal values, source references and UTC schedule.",
        fields: [],
      });
      return;
    }
    const body = rule
      ? {
          kind: "create_version",
          rule_id: rule.id,
          if_match: `"${rule.id}:${rule.revision}"`,
          body: { definition },
        }
      : { kind: "create_rule", body: { account_id: accountId, definition } };
    const signature = JSON.stringify(body);
    if (retry.current?.signature !== signature)
      retry.current = { signature, key: crypto.randomUUID() };
    const key = retry.current.key;
    setSubmitting(true);
    startChange(async () => {
      const result = await submitAlertCommand({
        ...body,
        idempotency_key: key,
      });
      if (mounted.current) setSubmitting(false);
      if (!mounted.current || navigationRef.current !== generation) return;
      setFeedback(result);
      if (result.ok) {
        const id =
          result.kind === "rule"
            ? result.value.id
            : result.kind === "version"
              ? result.value.version.rule_id
              : rule?.id;
        startChange(() => {
          router.push(
            alertHref({ account: accountId, view: "rules", rule: id }),
          );
          return router.refresh();
        });
      }
    });
  }
  const predicate =
    initial?.predicate.metric === metric.metric
      ? (initial.predicate as unknown as Record<string, unknown>)
      : {};
  return (
    <Surface className={styles.surface}>
      <h2>
        {rule ? "Create an immutable rule version" : "Create an alert rule"}
      </h2>
      <p>
        Saving a definition does not activate it. Review the saved version, then
        activate it explicitly. Ratios use fractions; amounts require currency.
        Schedules use UTC.
      </p>
      {!canWrite ? (
        <Notice title="Alert editing unavailable">
          Alert write and analytics scopes are required. Existing rules and
          history remain readable.
        </Notice>
      ) : null}
      {feedback ? (
        <Notice
          title={feedback.ok ? "Rule definition saved" : feedback.code}
          tone={feedback.ok ? "info" : "danger"}
        >
          {feedback.ok
            ? "The new version is ready for review and explicit activation."
            : feedback.message}
        </Notice>
      ) : null}
      <form
        onSubmit={submit}
        className={styles.form}
        aria-label="Alert rule editor"
      >
        <fieldset
          disabled={!canWrite || pending || rule?.lifecycle === "archived"}
          className={styles.fields}
        >
          <legend>Rule definition</legend>
          <label>
            Rule name
            <input
              name="name"
              defaultValue={initial?.name ?? ""}
              required
              minLength={1}
              maxLength={120}
            />
          </label>
          <label>
            Rule family
            <select
              value={metric.family}
              onChange={(event) =>
                setMetric(
                  ALERT_METRICS.find(
                    (item) => item.family === event.target.value,
                  ) ?? ALERT_METRICS[0],
                )
              }
            >
              {ALERT_FAMILIES.map((family) => (
                <option key={family} value={family}>
                  {titleCase(family)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Metric
            <select
              value={metric.metric}
              onChange={(event) =>
                setMetric(
                  ALERT_METRICS.find(
                    (item) => item.metric === event.target.value,
                  ) ?? ALERT_METRICS[0],
                )
              }
            >
              {ALERT_METRICS.filter(
                (item) => item.family === metric.family,
              ).map((item) => (
                <option key={item.metric} value={item.metric}>
                  {titleCase(item.metric)}
                </option>
              ))}
            </select>
          </label>
          <fieldset className={styles.fields} key={metric.metric}>
            <legend>Predicate</legend>
            {metric.comparison !== "event" ? (
              <>
                {metric.comparison !== "boolean" ? (
                  <label>
                    Comparison
                    <select
                      name="comparison"
                      defaultValue={String(predicate.comparison ?? "gte")}
                    >
                      {[
                        ["gt", "Greater than"],
                        ["gte", "At least"],
                        ["lt", "Less than"],
                        ["lte", "At most"],
                        ["eq", "Equal"],
                      ].map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <p>Boolean comparison: equal.</p>
                )}
                <PredicateControl
                  field={{
                    key: "threshold",
                    label: "Threshold",
                    kind: metric.comparison,
                    min: metric.comparison === "integer" ? 0 : undefined,
                    initial: metric.comparison === "boolean" ? "true" : "0",
                  }}
                  initial={predicate.threshold}
                />
              </>
            ) : (
              <p>This event predicate has no threshold or comparison.</p>
            )}
            {metric.fields.map((field) => (
              <PredicateControl
                key={field.key}
                field={field}
                initial={predicate[field.key]}
              />
            ))}
          </fieldset>
          <label>
            Severity
            <select
              name="severity"
              defaultValue={initial?.severity ?? "warning"}
            >
              {["info", "warning", "critical"].map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Quality policy
            <select
              name="quality_policy"
              defaultValue={initial?.quality_policy ?? "require_complete"}
            >
              <option value="require_complete">Require complete data</option>
              <option value="allow_degraded">
                Allow degraded data with explicit quality
              </option>
            </select>
          </label>
          <label>
            Source policy version ID (optional)
            <input
              name="source_policy_version_id"
              defaultValue={initial?.source_policy_version_id ?? ""}
              maxLength={36}
            />
          </label>
          <label>
            Schedule
            <select
              name="schedule_kind"
              value={schedule}
              onChange={(event) =>
                setSchedule(event.target.value as "interval" | "daily_utc")
              }
            >
              <option value="interval">Fixed interval</option>
              <option value="daily_utc">Daily UTC</option>
            </select>
          </label>
          {schedule === "interval" ? (
            <>
              <label>
                Anchor time (UTC)
                <input
                  name="anchor_at"
                  type="text"
                  required
                  defaultValue={
                    initial?.schedule.kind === "interval"
                      ? initial.schedule.anchor_at
                      : now
                  }
                  placeholder="2026-09-10T00:00:00Z"
                />
              </label>
              <label>
                Interval (seconds)
                <input
                  name="interval_seconds"
                  type="number"
                  min={300}
                  max={86400}
                  step={1}
                  required
                  defaultValue={
                    initial?.schedule.kind === "interval"
                      ? initial.schedule.interval_seconds
                      : 300
                  }
                />
              </label>
            </>
          ) : (
            <label>
              Minute of day (UTC)
              <input
                name="minute_utc"
                type="number"
                min={0}
                max={1439}
                step={1}
                required
                defaultValue={
                  initial?.schedule.kind === "daily_utc"
                    ? initial.schedule.minute_utc
                    : 0
                }
              />
            </label>
          )}
          <label>
            Cooldown (seconds)
            <input
              name="cooldown_seconds"
              type="number"
              min={0}
              max={604800}
              step={1}
              required
              defaultValue={initial?.cooldown_seconds ?? 0}
            />
          </label>
          <label className={styles.wide}>
            Remediation description (optional)
            <textarea
              name="remediation"
              defaultValue={initial?.remediation ?? ""}
              maxLength={2000}
            />
          </label>
          <fieldset className={styles.fields}>
            <legend>Notification destinations</legend>
            <p className={styles.wide}>
              In-app delivery is durable. External destinations are configured
              on the server; no address, URL or credential is entered here.
            </p>
            {destinations.length === 0 ? (
              <p>
                No external destination is configured. In-app notifications
                remain available.
              </p>
            ) : (
              destinations.map((destination) => (
                <label className={styles.choice} key={destination.id}>
                  <input
                    type="checkbox"
                    name="destination_ids"
                    value={destination.id}
                    defaultChecked={initial?.destination_ids?.includes(
                      destination.id,
                    )}
                    disabled={
                      destination.state !== "configured" &&
                      !initial?.destination_ids?.includes(destination.id)
                    }
                  />
                  {destination.label} · {titleCase(destination.channel)} ·{" "}
                  {titleCase(destination.state)}
                </label>
              ))
            )}
            {initial?.destination_ids
              ?.filter((id) => !destinations.some((item) => item.id === id))
              .map((id) => (
                <label className={styles.choice} key={id}>
                  <input
                    type="checkbox"
                    name="destination_ids"
                    value={id}
                    defaultChecked
                  />
                  Keep saved destination {id} (metadata is not on this page)
                </label>
              ))}
          </fieldset>
          <Button type="submit">
            {submitting
              ? "Saving definition…"
              : rule
                ? "Save new version"
                : "Create rule"}
          </Button>
        </fieldset>
      </form>
    </Surface>
  );
}
