"use client";

import { useState } from "react";
import type {
  Instrument,
  TargetContent,
  TargetNode,
  TargetConstraint,
  TargetExclusion,
  TargetVersionResponse,
} from "@trading212/api-contracts";
import { Button, Notice, StatusPill, Surface } from "@trading212/ui";

import { TargetCommandFeedback, useTargetCommand } from "./target-forms";
import { searchTargetInstruments } from "../lib/target-actions";

const constraintLabels: Record<TargetConstraint["kind"], string> = {
  minimum_funded_amount: "Minimum funded amount",
  amount_increment: "Funding increment",
  minimum_post_weight: "Minimum post-contribution weight",
  maximum_post_weight: "Maximum post-contribution weight",
  minimum_group_funding: "Minimum group funding",
  maximum_group_funding: "Maximum group funding",
  cash_reserve: "Cash reserve",
  eligible: "Funding eligibility",
  maximum_funded_lines: "Maximum funded holdings",
  priority: "Priority coefficient",
};
const amountKinds = new Set([
  "minimum_funded_amount",
  "amount_increment",
  "minimum_group_funding",
  "maximum_group_funding",
  "cash_reserve",
]);
const weightKinds = new Set([
  "minimum_post_weight",
  "maximum_post_weight",
  "cash_reserve",
]);
const portfolioKinds = new Set(["cash_reserve", "maximum_funded_lines"]);

function newConstraint(
  kind: TargetConstraint["kind"],
  currency: string,
  nodeKey: string | null,
): TargetConstraint {
  const value: TargetConstraint = {
    key: crypto.randomUUID(),
    kind,
    node_key: portfolioKinds.has(kind) ? null : nodeKey,
  };
  if (amountKinds.has(kind))
    return {
      ...value,
      amount: kind === "amount_increment" ? "0.01" : "0",
      currency,
    };
  if (weightKinds.has(kind))
    return { ...value, weight: kind === "maximum_post_weight" ? "1" : "0" };
  if (kind === "eligible") return { ...value, enabled: true };
  if (kind === "maximum_funded_lines") return { ...value, count: 256 };
  return { ...value, coefficient: "1" };
}

function nodeDepth(node: TargetNode, nodes: TargetNode[]): number {
  const visited = new Set<string>([node.key]);
  let parent = node.parent_key;
  let depth = 0;
  while (parent && depth < 8 && !visited.has(parent)) {
    visited.add(parent);
    depth += 1;
    parent = nodes.find((item) => item.key === parent)?.parent_key;
  }
  return depth;
}

function compareNodeOrder(left: TargetNode, right: TargetNode): number {
  const orderDifference = (left.order ?? 0) - (right.order ?? 0);
  if (orderDifference) return orderDifference;
  // Match the domain's Unicode code-point key order, without locale-dependent sorting.
  const leftKey = [...left.key];
  const rightKey = [...right.key];
  for (
    let index = 0;
    index < Math.min(leftKey.length, rightKey.length);
    index += 1
  ) {
    const difference =
      leftKey[index].codePointAt(0)! - rightKey[index].codePointAt(0)!;
    if (difference) return difference;
  }
  return leftKey.length - rightKey.length;
}

function orderedHierarchy(nodes: TargetNode[]): TargetNode[] {
  const ordered = [...nodes].sort(compareNodeOrder);
  const children = new Map<string | null, TargetNode[]>();
  for (const node of ordered) {
    const parent = node.parent_key ?? null;
    children.set(parent, [...(children.get(parent) ?? []), node]);
  }
  const result: TargetNode[] = [];
  const visited = new Set<string>();
  function visit(node: TargetNode) {
    if (visited.has(node.key)) return;
    visited.add(node.key);
    result.push(node);
    for (const child of children.get(node.key) ?? []) visit(child);
  }
  for (const node of children.get(null) ?? []) visit(node);
  // Invalid drafts remain editable: disconnected and cyclic nodes appear once.
  for (const node of ordered) visit(node);
  return result;
}

export function TargetEditor({
  version,
  etag,
  instruments: initialInstruments,
  instrumentTotal,
  instrumentCursor,
}: Readonly<{
  version: TargetVersionResponse;
  etag: string;
  instruments: Instrument[];
  instrumentTotal: number | null;
  instrumentCursor: string | null;
}>) {
  const [content, setContent] = useState<TargetContent>(version.content);
  const [effectiveAt, setEffectiveAt] = useState(
    version.effective_at.slice(0, 16),
  );
  const [effectiveAtChanged, setEffectiveAtChanged] = useState(false);
  const [changed, setChanged] = useState(false);
  const [normalize, setNormalize] = useState(false);
  const [catalog, setCatalog] = useState({
    items: initialInstruments,
    total: instrumentTotal,
    next_cursor: instrumentCursor,
  });
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogPending, setCatalogPending] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const instruments = catalog.items;
  async function searchCatalog(cursor?: string | null) {
    setCatalogPending(true);
    setCatalogError(null);
    try {
      const result = await searchTargetInstruments({
        query: catalogQuery,
        cursor,
      });
      if (result.ok) setCatalog(result.page);
      else setCatalogError(result.message);
    } catch {
      setCatalogError(
        "The catalog could not be loaded. Your target edits are preserved.",
      );
    } finally {
      setCatalogPending(false);
    }
  }
  const action = useTargetCommand();
  const editable = version.state === "draft";
  const nodes = orderedHierarchy(content.nodes);
  const constraints = content.constraints ?? [];
  const exclusions = content.exclusions ?? [];
  const validation = version.latest_validation;
  const currentValidation =
    validation &&
    (editable
      ? validation.result_revision === version.revision && !changed
      : validation.result_digest === version.content_digest);
  function update(next: TargetContent) {
    setContent(next);
    setChanged(true);
  }
  function updateNode(key: string, patch: Partial<TargetNode>) {
    update({
      ...content,
      nodes: nodes.map((node) =>
        node.key === key ? { ...node, ...patch } : node,
      ),
    });
  }
  function addNode(kind: TargetNode["kind"]) {
    if (kind === "holding" && catalog.total === null && !catalogPending)
      void searchCatalog();
    const roots = nodes
      .filter((node) => !node.parent_key)
      .sort(compareNodeOrder);
    const lastOrder = roots.length ? (roots.at(-1)?.order ?? 0) : -1;
    const compactRoots = lastOrder === 255;
    const rootOrders = new Map(roots.map((node, order) => [node.key, order]));
    update({
      ...content,
      nodes: [
        ...nodes.map((node) =>
          compactRoots && !node.parent_key
            ? { ...node, order: rootOrders.get(node.key)! }
            : node,
        ),
        {
          key: crypto.randomUUID(),
          parent_key: null,
          kind,
          name:
            kind === "cash"
              ? `${version.reporting_currency} cash`
              : kind === "group"
                ? "New group"
                : "New holding",
          order: compactRoots ? roots.length : lastOrder + 1,
          weight: "0",
          holding:
            kind === "holding"
              ? {
                  state: "unresolved",
                  requested_identifier: { kind: "isin", value: "UNRESOLVED" },
                  reason:
                    "Choose a canonical instrument or enter an identifier.",
                }
              : null,
        },
      ],
    });
  }
  function removeNode(key: string) {
    const removed = new Set([key]);
    for (let iteration = 0; iteration < nodes.length; iteration += 1) {
      for (const node of nodes)
        if (node.parent_key && removed.has(node.parent_key))
          removed.add(node.key);
    }
    update({
      ...content,
      nodes: nodes.filter((node) => !removed.has(node.key)),
      constraints: constraints.filter(
        (item) => !item.node_key || !removed.has(item.node_key),
      ),
      exclusions: exclusions.filter(
        (item) => !item.node_key || !removed.has(item.node_key),
      ),
    });
  }
  function updateConstraint(key: string, patch: Partial<TargetConstraint>) {
    update({
      ...content,
      constraints: constraints.map((item) =>
        item.key === key ? { ...item, ...patch } : item,
      ),
    });
  }
  function updateExclusion(key: string, patch: Partial<TargetExclusion>) {
    update({
      ...content,
      exclusions: exclusions.map((item) =>
        item.key === key ? { ...item, ...patch } : item,
      ),
    });
  }
  function precedingSibling(node: TargetNode): TargetNode | undefined {
    const siblings = nodes
      .filter((item) => (item.parent_key ?? null) === (node.parent_key ?? null))
      .sort(compareNodeOrder);
    return siblings[siblings.findIndex((item) => item.key === node.key) - 1];
  }
  function moveUp(node: TargetNode) {
    const previous = precedingSibling(node);
    if (!previous) return;
    const siblings = nodes
      .filter((item) => (item.parent_key ?? null) === (node.parent_key ?? null))
      .sort(compareNodeOrder);
    const index = siblings.findIndex((item) => item.key === node.key);
    [siblings[index - 1], siblings[index]] = [
      siblings[index],
      siblings[index - 1],
    ];
    const duplicateOrders =
      new Set(siblings.map((item) => item.order ?? 0)).size !== siblings.length;
    const correctedOrders = new Map(
      siblings.map((item, order) => [item.key, order]),
    );
    update({
      ...content,
      nodes: nodes.map((item) => {
        if (duplicateOrders && correctedOrders.has(item.key))
          return { ...item, order: correctedOrders.get(item.key)! };
        if (item.key === node.key)
          return { ...item, order: previous.order ?? 0 };
        if (item.key === previous.key)
          return { ...item, order: node.order ?? 0 };
        return item;
      }),
    });
  }
  const commandOptions = { version_id: version.id, if_match: etag };
  return (
    <div className="page-stack">
      <Surface>
        <div className="target-section-heading">
          <h2>Target hierarchy</h2>
          <StatusPill tone={editable ? "info" : "neutral"}>
            {version.state}
          </StatusPill>
        </div>
        <p className="muted">
          Weights are exact fractions of the parent: 0.25 means 25%. Every
          sibling group must sum to 1. Cash belongs at the top level.
        </p>
        {!editable ? (
          <Notice title="Published target content is locked">
            Create a draft version to change these targets. Lifecycle actions
            preserve the published content and its history.
          </Notice>
        ) : null}
        {editable ? (
          <details
            className="target-details"
            onToggle={(event) => {
              if (
                event.currentTarget.open &&
                catalog.total === null &&
                !catalogPending
              )
                void searchCatalog();
            }}
          >
            <summary>Find instruments for holding targets</summary>
            <form
              className="target-form"
              onSubmit={(event) => {
                event.preventDefault();
                void searchCatalog();
              }}
            >
              <label>
                Search instrument catalog
                <input
                  value={catalogQuery}
                  onChange={(event) => setCatalogQuery(event.target.value)}
                  maxLength={80}
                />
              </label>
              <Button
                type="submit"
                variant="secondary"
                disabled={catalogPending}
              >
                Search instruments
              </Button>
            </form>
            <p className="muted">
              {catalog.total === null
                ? "The instrument catalog has not been loaded."
                : `Holding selectors show ${catalog.items.length} instruments on this page out of ${catalog.total} matches.`}
            </p>
            {catalog.next_cursor ? (
              <Button
                variant="quiet"
                disabled={catalogPending}
                onClick={() => void searchCatalog(catalog.next_cursor)}
              >
                Next instruments
              </Button>
            ) : null}
            {catalogError ? <p role="alert">{catalogError}</p> : null}
          </details>
        ) : null}
        <fieldset
          disabled={!editable || action.pending}
          className="target-fieldset"
        >
          <legend className="sr-only">Target version content</legend>
          <label className="target-effective-date">
            Effective from (UTC)
            <input
              type="datetime-local"
              value={effectiveAt}
              onChange={(event) => {
                setEffectiveAt(event.target.value);
                setEffectiveAtChanged(true);
                setChanged(true);
              }}
              required
            />
          </label>
          <div className="target-node-list">
            {nodes.map((node, index) => (
              <article
                key={node.key}
                className="target-node"
                style={
                  {
                    "--node-depth": nodeDepth(node, nodes),
                  } as React.CSSProperties
                }
              >
                <div className="target-node__heading">
                  <span className="target-node__kind">{node.kind}</span>
                  <strong>{node.name}</strong>
                  <span className="muted">{index + 1}</span>
                </div>
                <div className="target-form">
                  <label>
                    Name
                    <input
                      aria-label={`Name for ${node.name}`}
                      value={node.name}
                      maxLength={120}
                      required
                      onChange={(event) =>
                        updateNode(node.key, { name: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Parent group
                    <select
                      aria-label={`Parent for ${node.name}`}
                      value={node.parent_key ?? ""}
                      onChange={(event) =>
                        updateNode(node.key, {
                          parent_key: event.target.value || null,
                        })
                      }
                    >
                      <option value="">Whole Pie</option>
                      {nodes
                        .filter(
                          (item) =>
                            item.kind === "group" &&
                            item.key !== node.key &&
                            node.kind !== "cash",
                        )
                        .map((item) => (
                          <option key={item.key} value={item.key}>
                            {item.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Target weight
                    <input
                      aria-label={`Weight for ${node.name}`}
                      inputMode="decimal"
                      value={node.weight}
                      onChange={(event) =>
                        updateNode(node.key, { weight: event.target.value })
                      }
                      required
                      pattern="(?:0|1)(?:\.[0-9]{1,18})?"
                    />
                  </label>
                  {node.holding ? (
                    <>
                      <label>
                        Instrument mapping
                        <select
                          aria-label={`Instrument for ${node.name}`}
                          value={
                            node.holding.state === "resolved"
                              ? `${node.holding.instrument_id}:${node.holding.preferred_listing_id ?? ""}`
                              : ""
                          }
                          onChange={(event) => {
                            const selected = instruments.find(
                              (item) =>
                                `${item.instrument_id}:${item.listing_id}` ===
                                event.target.value,
                            );
                            updateNode(node.key, {
                              holding: selected
                                ? {
                                    state: "resolved",
                                    instrument_id: selected.instrument_id,
                                    listing_id: null,
                                    preferred_listing_id: selected.listing_id,
                                    requested_identifier: null,
                                    reason:
                                      "Selected from canonical instrument catalog.",
                                  }
                                : {
                                    state: "unresolved",
                                    requested_identifier: {
                                      kind: "isin",
                                      value: "UNRESOLVED",
                                    },
                                    reason:
                                      "An identifier requires resolution.",
                                  },
                            });
                          }}
                        >
                          <option value="">Unresolved identifier</option>
                          {node.holding.state === "resolved" &&
                          !instruments.some(
                            (item) =>
                              item.instrument_id ===
                                node.holding?.instrument_id &&
                              item.listing_id ===
                                node.holding.preferred_listing_id,
                          ) ? (
                            <option
                              value={`${node.holding.instrument_id}:${node.holding.preferred_listing_id ?? ""}`}
                            >
                              Existing canonical mapping
                            </option>
                          ) : null}
                          {instruments.map((item) => (
                            <option
                              key={item.listing_id}
                              value={`${item.instrument_id}:${item.listing_id}`}
                            >
                              {item.ticker} · {item.name} ·{" "}
                              {item.trading_currency}
                            </option>
                          ))}
                        </select>
                      </label>
                      {node.holding.state === "resolved" ? (
                        <label>
                          Holding coverage
                          <select
                            aria-label={`Coverage for ${node.name}`}
                            value={
                              node.holding.listing_id ? "listing" : "instrument"
                            }
                            onChange={(event) =>
                              updateNode(node.key, {
                                holding: {
                                  ...node.holding!,
                                  listing_id:
                                    event.target.value === "listing"
                                      ? node.holding?.preferred_listing_id
                                      : null,
                                },
                              })
                            }
                          >
                            <option value="instrument">
                              All listings of this instrument
                            </option>
                            <option value="listing">
                              Selected listing only
                            </option>
                          </select>
                        </label>
                      ) : (
                        <>
                          <label>
                            Identifier kind
                            <select
                              value={
                                node.holding.requested_identifier?.kind ??
                                "isin"
                              }
                              onChange={(event) => {
                                const kind = event.target.value as
                                  "isin" | "provider_key" | "mic_ticker";
                                updateNode(node.key, {
                                  holding: {
                                    ...node.holding!,
                                    requested_identifier: {
                                      kind,
                                      value:
                                        node.holding?.requested_identifier
                                          ?.value ?? "",
                                      provider:
                                        kind === "provider_key"
                                          ? "trading212"
                                          : null,
                                    },
                                  },
                                });
                              }}
                            >
                              <option value="isin">ISIN</option>
                              <option value="mic_ticker">
                                Exchange MIC and ticker
                              </option>
                              <option value="provider_key">Provider key</option>
                            </select>
                          </label>
                          <label>
                            Identifier
                            <input
                              aria-label={`Identifier for ${node.name}`}
                              value={
                                node.holding.requested_identifier?.value ?? ""
                              }
                              maxLength={80}
                              required
                              onChange={(event) =>
                                updateNode(node.key, {
                                  holding: {
                                    ...node.holding!,
                                    requested_identifier: {
                                      ...node.holding!.requested_identifier!,
                                      value: event.target.value,
                                    },
                                  },
                                })
                              }
                            />
                          </label>
                          {node.holding.requested_identifier?.kind ===
                          "provider_key" ? (
                            <label>
                              Provider
                              <input
                                value={
                                  node.holding.requested_identifier.provider ??
                                  ""
                                }
                                maxLength={80}
                                required
                                onChange={(event) =>
                                  updateNode(node.key, {
                                    holding: {
                                      ...node.holding!,
                                      requested_identifier: {
                                        ...node.holding!.requested_identifier!,
                                        provider: event.target.value,
                                      },
                                    },
                                  })
                                }
                              />
                            </label>
                          ) : null}
                        </>
                      )}
                    </>
                  ) : null}
                </div>
                <div className="target-actions">
                  <Button
                    variant="quiet"
                    disabled={!precedingSibling(node)}
                    onClick={() => moveUp(node)}
                  >
                    Move up
                  </Button>
                  <Button variant="danger" onClick={() => removeNode(node.key)}>
                    Remove{" "}
                    {node.kind === "group" ? "group and children" : node.kind}
                  </Button>
                </div>
              </article>
            ))}
          </div>
          {nodes.length === 0 ? (
            <p className="muted">
              This draft has no targets. Add groups, holdings, or cash to begin.
            </p>
          ) : null}
          <div className="target-actions">
            <Button
              variant="secondary"
              disabled={nodes.length >= 256}
              onClick={() => addNode("group")}
            >
              Add group
            </Button>
            <Button
              variant="secondary"
              disabled={nodes.length >= 256}
              onClick={() => addNode("holding")}
            >
              Add holding
            </Button>
            <Button
              variant="secondary"
              disabled={
                nodes.length >= 256 ||
                nodes.some((node) => node.kind === "cash")
              }
              onClick={() => addNode("cash")}
            >
              Add cash
            </Button>
          </div>
          <details className="target-details">
            <summary>Funding constraints ({constraints.length})</summary>
            <p className="muted">
              Amounts use {version.reporting_currency}. Post-contribution
              weights are fractions of the whole portfolio. A cash reserve
              includes cash already held.
            </p>
            {constraints.map((item) => (
              <div className="target-rule" key={item.key}>
                <div className="target-form">
                  <label>
                    Constraint
                    <select
                      value={item.kind}
                      onChange={(event) => {
                        const replacement = newConstraint(
                          event.target.value as TargetConstraint["kind"],
                          version.reporting_currency,
                          item.node_key ?? nodes[0]?.key ?? null,
                        );
                        update({
                          ...content,
                          constraints: constraints.map((current) =>
                            current.key === item.key
                              ? { ...replacement, key: item.key }
                              : current,
                          ),
                        });
                      }}
                    >
                      {Object.entries(constraintLabels).map(([kind, label]) => (
                        <option key={kind} value={kind}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!portfolioKinds.has(item.kind) ? (
                    <label>
                      Applies to
                      <select
                        value={item.node_key ?? ""}
                        onChange={(event) =>
                          updateConstraint(item.key, {
                            node_key: event.target.value || null,
                          })
                        }
                      >
                        <option value="">Choose target</option>
                        {nodes.map((node) => (
                          <option key={node.key} value={node.key}>
                            {node.name} · {node.kind}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  {amountKinds.has(item.kind) ? (
                    <label>
                      Amount ({version.reporting_currency})
                      <input
                        inputMode="decimal"
                        value={item.amount ?? ""}
                        onChange={(event) =>
                          updateConstraint(item.key, {
                            amount: event.target.value || null,
                            currency: event.target.value
                              ? version.reporting_currency
                              : null,
                          })
                        }
                        required={item.kind !== "cash_reserve"}
                      />
                    </label>
                  ) : null}
                  {weightKinds.has(item.kind) ? (
                    <label>
                      Weight fraction
                      <input
                        inputMode="decimal"
                        value={item.weight ?? ""}
                        onChange={(event) =>
                          updateConstraint(item.key, {
                            weight: event.target.value || null,
                          })
                        }
                        required={item.kind !== "cash_reserve"}
                      />
                    </label>
                  ) : null}
                  {item.kind === "eligible" ? (
                    <label>
                      Eligible
                      <select
                        value={String(item.enabled)}
                        onChange={(event) =>
                          updateConstraint(item.key, {
                            enabled: event.target.value === "true",
                          })
                        }
                      >
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    </label>
                  ) : null}
                  {item.kind === "maximum_funded_lines" ? (
                    <label>
                      Maximum holdings
                      <input
                        type="number"
                        min={0}
                        max={256}
                        step={1}
                        value={item.count ?? 0}
                        onChange={(event) =>
                          updateConstraint(item.key, {
                            count: event.target.valueAsNumber,
                          })
                        }
                      />
                    </label>
                  ) : null}
                  {item.kind === "priority" ? (
                    <label>
                      Coefficient
                      <input
                        inputMode="decimal"
                        value={item.coefficient ?? "1"}
                        onChange={(event) =>
                          updateConstraint(item.key, {
                            coefficient: event.target.value,
                          })
                        }
                      />
                    </label>
                  ) : null}
                </div>
                <Button
                  variant="quiet"
                  onClick={() =>
                    update({
                      ...content,
                      constraints: constraints.filter(
                        (current) => current.key !== item.key,
                      ),
                    })
                  }
                >
                  Remove constraint
                </Button>
              </div>
            ))}
            <Button
              variant="secondary"
              disabled={constraints.length >= 256}
              onClick={() =>
                update({
                  ...content,
                  constraints: [
                    ...constraints,
                    newConstraint(
                      "cash_reserve",
                      version.reporting_currency,
                      null,
                    ),
                  ],
                })
              }
            >
              Add constraint
            </Button>
          </details>
          <details className="target-details">
            <summary>Exclusions ({exclusions.length})</summary>
            {exclusions.map((item) => (
              <div key={item.key} className="target-rule">
                <div className="target-form">
                  <label>
                    Exclude by
                    <select
                      value={
                        item.instrument_id
                          ? "instrument"
                          : item.listing_id
                            ? "listing"
                            : "node"
                      }
                      onChange={(event) =>
                        updateExclusion(item.key, {
                          node_key:
                            event.target.value === "node"
                              ? (nodes[0]?.key ?? null)
                              : null,
                          instrument_id:
                            event.target.value === "instrument"
                              ? (instruments[0]?.instrument_id ?? "")
                              : null,
                          listing_id:
                            event.target.value === "listing"
                              ? (instruments[0]?.listing_id ?? "")
                              : null,
                        })
                      }
                    >
                      <option value="node">Target node</option>
                      <option value="instrument">Instrument</option>
                      <option value="listing">Listing</option>
                    </select>
                  </label>
                  {item.instrument_id != null ? (
                    <label>
                      Instrument
                      <select
                        value={item.instrument_id}
                        onChange={(event) =>
                          updateExclusion(item.key, {
                            instrument_id: event.target.value,
                          })
                        }
                      >
                        {instruments
                          .filter(
                            (entry, index, all) =>
                              all.findIndex(
                                (candidate) =>
                                  candidate.instrument_id ===
                                  entry.instrument_id,
                              ) === index,
                          )
                          .map((entry) => (
                            <option
                              key={entry.instrument_id}
                              value={entry.instrument_id}
                            >
                              {entry.canonical_name}
                            </option>
                          ))}
                      </select>
                    </label>
                  ) : item.listing_id != null ? (
                    <label>
                      Listing
                      <select
                        value={item.listing_id}
                        onChange={(event) =>
                          updateExclusion(item.key, {
                            listing_id: event.target.value,
                          })
                        }
                      >
                        {instruments.map((entry) => (
                          <option
                            key={entry.listing_id}
                            value={entry.listing_id}
                          >
                            {entry.ticker} · {entry.trading_currency}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <label>
                      Target
                      <select
                        value={item.node_key ?? ""}
                        onChange={(event) =>
                          updateExclusion(item.key, {
                            node_key: event.target.value,
                          })
                        }
                      >
                        <option value="">Choose target</option>
                        {nodes.map((node) => (
                          <option key={node.key} value={node.key}>
                            {node.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <label>
                    Reason
                    <input
                      value={item.reason ?? ""}
                      maxLength={1000}
                      onChange={(event) =>
                        updateExclusion(item.key, {
                          reason: event.target.value,
                        })
                      }
                    />
                  </label>
                </div>
                <Button
                  variant="quiet"
                  onClick={() =>
                    update({
                      ...content,
                      exclusions: exclusions.filter(
                        (current) => current.key !== item.key,
                      ),
                    })
                  }
                >
                  Remove exclusion
                </Button>
              </div>
            ))}
            <Button
              variant="secondary"
              disabled={exclusions.length >= 256}
              onClick={() =>
                update({
                  ...content,
                  exclusions: [
                    ...exclusions,
                    {
                      key: crypto.randomUUID(),
                      node_key: nodes[0]?.key ?? null,
                      reason: "",
                    },
                  ],
                })
              }
            >
              Add exclusion
            </Button>
          </details>
        </fieldset>
        {editable ? (
          <div className="target-actions target-actions--save">
            <Button
              disabled={action.pending || !changed}
              onClick={() =>
                void action.run({
                  kind: "replace_draft",
                  ...commandOptions,
                  body: {
                    effective_at: effectiveAtChanged
                      ? `${effectiveAt}${effectiveAt.length === 16 ? ":00" : ""}Z`
                      : version.effective_at,
                    content,
                  },
                })
              }
            >
              {action.pending ? "Saving…" : "Save draft"}
            </Button>
            <span className="muted">
              {changed
                ? "Unsaved changes"
                : `Saved revision ${version.revision}`}
            </span>
          </div>
        ) : null}
        <TargetCommandFeedback result={action.result} />
      </Surface>
      <Surface>
        <h2>Validation and publication</h2>
        {editable ? (
          <>
            <p className="muted">
              Save your draft before validation. Normalization is optional and
              applies only to sibling sums within 0.000000000001 of 1.
            </p>
            <label className="target-checkbox">
              <input
                type="checkbox"
                checked={normalize}
                onChange={(event) => setNormalize(event.target.checked)}
                disabled={action.pending}
              />
              Normalize weights within the accepted tolerance and record every
              adjustment
            </label>
            <div className="target-actions">
              <Button
                variant="secondary"
                disabled={changed || action.pending}
                onClick={() =>
                  void action.run({
                    kind: "validate_version",
                    ...commandOptions,
                    body: { normalize },
                  })
                }
              >
                Validate target
              </Button>
              <Button
                disabled={
                  changed ||
                  action.pending ||
                  !validation?.valid ||
                  validation.result_revision !== version.revision
                }
                onClick={() =>
                  void action.run({
                    kind: "publish_version",
                    ...commandOptions,
                    body: { validation_id: validation!.id },
                  })
                }
              >
                Publish version
              </Button>
            </div>
          </>
        ) : null}
        {validation ? (
          <>
            <p>
              <StatusPill
                tone={
                  !currentValidation
                    ? "warning"
                    : validation.valid
                      ? "positive"
                      : "danger"
                }
              >
                {!currentValidation
                  ? "Historical validation"
                  : validation.valid
                    ? "Valid"
                    : "Validation failed"}
              </StatusPill>{" "}
              Evaluated {validation.evaluated_at} · result revision{" "}
              {validation.result_revision}
            </p>
            {validation.issues.length ? (
              <ul className="target-validation-issues">
                {validation.issues.map((issue, index) => (
                  <li key={`${issue.code}:${index}`}>
                    <strong>
                      {issue.severity}: {issue.code}
                    </strong>
                    <p>{issue.message}</p>
                    {issue.node_keys.length ? (
                      <p className="muted">
                        Targets:{" "}
                        {issue.node_keys
                          .map(
                            (key) =>
                              nodes.find((node) => node.key === key)?.name ??
                              key,
                          )
                          .join(", ")}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No validation issues.</p>
            )}
            {validation.adjustments.length ? (
              <div
                role="region"
                aria-label="Normalization adjustments"
                tabIndex={0}
                className="target-table-scroll"
              >
                <table>
                  <caption>Recorded normalization adjustments</caption>
                  <thead>
                    <tr>
                      <th>Target</th>
                      <th>Original weight</th>
                      <th>Normalized weight</th>
                      <th>Original sibling sum</th>
                      <th>Remainder rank</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validation.adjustments.map((item) => (
                      <tr key={item.node_key}>
                        <td>
                          {nodes.find((node) => node.key === item.node_key)
                            ?.name ?? item.node_key}
                        </td>
                        <td>{item.original_weight}</td>
                        <td>{item.normalized_weight}</td>
                        <td>{item.original_sibling_sum}</td>
                        <td>{item.remainder_rank}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            <p className="muted">
              Method {validation.method} · {validation.method_version}
            </p>
          </>
        ) : (
          <p className="muted">This version has not been validated.</p>
        )}
        {(version.flattened_nodes ?? []).length > 0 ? (
          <details className="target-details">
            <summary>Canonical effective weights</summary>
            <div
              role="region"
              aria-label="Effective target weights"
              tabIndex={0}
              className="target-table-scroll"
            >
              <table>
                <caption>Canonical effective target weights</caption>
                <thead>
                  <tr>
                    <th>Target</th>
                    <th>Depth</th>
                    <th>Effective weight</th>
                  </tr>
                </thead>
                <tbody>
                  {version.flattened_nodes.map((item) => (
                    <tr key={item.node.key}>
                      <td>{item.node.name}</td>
                      <td>{item.depth}</td>
                      <td>{item.effective_weight}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              Reported rounding residual:{" "}
              {version.effective_weight_rounding_residual ?? "Unavailable"}
            </p>
          </details>
        ) : null}
        {version.content_digest ? (
          <p className="target-digest">
            Content digest <code>{version.content_digest}</code>
          </p>
        ) : null}
        {version.state !== "archived" && version.state !== "superseded" ? (
          <div className="target-actions">
            <Button
              variant="danger"
              disabled={action.pending || changed}
              onClick={() =>
                void action.run({ kind: "archive_version", ...commandOptions })
              }
            >
              Archive version
            </Button>
            <span className="muted">
              Archiving the active version leaves this Pie without an active
              target.
            </span>
          </div>
        ) : null}
      </Surface>
    </div>
  );
}
