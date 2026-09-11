import Link from "next/link";
import { Fragment } from "react";
import { Notice, Surface } from "@trading212/ui";
import type {
  AlertEvaluationView,
  AlertEventDetail,
  AlertRuleDefinition,
  AlertRuleDetail,
} from "@trading212/api-contracts";
import { alertHref, type AlertQuery } from "../lib/alert-query";
import { formatDateTime, titleCase } from "../lib/format";
import {
  AlertEventCommands,
  AlertRuleCommands,
  AlertVersionActivation,
} from "./alert-commands";
type AlertObservedMetric = NonNullable<
  NonNullable<AlertEvaluationView["result"]>["observation"]
>;

import styles from "./alert-view.module.css";

export function AlertDefinition({
  definition,
}: Readonly<{ definition: AlertRuleDefinition }>) {
  return (
    <dl className={styles.facts}>
      <dt>Name</dt>
      <dd>{definition.name}</dd>
      {Object.entries(definition.predicate)
        .filter(([, value]) => value !== null && value !== undefined)
        .map(([key, value]) => (
          <Fragment key={key}>
            <dt>{titleCase(key)}</dt>
            <dd>
              {key === "minimum_net_amount" &&
              definition.predicate.metric === "positive_dividend"
                ? `${value} ${definition.predicate.currency}`
                : String(value)}
            </dd>
          </Fragment>
        ))}
      <dt>Severity / quality</dt>
      <dd>
        {titleCase(definition.severity)} ·{" "}
        {titleCase(definition.quality_policy ?? "require_complete")}
      </dd>
      <dt>Schedule</dt>
      <dd>
        {definition.schedule.kind === "interval"
          ? `Every ${definition.schedule.interval_seconds} seconds from ${formatDateTime(definition.schedule.anchor_at)}`
          : `Daily at minute ${definition.schedule.minute_utc} UTC`}
      </dd>
      <dt>Cooldown</dt>
      <dd>{definition.cooldown_seconds} seconds</dd>
      <dt>Source policy</dt>
      <dd>
        {definition.source_policy_version_id ??
          "Canonical adapter policy, pinned at evaluation"}
      </dd>
      <dt>Destinations</dt>
      <dd>
        {(definition.destination_ids ?? []).length
          ? (definition.destination_ids ?? []).join(", ")
          : "In-app only"}
      </dd>
      <dt>Remediation</dt>
      <dd>{definition.remediation || "No additional description"}</dd>
    </dl>
  );
}

function Observed({ metric }: Readonly<{ metric: AlertObservedMetric }>) {
  return (
    <dl className={styles.facts}>
      <dt>Metric</dt>
      <dd>{titleCase(metric.metric)}</dd>
      <dt>Observed value</dt>
      <dd>
        {metric.value === null ? "Unavailable" : String(metric.value)}
        {metric.currency ? ` ${metric.currency}` : ""}
      </dd>
      <dt>Availability / quality</dt>
      <dd>
        {titleCase(metric.availability)} · {titleCase(metric.quality)}
      </dd>
      <dt>Origin / bound</dt>
      <dd>
        {titleCase(metric.origin)} · {titleCase(metric.bound ?? "exact")}
        {metric.positive_below_quantum
          ? " · positive below display quantum"
          : ""}
      </dd>
      <dt>Context</dt>
      <dd>{metric.context_key}</dd>
      {metric.reason ? (
        <>
          <dt>Reason</dt>
          <dd>{titleCase(metric.reason)}</dd>
        </>
      ) : null}
    </dl>
  );
}

export function AlertEvaluation({
  evaluation,
}: Readonly<{ evaluation: AlertEvaluationView }>) {
  const result = evaluation.result;
  return (
    <article className={styles.entry}>
      <h3>
        {titleCase(evaluation.outcome)} ·{" "}
        {formatDateTime(evaluation.scheduled_for)}
      </h3>
      <dl className={styles.facts}>
        <dt>Evaluated</dt>
        <dd>{formatDateTime(evaluation.evaluated_at)}</dd>
        <dt>Execution / retention</dt>
        <dd>
          {titleCase(evaluation.execution_intent)} ·{" "}
          {titleCase(evaluation.reproducibility)}
        </dd>
        <dt>Decision</dt>
        <dd>
          {result?.decision === true
            ? "Matched"
            : result?.decision === false
              ? "Not matched"
              : "No conclusive decision"}
        </dd>
        <dt>Rule version</dt>
        <dd>{evaluation.rule_version_id}</dd>
        <dt>Rule / input / result hashes</dt>
        <dd>
          {evaluation.rule_content_digest}
          <br />
          {evaluation.input_digest}
          <br />
          {evaluation.result_digest}
        </dd>
        <dt>Retained until</dt>
        <dd>{formatDateTime(evaluation.expires_at)}</dd>
      </dl>
      {!result ? (
        <Notice title="Evaluation proof unavailable">
          {evaluation.reproducibility === "expired"
            ? "The licensed retention deadline has passed."
            : "Current source permissions restrict this proof."}{" "}
          The historical identity and outcome remain; no missing value is
          replaced with zero.
        </Notice>
      ) : (
        <>
          {result.reason ? (
            <p>Outcome reason: {titleCase(result.reason)}</p>
          ) : null}
          {result.observation ? <Observed metric={result.observation} /> : null}
          {(result.event_decisions ?? []).length ? (
            <details>
              <summary>
                Per-event decisions ({(result.event_decisions ?? []).length})
              </summary>
              {(result.event_decisions ?? []).map((event) => (
                <article
                  className={styles.entry}
                  key={`${event.identity}:${event.revision_id}`}
                >
                  <h4>
                    {titleCase(event.outcome)} · {event.identity}
                  </h4>
                  <p>
                    Revision {event.revision_id ?? "none"}; correction of{" "}
                    {event.correction_of ?? "none"}; reason{" "}
                    {event.reason ?? "none"}.
                  </p>
                  <Observed metric={event.observation} />
                </article>
              ))}
            </details>
          ) : null}
          <details>
            <summary>
              Method, coverage, warnings and source context (
              {result.contexts.length})
            </summary>
            {result.contexts.map((context) => (
              <section className={styles.entry} key={context.key}>
                <h4>{context.key}</h4>
                <dl className={styles.facts}>
                  <dt>Method</dt>
                  <dd>
                    {context.method_key} / {context.method_version}
                  </dd>
                  <dt>Valuation / cutoff</dt>
                  <dd>
                    {formatDateTime(context.valuation_at)} /{" "}
                    {formatDateTime(context.source_cutoff_at)}
                  </dd>
                  <dt>Quality / currency</dt>
                  <dd>
                    {titleCase(context.quality)} /{" "}
                    {context.reporting_currency ?? "Not monetary"}
                  </dd>
                  <dt>Reconciliation</dt>
                  <dd>
                    {context.reconciliation_id ?? "No reconciliation identity"}
                  </dd>
                </dl>
                <h5>Coverage</h5>
                {(context.coverage ?? []).length ? (
                  <ul>
                    {(context.coverage ?? []).map((fact) => (
                      <li key={fact.key}>
                        {fact.key}: {fact.available_count ?? "unknown"} /{" "}
                        {fact.expected_count ?? "unknown"}; complete{" "}
                        {fact.complete === null
                          ? "unknown"
                          : String(fact.complete)}
                        ; fraction {fact.covered_fraction ?? "unavailable"}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No additional coverage facts.</p>
                )}
                <h5>Warnings</h5>
                {(context.warnings ?? []).length ? (
                  <ul>
                    {(context.warnings ?? []).map((warning, index) => (
                      <li key={`${warning.code}:${index}`}>
                        {warning.code}: {warning.message}{" "}
                        {(warning.source_reference_keys ?? []).length
                          ? `Sources: ${(warning.source_reference_keys ?? []).join(", ")}`
                          : ""}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No warnings.</p>
                )}
                {(context.assumptions ?? []).length ? (
                  <>
                    <h5>Assumptions</h5>
                    <ul>
                      {(context.assumptions ?? []).map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </>
                ) : null}
                <p>
                  Source references:{" "}
                  {(context.source_reference_keys ?? []).join(", ") || "None"}
                </p>
              </section>
            ))}
          </details>
          {evaluation.definition ? (
            <details>
              <summary>Exact evaluated rule definition</summary>
              <AlertDefinition definition={evaluation.definition} />
            </details>
          ) : null}
          <details>
            <summary>
              Immutable inputs and licensed sources (
              {evaluation.source_references.length})
            </summary>
            <h4>Canonical input pins</h4>
            {evaluation.canonical_bindings.map((pin, index) => (
              <p key={`${pin.subject_id}:${pin.role}:${index}`}>
                {pin.family} / {pin.role}: {pin.subject_id}; hash{" "}
                {pin.content_digest}; parent {pin.parent_id ?? "none"}; method{" "}
                {pin.method_key ?? "none"} / {pin.method_version ?? "none"};
                numeric policy {pin.numeric_policy_version ?? "none"}.
              </p>
            ))}
            <h4>Sources</h4>
            {evaluation.source_references.map((source) => (
              <dl className={styles.facts} key={source.key}>
                <dt>{source.key}</dt>
                <dd>
                  {source.kind} · {source.subject_id}
                  <br />
                  Hash {source.content_digest}
                  <br />
                  Effective {formatDateTime(source.effective_at)}; observed{" "}
                  {formatDateTime(source.first_observed_at)}
                  <br />
                  Parent {source.parent_id ?? "none"}; provider{" "}
                  {source.provider_id ?? "none"}; license{" "}
                  {source.license_version_id ?? "none"}; expiry{" "}
                  {source.expires_at
                    ? formatDateTime(source.expires_at)
                    : "not specified"}
                </dd>
              </dl>
            ))}
            <h4>License metadata</h4>
            {evaluation.licenses.map((license, index) => (
              <pre key={index}>{JSON.stringify(license, null, 2)}</pre>
            ))}
          </details>
        </>
      )}
    </article>
  );
}

export function AlertRulePanel({
  rule,
  query,
  canWrite,
}: Readonly<{ rule: AlertRuleDetail; query: AlertQuery; canWrite: boolean }>) {
  return (
    <Surface className={styles.surface}>
      <h2>{rule.latest_version.definition.name}</h2>
      <p>
        {titleCase(rule.lifecycle)} · revision {rule.revision}. Latest version{" "}
        {rule.latest_version.version_number}; active version{" "}
        {rule.active_version?.version_number ?? "none"}.
      </p>
      <p>
        {rule.lifecycle === "active"
          ? `Next scheduled evaluation: ${rule.next_scheduled_for ? formatDateTime(rule.next_scheduled_for) : "Not scheduled"}.`
          : rule.lifecycle === "paused"
            ? "Scheduling paused. Activate a saved version to resume future evaluations."
            : rule.lifecycle === "archived"
              ? "Rule archived. No future evaluations are scheduled."
              : "Draft rule. Activate a saved version to schedule evaluations."}
      </p>
      <details open>
        <summary>Latest saved definition</summary>
        <AlertDefinition definition={rule.latest_version.definition} />
      </details>
      {rule.active_version &&
      rule.active_version.id !== rule.latest_version.id ? (
        <details>
          <summary>
            Active definition · version {rule.active_version.version_number}
          </summary>
          <AlertDefinition definition={rule.active_version.definition} />
        </details>
      ) : null}
      <AlertRuleCommands
        key={`${rule.id}:${rule.revision}`}
        rule={rule}
        canWrite={canWrite}
      />
      <h2>Immutable version history</h2>
      <p>
        Every saved version is retained, including definitions that were never
        activated.
      </p>
      {rule.version_page.items.map((version) => (
        <details key={version.id}>
          <summary>
            Saved version {version.version_number} ·{" "}
            {formatDateTime(version.created_at)}
          </summary>
          <p>
            Version ID {version.id}; content hash {version.content_digest}.
          </p>
          <AlertDefinition definition={version.definition} />
          <AlertVersionActivation
            key={`${version.id}:${rule.revision}`}
            rule={rule}
            version={version}
            canWrite={canWrite}
          />
        </details>
      ))}
      <nav className={styles.navigation} aria-label="Version pagination">
        <p>
          {rule.version_page.items.length} on this page /{" "}
          {rule.version_page.total} immutable versions.
        </p>
        {rule.version_page.next_cursor ? (
          <Link
            prefetch={false}
            href={alertHref({
              ...query,
              version_cursor: rule.version_page.next_cursor,
            })}
          >
            Next version page
          </Link>
        ) : (
          <p>End of version history.</p>
        )}
      </nav>
      <h2>Evaluation history</h2>
      <p>
        Includes matched, not matched, suppressed, quality-gap and failed
        evaluations. These outcomes are distinct from notifications.
      </p>
      {rule.evaluation_page.items.length ? (
        rule.evaluation_page.items.map((item) => (
          <AlertEvaluation key={item.id} evaluation={item} />
        ))
      ) : (
        <Notice title="No evaluations on this page">
          A saved draft is not evaluated until activated. Paused and archived
          rules do not schedule new evaluations.
        </Notice>
      )}
      <nav className={styles.navigation} aria-label="Evaluation pagination">
        <p>
          {rule.evaluation_page.items.length} on this page /{" "}
          {rule.evaluation_page.total} retained evaluations.
        </p>
        {rule.evaluation_page.next_cursor ? (
          <Link
            prefetch={false}
            href={alertHref({
              ...query,
              evaluation_cursor: rule.evaluation_page.next_cursor,
            })}
          >
            Next evaluation page
          </Link>
        ) : (
          <p>End of evaluation history.</p>
        )}
      </nav>
    </Surface>
  );
}

export function AlertEventPanel({
  event,
  canWrite,
}: Readonly<{ event: AlertEventDetail; canWrite: boolean }>) {
  return (
    <Surface className={styles.surface}>
      <h2>Alert event · {titleCase(event.severity)}</h2>
      <p>
        {titleCase(event.episode_state)} ·{" "}
        {event.acknowledgment ? "Acknowledged" : "Not acknowledged"} · revision{" "}
        {event.revision}
      </p>
      <dl className={styles.facts}>
        <dt>Occurred / recorded</dt>
        <dd>
          {formatDateTime(event.occurred_at)} /{" "}
          {formatDateTime(event.recorded_at)}
        </dd>
        <dt>Rule</dt>
        <dd>
          <Link
            href={alertHref({ account: event.account_id, rule: event.rule_id })}
          >
            {event.rule_id}
          </Link>
        </dd>
        <dt>Correction of</dt>
        <dd>{event.correction_of ?? "None"}</dd>
        <dt>Resolution</dt>
        <dd>
          {event.resolved_at
            ? `${formatDateTime(event.resolved_at)} · ${titleCase(event.resolution_reason ?? "unknown")}`
            : "Open"}
        </dd>
        <dt>Acknowledgment</dt>
        <dd>
          {event.acknowledgment
            ? `${formatDateTime(event.acknowledgment.acknowledged_at)} · ${event.acknowledgment.note ?? "No note"}`
            : "Not acknowledged"}
        </dd>
        <dt>Remediation</dt>
        <dd>
          {event.remediation ||
            "Review the recorded observation and source quality."}
        </dd>
      </dl>
      <AlertEventCommands
        key={`${event.id}:${event.revision}`}
        event={event}
        canWrite={canWrite}
      />
      <h3>Delivery</h3>
      <p>
        In-app notification {event.delivery.in_app_notification_id} ·{" "}
        {titleCase(event.delivery.notification_state)} ·{" "}
        {formatDateTime(event.delivery.created_at)}
      </p>
      {(event.delivery.external ?? []).length ? (
        <ul>
          {(event.delivery.external ?? []).map((delivery) => (
            <li key={delivery.id}>
              {titleCase(delivery.channel)} · {titleCase(delivery.state)} ·
              attempts {delivery.attempts} · destination{" "}
              {delivery.destination_id}
              {delivery.reason ? ` · ${delivery.reason}` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p>
          No external delivery was requested. No email or webhook success is
          implied.
        </p>
      )}
      <AlertEvaluation evaluation={event.evaluation} />
    </Surface>
  );
}
