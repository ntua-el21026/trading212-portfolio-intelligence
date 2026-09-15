"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  ScenarioVersionContent,
  ScenarioDefinitionResponse,
  ScenarioVersionResponse,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import { scenarioHref, type ScenarioQuery } from "../lib/scenario-query";
import { useScenarioCommand } from "./scenario-command";
import styles from "./scenario-workspace.module.css";

type Shock = NonNullable<ScenarioVersionContent["shocks"]>[number];
type Exclusion = NonNullable<ScenarioVersionContent["exclusions"]>[number];
type Selector = Exclusion["selector"];

function emptySelector(kind: Selector["kind"]): Selector {
  switch (kind) {
    case "instrument":
      return { kind, instrument_id: "" };
    case "entity":
      return { kind, entity_id: "" };
    case "economic_currency":
      return { kind, currency: "EUR" };
    case "region":
    case "sector":
      return { kind, taxonomy_id: "", taxonomy_version: "", bucket_key: "" };
  }
}
function emptyShock(kind: Shock["kind"]): Shock {
  if (kind === "price")
    return {
      kind,
      size: "0",
      selector: { kind: "instrument", instrument_id: "" },
    };
  if (kind === "fx")
    return {
      kind,
      size: "0",
      selector: { kind: "economic_currency", currency: "EUR" },
    };
  return {
    kind,
    size: "0",
    source: {
      version_id: "",
      content_digest: "",
      driver_id: "",
      driver_definition_version_id: "",
    },
  };
}

function SelectorFields({
  value,
  onChange,
  priceOnly = false,
}: Readonly<{
  value: Selector;
  onChange: (value: Selector) => void;
  priceOnly?: boolean;
}>) {
  return (
    <>
      <label>
        Match by
        <select
          value={value.kind}
          onChange={(event) =>
            onChange(emptySelector(event.target.value as Selector["kind"]))
          }
        >
          <option value="instrument">Instrument</option>
          <option value="entity">Economic entity</option>
          <option value="sector">Sector</option>
          <option value="region">Region</option>
          {!priceOnly ? (
            <option value="economic_currency">Economic currency</option>
          ) : null}
        </select>
      </label>
      {value.kind === "instrument" ? (
        <label>
          Instrument ID
          <input
            required
            value={value.instrument_id}
            maxLength={36}
            onChange={(event) =>
              onChange({ ...value, instrument_id: event.target.value })
            }
          />
        </label>
      ) : null}
      {value.kind === "entity" ? (
        <label>
          Economic entity ID
          <input
            required
            value={value.entity_id}
            maxLength={36}
            onChange={(event) =>
              onChange({ ...value, entity_id: event.target.value })
            }
          />
        </label>
      ) : null}
      {value.kind === "economic_currency" ? (
        <label>
          Economic currency
          <input
            required
            value={value.currency}
            pattern="[A-Z]{3}"
            maxLength={3}
            onChange={(event) =>
              onChange({ ...value, currency: event.target.value })
            }
          />
        </label>
      ) : null}
      {value.kind === "sector" || value.kind === "region" ? (
        <>
          <label>
            Taxonomy ID
            <input
              required
              value={value.taxonomy_id}
              maxLength={36}
              onChange={(event) =>
                onChange({ ...value, taxonomy_id: event.target.value })
              }
            />
          </label>
          <label>
            Taxonomy version
            <input
              required
              value={value.taxonomy_version}
              maxLength={120}
              onChange={(event) =>
                onChange({ ...value, taxonomy_version: event.target.value })
              }
            />
          </label>
          <label>
            Bucket key
            <input
              required
              value={value.bucket_key}
              maxLength={120}
              onChange={(event) =>
                onChange({ ...value, bucket_key: event.target.value })
              }
            />
          </label>
        </>
      ) : null}
    </>
  );
}

function ShockFields({
  value,
  onChange,
}: Readonly<{ value: Shock; onChange: (value: Shock) => void }>) {
  return (
    <>
      <label>
        Shock channel
        <select
          value={value.kind}
          onChange={(event) =>
            onChange(emptyShock(event.target.value as Shock["kind"]))
          }
        >
          <option value="price">Price</option>
          <option value="fx">FX</option>
          <option value="rate">Rate sensitivity</option>
          <option value="factor">Factor sensitivity</option>
        </select>
      </label>
      {value.kind === "price" ? (
        <SelectorFields
          value={value.selector}
          priceOnly
          onChange={(selector) => {
            if (selector.kind !== "economic_currency")
              onChange({ ...value, selector });
          }}
        />
      ) : null}
      {value.kind === "fx" ? (
        <label>
          Economic currency
          <input
            required
            maxLength={3}
            pattern="[A-Z]{3}"
            value={value.selector.currency}
            onChange={(event) =>
              onChange({
                ...value,
                selector: {
                  kind: "economic_currency",
                  currency: event.target.value,
                },
              })
            }
          />
        </label>
      ) : null}
      {value.kind === "rate" || value.kind === "factor" ? (
        <>
          <p className={styles.full}>
            Select an existing licensed sensitivity version using its saved
            identifiers. Coefficients come from that retained source.
          </p>
          {(
            [
              ["version_id", "Sensitivity version ID"],
              ["content_digest", "Sensitivity content digest"],
              ["driver_id", "Driver ID"],
              ["driver_definition_version_id", "Driver definition version ID"],
            ] as const
          ).map(([key, label]) => (
            <label key={key}>
              {label}
              <input
                required
                value={value.source[key]}
                maxLength={key === "content_digest" ? 64 : 36}
                onChange={(event) =>
                  onChange({
                    ...value,
                    source: { ...value.source, [key]: event.target.value },
                  })
                }
              />
            </label>
          ))}
        </>
      ) : null}
      <label>
        {value.kind === "rate" ? "Absolute rate change" : "Simple return shock"}
        <input
          required
          inputMode="decimal"
          value={value.size}
          maxLength={40}
          onChange={(event) => onChange({ ...value, size: event.target.value })}
        />
      </label>
      <p className={styles.full}>
        {value.kind === "rate"
          ? "0.01 means a one percentage point rate increase."
          : "0.10 means a 10% increase; −0.10 means a 10% decrease."}{" "}
        {value.kind === "rate" || value.kind === "factor"
          ? "Supported range: −1 to 1."
          : "Supported range: −1 to 5."}
      </p>
    </>
  );
}

export function ScenarioDefinitionForm({
  accountId,
  query,
  definition,
  version,
  canWrite,
}: Readonly<{
  accountId: string;
  query: ScenarioQuery;
  definition?: ScenarioDefinitionResponse;
  version?: ScenarioVersionResponse;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const [content, setContent] = useState<ScenarioVersionContent>(
    () =>
      version?.content ?? {
        name: "Portfolio scenario",
        description: "",
        mode: "compounded",
        shocks: [],
        exclusions: [],
        method_version: "1.0.0",
      },
  );
  const [shockIds, setShockIds] = useState(() =>
    (version?.content.shocks ?? []).map((_, index) => `saved-shock-${index}`),
  );
  const [exclusionIds, setExclusionIds] = useState(() =>
    (version?.content.exclusions ?? []).map(
      (_, index) => `saved-exclusion-${index}`,
    ),
  );
  const action = useScenarioCommand((result) => {
    if (result.kind === "definition")
      router.push(
        scenarioHref(query, {
          view: "definitions",
          definition: result.value.id,
          version: result.value.current_version_id,
          versions_cursor: null,
          definitions_cursor: null,
        }),
      );
    if (result.kind === "version")
      router.push(
        scenarioHref(query, {
          view: "definitions",
          definition: result.value.definition_id,
          version: result.value.id,
          versions_cursor: null,
        }),
      );
  });
  function change(value: Partial<ScenarioVersionContent>) {
    action.changed();
    setContent((previous) => ({ ...previous, ...value }));
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    action.submit((idempotency_key) =>
      definition
        ? {
            kind: "create_version",
            account_id: accountId,
            definition_id: definition.id,
            if_match: `"${definition.id}:${definition.revision}"`,
            idempotency_key,
            body: { content },
          }
        : {
            kind: "create_definition",
            account_id: accountId,
            idempotency_key,
            body: { content },
          },
    );
  }
  const shocks = content.shocks ?? [];
  const exclusions = content.exclusions ?? [];
  return (
    <form
      onSubmit={submit}
      className={styles.form}
      aria-label={
        definition ? "New scenario version" : "Create scenario definition"
      }
    >
      <fieldset
        disabled={!canWrite || action.pending}
        className={styles.fields}
      >
        <legend>
          {definition
            ? `Based on saved version ${version?.version_number}`
            : "Scenario assumptions"}
        </legend>
        <label>
          Name
          <input
            required
            maxLength={120}
            value={content.name}
            onChange={(event) => change({ name: event.target.value })}
          />
        </label>
        <label>
          Calculation mode
          <select
            value={content.mode}
            onChange={(event) =>
              change({
                mode: event.target.value as ScenarioVersionContent["mode"],
              })
            }
          >
            <option value="compounded">Compounded channels</option>
            <option value="first_order">First order sum</option>
          </select>
        </label>
        <label className={styles.full}>
          Description
          <textarea
            maxLength={1024}
            value={content.description ?? ""}
            onChange={(event) => change({ description: event.target.value })}
          />
        </label>
        <p className={styles.full}>
          These are explicit hypothetical assumptions. Missing source evidence
          remains uncovered. For historical replay, save a version with no
          hypothetical shocks.
        </p>
        <div className={styles.full}>
          <h3>Shocks · {shocks.length}/128</h3>
          {shocks.map((shock, index) => (
            <fieldset className={styles.fields} key={shockIds[index]}>
              <legend>Shock {index + 1}</legend>
              <ShockFields
                value={shock}
                onChange={(value) =>
                  change({
                    shocks: shocks.map((item, at) =>
                      at === index ? value : item,
                    ),
                  })
                }
              />
              <Button
                variant="quiet"
                onClick={() => {
                  change({ shocks: shocks.filter((_, at) => at !== index) });
                  setShockIds((ids) => ids.filter((_, at) => at !== index));
                }}
              >
                Remove shock {index + 1}
              </Button>
            </fieldset>
          ))}
          <Button
            variant="secondary"
            disabled={shocks.length >= 128}
            onClick={() => {
              change({ shocks: [...shocks, emptyShock("price")] });
              setShockIds((ids) => [...ids, crypto.randomUUID()]);
            }}
          >
            Add shock
          </Button>
        </div>
        <div className={styles.full}>
          <h3>Exclusions · {exclusions.length}/128</h3>
          {exclusions.map((exclusion, index) => (
            <fieldset className={styles.fields} key={exclusionIds[index]}>
              <legend>Exclusion {index + 1}</legend>
              <SelectorFields
                value={exclusion.selector}
                onChange={(selector) =>
                  change({
                    exclusions: exclusions.map((item, at) =>
                      at === index ? { selector } : item,
                    ),
                  })
                }
              />
              <Button
                variant="quiet"
                onClick={() => {
                  change({
                    exclusions: exclusions.filter((_, at) => at !== index),
                  });
                  setExclusionIds((ids) => ids.filter((_, at) => at !== index));
                }}
              >
                Remove exclusion {index + 1}
              </Button>
            </fieldset>
          ))}
          <Button
            variant="secondary"
            disabled={exclusions.length >= 128}
            onClick={() => {
              change({
                exclusions: [
                  ...exclusions,
                  { selector: emptySelector("instrument") },
                ],
              });
              setExclusionIds((ids) => [...ids, crypto.randomUUID()]);
            }}
          >
            Add exclusion
          </Button>
        </div>
        <Button type="submit">
          {action.pending
            ? "Saving assumptions…"
            : definition
              ? "Save new scenario version"
              : "Create scenario"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Read-only access">
          Saving assumptions requires scenarios:write, portfolio:read and
          analytics:read.
        </Notice>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}
