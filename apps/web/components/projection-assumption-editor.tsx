"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  AssumptionSetResponse,
  AssumptionVersionResponse,
  CreateAssumptionSetRequest,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import {
  projectionSelectionHref,
  type ProjectionQuery,
} from "../lib/projection-query";
import { useProjectionCommand } from "./projection-command";
import { ExactField } from "./projection-fields";
import styles from "./projection-workspace.module.css";
type Content = CreateAssumptionSetRequest["content"];
export function ProjectionAssumptionEditor({
  accountId,
  currency,
  query,
  definition,
  version,
  canWrite,
}: Readonly<{
  accountId: string;
  currency: string;
  query: ProjectionQuery;
  definition?: AssumptionSetResponse;
  version?: AssumptionVersionResponse;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const [name, setName] = useState(version?.metadata.name ?? "");
  const [description, setDescription] = useState(
    version?.metadata.description ?? "",
  );
  const [content, setContent] = useState<Content>(
    () =>
      version?.content ?? {
        assets: [
          {
            key: "portfolio",
            annual_mean_log_return: "0",
            annual_volatility: "0",
            weight: "1",
          },
        ],
        correlation: [["1"]],
        reporting_currency: currency,
        annual_inflation: "0",
        annual_fee: "0",
        annual_tax_drag: null,
        rebalance: "none",
        calibration_pins: [],
      },
  );
  const action = useProjectionCommand((result) => {
    if (result.kind === "set")
      router.push(
        projectionSelectionHref(query, {
          view: "assumptions",
          set: result.value.id,
          version: result.value.current_version_id,
        }),
      );
    if (result.kind === "assumption_version")
      router.push(
        projectionSelectionHref(query, {
          view: "assumptions",
          set: result.value.set_id,
          version: result.value.id,
        }),
      );
  });
  function change(next: Content) {
    action.changed();
    setContent(next);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = { metadata: { name, description }, content };
    action.submit((idempotency_key) =>
      definition
        ? {
            kind: "create_assumption_version",
            account_id: accountId,
            set_id: definition.id,
            if_match: `"${definition.id}:${definition.revision}"`,
            body,
            idempotency_key,
          }
        : { kind: "create_set", account_id: accountId, body, idempotency_key },
    );
  }
  const pins = content.calibration_pins ?? [];
  return (
    <form
      aria-label="Projection assumptions"
      onSubmit={submit}
      className={styles.form}
    >
      <fieldset disabled={!canWrite || action.pending}>
        <legend>
          {definition
            ? "Save an immutable assumption version"
            : "Create an assumption set"}
        </legend>
        <p>
          These are explicit modeled assumptions, not calibrated expected
          returns or a guaranteed forecast. Returns are annual mean log returns;
          volatility is annual log-return volatility. Enter ratios as exact
          decimals, for example 0.05 for 5%.
        </p>
        <label>
          Assumption name
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
          <label>
            Reporting currency
            <input
              required
              pattern="[A-Z]{3}"
              maxLength={3}
              value={content.reporting_currency}
              onChange={(event) =>
                change({ ...content, reporting_currency: event.target.value })
              }
            />
          </label>
          <ExactField
            label="Annual inflation (ratio)"
            value={content.annual_inflation ?? "0"}
            required
            onChange={(event) =>
              change({ ...content, annual_inflation: event.target.value })
            }
          />
          <ExactField
            label="Annual fee (ratio)"
            value={content.annual_fee ?? "0"}
            required
            onChange={(event) =>
              change({ ...content, annual_fee: event.target.value })
            }
          />
          <ExactField
            label="Annual modeled tax drag (blank means not modeled)"
            value={content.annual_tax_drag ?? ""}
            onChange={(event) =>
              change({
                ...content,
                annual_tax_drag: event.target.value || null,
              })
            }
          />
          <label>
            Rebalancing
            <select
              value={content.rebalance ?? "none"}
              onChange={(event) =>
                change({
                  ...content,
                  rebalance: event.target.value as Content["rebalance"],
                })
              }
            >
              <option value="none">None</option>
              <option value="monthly">Monthly</option>
              <option value="annual">Annual</option>
            </select>
          </label>
        </div>
        <p>
          Use 1–12 asset groups. Weights must sum exactly to 1. Mean log returns
          range from −0.5 to 0.5; volatility from 0 to 1; inflation from −0.1 to
          0.5; fees and tax drag from 0 to 0.2.
        </p>
        {content.assets.map((asset, index) => (
          <fieldset key={index}>
            <legend>Asset {index + 1}</legend>
            <div className={styles.fields}>
              <label>
                Asset key
                <input
                  required
                  maxLength={120}
                  value={asset.key}
                  onChange={(event) =>
                    change({
                      ...content,
                      assets: content.assets.map((item, i) =>
                        i === index
                          ? { ...item, key: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              </label>
              {(
                [
                  ["annual_mean_log_return", "Annual mean log return"],
                  ["annual_volatility", "Annual volatility"],
                  ["weight", "Allocation weight"],
                ] as const
              ).map(([key, label]) => (
                <ExactField
                  key={key}
                  label={label}
                  required
                  value={asset[key]}
                  onChange={(event) =>
                    change({
                      ...content,
                      assets: content.assets.map((item, i) =>
                        i === index
                          ? { ...item, [key]: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              ))}
            </div>
            <Button
              type="button"
              variant="secondary"
              disabled={content.assets.length === 1}
              onClick={() =>
                change({
                  ...content,
                  assets: content.assets.filter((_, i) => i !== index),
                  correlation: content.correlation
                    .filter((_, i) => i !== index)
                    .map((row) => row.filter((_, i) => i !== index)),
                })
              }
            >
              Remove asset {index + 1}
            </Button>
          </fieldset>
        ))}
        <Button
          type="button"
          variant="secondary"
          disabled={content.assets.length >= 12}
          onClick={() =>
            change({
              ...content,
              assets: [
                ...content.assets,
                {
                  key: `asset_${content.assets.length + 1}`,
                  annual_mean_log_return: "0",
                  annual_volatility: "0",
                  weight: "0",
                },
              ],
              correlation: [
                ...content.correlation.map((row) => [...row, "0"]),
                [...content.assets.map(() => "0"), "1"],
              ],
            })
          }
        >
          Add asset group
        </Button>
        <fieldset>
          <legend>Asset correlation</legend>
          <p>
            Pairs are edited together to preserve symmetry. The server verifies
            that the complete matrix is positive semidefinite.
          </p>
          <div
            className="table-scroll"
            role="region"
            tabIndex={0}
            aria-label="Asset correlation matrix"
          >
            <table className={`data-table ${styles.matrix}`}>
              <caption>Correlation in the asset order above</caption>
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  {content.assets.map((asset, i) => (
                    <th scope="col" key={i}>
                      {asset.key}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {content.correlation.map((row, i) => (
                  <tr key={i}>
                    <th scope="row">{content.assets[i]?.key}</th>
                    {row.map((cell, j) => (
                      <td key={j}>
                        {i === j ? (
                          "1"
                        ) : i > j ? (
                          cell
                        ) : (
                          <input
                            aria-label={`Correlation asset ${i + 1} and ${j + 1}`}
                            inputMode="decimal"
                            required
                            value={cell}
                            onChange={(event) =>
                              change({
                                ...content,
                                correlation: content.correlation.map(
                                  (other, x) =>
                                    other.map((value, y) =>
                                      (x === i && y === j) ||
                                      (x === j && y === i)
                                        ? event.target.value
                                        : value,
                                    ),
                                ),
                              })
                            }
                          />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </fieldset>
        <fieldset>
          <legend>Optional saved calibration evidence</legend>
          <p>
            Pin an existing retained history or total-return source by ID and
            digest. Its current permissions and original lifetime are checked by
            the server. These pins do not replace the modeled returns above.
          </p>
          {pins.map((pin, index) => (
            <div className={styles.fields} key={index}>
              <label>
                Calibration subject ID
                <input
                  required
                  value={pin.subject_id}
                  onChange={(event) =>
                    change({
                      ...content,
                      calibration_pins: pins.map((item, i) =>
                        i === index
                          ? { ...item, subject_id: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              </label>
              <label>
                Calibration content digest
                <input
                  required
                  pattern="[0-9a-f]{64}"
                  value={pin.content_digest}
                  onChange={(event) =>
                    change({
                      ...content,
                      calibration_pins: pins.map((item, i) =>
                        i === index
                          ? { ...item, content_digest: event.target.value }
                          : item,
                      ),
                    })
                  }
                />
              </label>
              <Button
                type="button"
                variant="secondary"
                onClick={() =>
                  change({
                    ...content,
                    calibration_pins: pins.filter((_, i) => i !== index),
                  })
                }
              >
                Remove calibration pin {index + 1}
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            disabled={pins.length >= 256}
            onClick={() =>
              change({
                ...content,
                calibration_pins: [
                  ...pins,
                  { subject_id: "", content_digest: "" },
                ],
              })
            }
          >
            Add calibration pin
          </Button>
        </fieldset>
        <Button type="submit">
          {action.pending
            ? "Saving assumptions…"
            : definition
              ? "Save assumption version"
              : "Create assumption set"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Write access required">
          Saving assumptions requires projections:write.
        </Notice>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}
