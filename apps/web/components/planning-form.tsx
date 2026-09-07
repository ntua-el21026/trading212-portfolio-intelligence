"use client";

import { useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type {
  CreateContributionPlanRequest,
  PlanningConstraint,
} from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";

import {
  submitPlanningCommand,
  type PlanningActionResult,
} from "../lib/planning-actions";
import type { PlanningTargetOption } from "../lib/planning-types";
import { titleCase } from "../lib/format";

const constraintKinds = [
  "minimum_funded_amount",
  "amount_increment",
  "minimum_post_weight",
  "maximum_post_weight",
  "minimum_group_funding",
  "maximum_group_funding",
  "cash_reserve",
  "eligible",
  "maximum_funded_lines",
  "priority",
] as const;

function ConstraintEditor({
  value,
  index,
  targets,
  currency,
  onChange,
  onRemove,
}: Readonly<{
  value: PlanningConstraint;
  index: number;
  targets: PlanningTargetOption[];
  currency: string;
  onChange: (value: PlanningConstraint) => void;
  onRemove: () => void;
}>) {
  const amount = [
    "minimum_funded_amount",
    "amount_increment",
    "minimum_group_funding",
    "maximum_group_funding",
    "cash_reserve",
  ].includes(value.kind);
  const weight = [
    "minimum_post_weight",
    "maximum_post_weight",
    "cash_reserve",
  ].includes(value.kind);
  return (
    <fieldset className="planning-constraint target-form">
      <legend>Constraint {index + 1}</legend>
      <label>
        <span>Constraint type</span>
        <select
          value={value.kind}
          onChange={(event) =>
            onChange({
              key: value.key,
              kind: event.target.value as PlanningConstraint["kind"],
              ...(event.target.value === "eligible" ? { enabled: true } : {}),
            })
          }
        >
          {constraintKinds.map((kind) => (
            <option key={kind} value={kind}>
              {titleCase(kind)}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Target scope</span>
        <select
          value={value.node_id ?? ""}
          onChange={(event) =>
            onChange({ ...value, node_id: event.target.value || null })
          }
        >
          <option value="">Whole portfolio</option>
          {targets.map((target) => (
            <option key={target.id} value={target.id}>
              {target.node.name} · {target.node.kind}
            </option>
          ))}
        </select>
      </label>
      {amount ? (
        <label>
          <span>Amount ({currency})</span>
          <input
            inputMode="decimal"
            value={value.amount ?? ""}
            onChange={(event) =>
              onChange({
                ...value,
                amount: event.target.value || null,
                currency: event.target.value ? currency : null,
              })
            }
            maxLength={40}
          />
        </label>
      ) : null}
      {weight ? (
        <label>
          <span>Weight (0–1)</span>
          <input
            inputMode="decimal"
            value={value.weight ?? ""}
            onChange={(event) =>
              onChange({ ...value, weight: event.target.value || null })
            }
            maxLength={40}
          />
        </label>
      ) : null}
      {value.kind === "maximum_funded_lines" ? (
        <label>
          <span>Maximum lines</span>
          <input
            type="number"
            min={0}
            max={256}
            step={1}
            value={value.count ?? ""}
            onChange={(event) =>
              onChange({
                ...value,
                count:
                  event.target.value === "" ? null : Number(event.target.value),
              })
            }
          />
        </label>
      ) : null}
      {value.kind === "eligible" ? (
        <label>
          <span>Eligibility</span>
          <select
            value={value.enabled === false ? "no" : "yes"}
            onChange={(event) =>
              onChange({ ...value, enabled: event.target.value === "yes" })
            }
          >
            <option value="yes">Eligible</option>
            <option value="no">Excluded</option>
          </select>
        </label>
      ) : null}
      {value.kind === "priority" ? (
        <label>
          <span>Priority coefficient</span>
          <input
            inputMode="decimal"
            value={value.coefficient ?? ""}
            onChange={(event) =>
              onChange({ ...value, coefficient: event.target.value || null })
            }
            maxLength={40}
          />
        </label>
      ) : null}
      <button type="button" onClick={onRemove}>
        Remove constraint {index + 1}
      </button>
    </fieldset>
  );
}

export function PlanningForm({
  initial,
  targets,
  revision,
}: Readonly<{
  initial: CreateContributionPlanRequest;
  targets: PlanningTargetOption[];
  revision?: { planId: string; etag: string };
}>) {
  const router = useRouter();
  const [body, setBody] = useState(initial);
  const [result, setResult] = useState<PlanningActionResult | null>(null);
  const [pending, startTransition] = useTransition();
  const requestIdentity = useRef<{ body: string; key: string } | null>(null);
  const holdings = targets.filter(
    (target) => target.node.kind === "holding" && target.holding_id,
  );
  const groups = targets.filter((target) => target.node.kind === "group");
  const set = <K extends keyof CreateContributionPlanRequest>(
    key: K,
    value: CreateContributionPlanRequest[K],
  ) => setBody((previous) => ({ ...previous, [key]: value }));
  const toggle = (
    key:
      "eligible_holding_ids" | "excluded_holding_ids" | "restricted_group_ids",
    id: string,
    enabled: boolean,
  ) => {
    setBody((previous) => {
      const selected = new Set(previous[key] ?? []);
      if (enabled) selected.add(id);
      else selected.delete(id);
      const next = { ...previous, [key]: [...selected].sort() };
      if (
        enabled &&
        key === "excluded_holding_ids" &&
        next.eligible_holding_ids
      )
        next.eligible_holding_ids = next.eligible_holding_ids.filter(
          (item) => item !== id,
        );
      if (enabled && key === "eligible_holding_ids")
        next.excluded_holding_ids = (next.excluded_holding_ids ?? []).filter(
          (item) => item !== id,
        );
      return next;
    });
  };

  function submit() {
    const serialized = JSON.stringify(body);
    if (requestIdentity.current?.body !== serialized)
      requestIdentity.current = { body: serialized, key: crypto.randomUUID() };
    const idempotencyKey = requestIdentity.current.key;
    startTransition(async () => {
      try {
        const response = await submitPlanningCommand(
          revision
            ? {
                kind: "revise",
                plan_id: revision.planId,
                if_match: revision.etag,
                body,
                idempotency_key: idempotencyKey,
              }
            : { kind: "create", body, idempotency_key: idempotencyKey },
        );
        setResult(response);
        if (response.ok) router.push(`/planner/${response.job.plan_id}`);
      } catch {
        setResult({
          ok: false,
          code: "PLANNING_UNAVAILABLE",
          message:
            "Your inputs are preserved; retry when the service is available.",
        });
      }
    });
  }

  return (
    <Surface>
      <h2>{revision ? "Calculate a new revision" : "Plan a contribution"}</h2>
      <p className="muted">
        A manual proposal using the selected snapshot and published target.
        Existing cash is retained. Every amount remains in{" "}
        {body.contribution.currency}.
      </p>
      {result && !result.ok ? (
        <Notice
          title={
            result.code === "REVISION_MISMATCH"
              ? "This plan changed in another session"
              : "Plan could not be queued"
          }
          tone="danger"
        >
          {result.message}
          {result.code === "REVISION_MISMATCH"
            ? " Copy your inputs before reloading the current revision."
            : null}
        </Notice>
      ) : null}
      {result?.ok ? (
        <Notice title="Plan queued">
          The request is stored. Its calculation status will appear on the plan
          page.
        </Notice>
      ) : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <fieldset className="target-fieldset" disabled={pending}>
          <legend className="ui-visually-hidden">Contribution request</legend>
          <div className="target-form">
            <label>
              <span>Contribution ({body.contribution.currency})</span>
              <input
                required
                inputMode="decimal"
                value={body.contribution.amount}
                onChange={(event) =>
                  set("contribution", {
                    ...body.contribution,
                    amount: event.target.value,
                  })
                }
                maxLength={40}
              />
            </label>
            <label>
              <span>Optimization mode</span>
              <select
                value={body.mode}
                onChange={(event) => {
                  const mode = event.target
                    .value as CreateContributionPlanRequest["mode"];
                  setBody((previous) => ({
                    ...previous,
                    mode,
                    restricted_group_ids:
                      mode === "restricted"
                        ? previous.restricted_group_ids
                        : [],
                  }));
                }}
              >
                <option value="global">Global — all targets</option>
                <option value="hierarchical">
                  Hierarchical — groups first
                </option>
                <option value="restricted">Restricted — selected groups</option>
                <option value="cash_only">Cash only</option>
              </select>
            </label>
            <label>
              <span>Coverage policy</span>
              <select
                value={body.coverage_policy ?? "require_complete"}
                onChange={(event) =>
                  set(
                    "coverage_policy",
                    event.target
                      .value as CreateContributionPlanRequest["coverage_policy"],
                  )
                }
              >
                <option value="require_complete">
                  Require complete inputs
                </option>
                <option value="allow_degraded">
                  Allow disclosed degraded inputs
                </option>
              </select>
            </label>
            <label>
              <span>
                Minimum total cash after contribution (
                {body.contribution.currency})
              </span>
              <input
                inputMode="decimal"
                value={body.cash_reserve ?? ""}
                onChange={(event) =>
                  set("cash_reserve", event.target.value || null)
                }
                maxLength={40}
                placeholder="No additional reserve"
              />
            </label>
            <label>
              <span>Amount precision</span>
              <input
                inputMode="decimal"
                value={body.monetary_quantum ?? ""}
                onChange={(event) =>
                  set("monetary_quantum", event.target.value || null)
                }
                maxLength={40}
                placeholder="Currency minor unit"
              />
            </label>
          </div>
          {body.mode === "restricted" ? (
            <fieldset className="planning-checks">
              <legend>Groups eligible for new funds</legend>
              {groups.map((group) => (
                <label key={group.id}>
                  <input
                    type="checkbox"
                    checked={(body.restricted_group_ids ?? []).includes(
                      group.id,
                    )}
                    onChange={(event) =>
                      toggle(
                        "restricted_group_ids",
                        group.id,
                        event.target.checked,
                      )
                    }
                  />
                  {group.node.name}
                </label>
              ))}
              {!groups.length ? (
                <p>
                  This target has no groups. Choose another optimization mode.
                </p>
              ) : null}
            </fieldset>
          ) : null}
          <details className="target-details">
            <summary>
              Eligible holdings, exclusions and listing preferences
            </summary>
            <label className="planning-check">
              <input
                type="checkbox"
                checked={
                  body.eligible_holding_ids !== null &&
                  body.eligible_holding_ids !== undefined
                }
                onChange={(event) =>
                  set(
                    "eligible_holding_ids",
                    event.target.checked
                      ? holdings
                          .map((item) => item.holding_id!)
                          .filter(
                            (id) =>
                              !(body.excluded_holding_ids ?? []).includes(id),
                          )
                      : null,
                  )
                }
              />
              Choose an explicit set of eligible holdings
            </label>
            <div className="target-form">
              {holdings.map((target) => {
                const holdingId = target.holding_id!;
                const preference = body.listing_preferences?.find(
                  (item) => item.holding_id === holdingId,
                );
                return (
                  <fieldset className="planning-holding" key={holdingId}>
                    <legend>{target.node.name}</legend>
                    {body.eligible_holding_ids ? (
                      <label className="planning-check">
                        <input
                          type="checkbox"
                          checked={body.eligible_holding_ids.includes(
                            holdingId,
                          )}
                          onChange={(event) =>
                            toggle(
                              "eligible_holding_ids",
                              holdingId,
                              event.target.checked,
                            )
                          }
                        />
                        Eligible for new funds
                      </label>
                    ) : null}
                    <label className="planning-check">
                      <input
                        type="checkbox"
                        checked={(body.excluded_holding_ids ?? []).includes(
                          holdingId,
                        )}
                        onChange={(event) =>
                          toggle(
                            "excluded_holding_ids",
                            holdingId,
                            event.target.checked,
                          )
                        }
                      />
                      Exclude from new funds
                    </label>
                    <label>
                      <span>Preferred listing ID for {target.node.name}</span>
                      <input
                        value={preference?.listing_id ?? ""}
                        maxLength={36}
                        placeholder={
                          target.node.holding?.preferred_listing_id ??
                          target.node.holding?.listing_id ??
                          "Use resolved mapping"
                        }
                        onChange={(event) =>
                          set(
                            "listing_preferences",
                            [
                              ...(body.listing_preferences ?? []).filter(
                                (item) => item.holding_id !== holdingId,
                              ),
                              ...(event.target.value
                                ? [
                                    {
                                      holding_id: holdingId,
                                      listing_id: event.target.value,
                                    },
                                  ]
                                : []),
                            ].sort((left, right) =>
                              left.holding_id.localeCompare(right.holding_id),
                            ),
                          )
                        }
                      />
                    </label>
                    <p className="muted">
                      Mapping: {target.node.holding?.state ?? "unresolved"}. The
                      server verifies that the selected listing belongs to this
                      holding.
                    </p>
                  </fieldset>
                );
              })}
            </div>
          </details>
          <details
            className="target-details"
            open={Boolean(body.allocation_constraints?.length)}
          >
            <summary>Allocation and hierarchy constraints</summary>
            <p className="muted">
              Published target constraints remain in force. Minimum funded
              amounts apply only to funded holdings; group funding minimums
              require funding.
            </p>
            {(body.allocation_constraints ?? []).map((constraint, index) => (
              <ConstraintEditor
                key={constraint.key}
                value={constraint}
                index={index}
                targets={targets}
                currency={body.contribution.currency}
                onChange={(value) =>
                  set(
                    "allocation_constraints",
                    (body.allocation_constraints ?? []).map((item, position) =>
                      position === index ? value : item,
                    ),
                  )
                }
                onRemove={() =>
                  set(
                    "allocation_constraints",
                    (body.allocation_constraints ?? []).filter(
                      (_, position) => position !== index,
                    ),
                  )
                }
              />
            ))}
            <button
              type="button"
              disabled={(body.allocation_constraints?.length ?? 0) >= 256}
              onClick={() =>
                set("allocation_constraints", [
                  ...(body.allocation_constraints ?? []),
                  {
                    key: `override-${crypto.randomUUID()}`,
                    kind: "minimum_funded_amount",
                    node_id: holdings[0]?.id ?? null,
                    amount: "0",
                    currency: body.contribution.currency,
                  },
                ])
              }
            >
              Add allocation constraint
            </button>
          </details>
          <details
            className="target-details"
            open={Boolean(body.holding_constraints?.length)}
          >
            <summary>Combined holding overrides</summary>
            <p className="muted">
              These minimum, increment and maximum-weight overrides are
              preserved when revising a plan created through MCP.
            </p>
            {(body.holding_constraints ?? []).map((constraint, index) => (
              <fieldset
                className="planning-constraint target-form"
                key={constraint.holding_id}
              >
                <legend>Holding override {index + 1}</legend>
                <label>
                  <span>Holding for override {index + 1}</span>
                  <select
                    value={constraint.holding_id}
                    onChange={(event) =>
                      set(
                        "holding_constraints",
                        (body.holding_constraints ?? []).map(
                          (item, position) =>
                            position === index
                              ? { ...item, holding_id: event.target.value }
                              : item,
                        ),
                      )
                    }
                  >
                    {!holdings.some(
                      (item) => item.holding_id === constraint.holding_id,
                    ) ? (
                      <option value={constraint.holding_id}>
                        Unresolved holding · {constraint.holding_id}
                      </option>
                    ) : null}
                    {holdings.map((target) => (
                      <option
                        key={target.holding_id}
                        value={target.holding_id!}
                      >
                        {target.node.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Minimum funded amount for override {index + 1}</span>
                  <input
                    inputMode="decimal"
                    maxLength={40}
                    value={constraint.minimum_amount}
                    onChange={(event) =>
                      set(
                        "holding_constraints",
                        (body.holding_constraints ?? []).map(
                          (item, position) =>
                            position === index
                              ? { ...item, minimum_amount: event.target.value }
                              : item,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  <span>Value increment for override {index + 1}</span>
                  <input
                    inputMode="decimal"
                    maxLength={40}
                    value={constraint.value_increment}
                    onChange={(event) =>
                      set(
                        "holding_constraints",
                        (body.holding_constraints ?? []).map(
                          (item, position) =>
                            position === index
                              ? { ...item, value_increment: event.target.value }
                              : item,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  <span>Maximum post weight for override {index + 1}</span>
                  <input
                    inputMode="decimal"
                    maxLength={40}
                    value={constraint.maximum_post_weight ?? ""}
                    onChange={(event) =>
                      set(
                        "holding_constraints",
                        (body.holding_constraints ?? []).map(
                          (item, position) =>
                            position === index
                              ? {
                                  ...item,
                                  maximum_post_weight:
                                    event.target.value || null,
                                }
                              : item,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  onClick={() =>
                    set(
                      "holding_constraints",
                      (body.holding_constraints ?? []).filter(
                        (_, position) => position !== index,
                      ),
                    )
                  }
                >
                  Remove holding override {index + 1}
                </button>
              </fieldset>
            ))}
            <button
              type="button"
              disabled={
                (body.holding_constraints?.length ?? 0) >= 256 ||
                !holdings.some(
                  (target) =>
                    !body.holding_constraints?.some(
                      (item) => item.holding_id === target.holding_id,
                    ),
                )
              }
              onClick={() => {
                const available = holdings.find(
                  (target) =>
                    !body.holding_constraints?.some(
                      (item) => item.holding_id === target.holding_id,
                    ),
                );
                if (available?.holding_id)
                  set("holding_constraints", [
                    ...(body.holding_constraints ?? []),
                    {
                      holding_id: available.holding_id,
                      minimum_amount: "0",
                      value_increment: "1",
                      maximum_post_weight: null,
                    },
                  ]);
              }}
            >
              Add holding override
            </button>
          </details>
          <div className="target-actions planning-submit">
            <button type="submit" disabled={pending}>
              {pending
                ? "Queuing plan…"
                : revision
                  ? "Calculate new revision"
                  : "Calculate contribution plan"}
            </button>
            <span className="muted">No orders are placed.</span>
          </div>
        </fieldset>
      </form>
    </Surface>
  );
}
