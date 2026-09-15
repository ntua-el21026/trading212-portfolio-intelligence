"use client";
import type { ComponentProps } from "react";
import type { CreateGoalRequest } from "@trading212/api-contracts";
import { Button } from "@trading212/ui";
import styles from "./projection-workspace.module.css";
export type DatedSchedule = CreateGoalRequest["content"]["schedule"];
export function emptySchedule(currency: string): DatedSchedule {
  return {
    base_monthly: { amount: "0", currency },
    annual_growth: "0",
    paused_dates: [],
    entries: [],
  };
}
export function ExactField({
  label,
  ...props
}: ComponentProps<"input"> & { label: string }) {
  return (
    <label>
      <span>{label}</span>
      <input
        type="text"
        inputMode="decimal"
        autoComplete="off"
        maxLength={160}
        {...props}
      />
    </label>
  );
}
export function ScheduleFields({
  value,
  onChange,
  disabled = false,
}: Readonly<{
  value: DatedSchedule;
  onChange: (value: DatedSchedule) => void;
  disabled?: boolean;
}>) {
  const entries = value.entries ?? [],
    paused = value.paused_dates ?? [];
  const full = entries.length + paused.length >= 128;
  return (
    <fieldset disabled={disabled}>
      <legend>Dated cash flows</legend>
      <p>
        Contributions occur at monthly anniversary boundaries, clamped to the
        month’s last day. Pauses and dated entries must match those boundaries
        within the horizon. Amounts use {value.base_monthly.currency}. A funding
        failure is retained even when rounded unpaid money is zero.
      </p>
      <div className={styles.fields}>
        <ExactField
          label="Base monthly contribution"
          value={value.base_monthly.amount}
          required
          onChange={(event) =>
            onChange({
              ...value,
              base_monthly: {
                ...value.base_monthly,
                amount: event.target.value,
              },
            })
          }
        />
        <ExactField
          label="Annual contribution growth (ratio)"
          value={value.annual_growth ?? "0"}
          required
          onChange={(event) =>
            onChange({ ...value, annual_growth: event.target.value })
          }
        />
      </div>
      {paused.map((date, index) => (
        <div className={styles.fields} key={index}>
          <label>
            Paused contribution date {index + 1}
            <input
              type="date"
              required
              value={date}
              onChange={(event) =>
                onChange({
                  ...value,
                  paused_dates: paused.map((item, i) =>
                    i === index ? event.target.value : item,
                  ),
                })
              }
            />
          </label>
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              onChange({
                ...value,
                paused_dates: paused.filter((_, i) => i !== index),
              })
            }
          >
            Remove pause {index + 1}
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="secondary"
        disabled={full}
        onClick={() => onChange({ ...value, paused_dates: [...paused, ""] })}
      >
        Add contribution pause
      </Button>
      {entries.map((entry, index) => (
        <fieldset key={index}>
          <legend>Dated entry {index + 1}</legend>
          <div className={styles.fields}>
            <label>
              Entry key
              <input
                required
                maxLength={120}
                value={entry.key}
                onChange={(event) =>
                  onChange({
                    ...value,
                    entries: entries.map((item, i) =>
                      i === index ? { ...item, key: event.target.value } : item,
                    ),
                  })
                }
              />
            </label>
            <label>
              Entry date
              <input
                type="date"
                required
                value={entry.on}
                onChange={(event) =>
                  onChange({
                    ...value,
                    entries: entries.map((item, i) =>
                      i === index ? { ...item, on: event.target.value } : item,
                    ),
                  })
                }
              />
            </label>
            <label>
              Entry type
              <select
                value={entry.kind}
                onChange={(event) =>
                  onChange({
                    ...value,
                    entries: entries.map((item, i) =>
                      i === index
                        ? {
                            ...item,
                            kind: event.target.value as
                              "lump_sum" | "withdrawal",
                          }
                        : item,
                    ),
                  })
                }
              >
                <option value="lump_sum">Lump sum contribution</option>
                <option value="withdrawal">Requested withdrawal</option>
              </select>
            </label>
            <ExactField
              label="Entry amount"
              value={entry.value.amount}
              required
              onChange={(event) =>
                onChange({
                  ...value,
                  entries: entries.map((item, i) =>
                    i === index
                      ? {
                          ...item,
                          value: { ...item.value, amount: event.target.value },
                        }
                      : item,
                  ),
                })
              }
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              onChange({
                ...value,
                entries: entries.filter((_, i) => i !== index),
              })
            }
          >
            Remove entry {index + 1}
          </Button>
        </fieldset>
      ))}
      <Button
        type="button"
        variant="secondary"
        disabled={full}
        onClick={() =>
          onChange({
            ...value,
            entries: [
              ...entries,
              {
                key: `entry_${crypto.randomUUID()}`,
                on: "",
                kind: "lump_sum",
                value: { amount: "0", currency: value.base_monthly.currency },
              },
            ],
          })
        }
      >
        Add dated cash flow
      </Button>
      <p>{entries.length + paused.length} of 128 dated entries and pauses.</p>
    </fieldset>
  );
}
