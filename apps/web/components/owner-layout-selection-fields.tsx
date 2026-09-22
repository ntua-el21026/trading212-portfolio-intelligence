"use client";
import type { OwnerLayoutWidget } from "@trading212/api-contracts";
import { layoutRoutes } from "../lib/owner-layout-query";
import styles from "./owner-layouts.module.css";

type Selection = NonNullable<OwnerLayoutWidget["selection"]>;
export function initialLayoutSelection(kind: Selection["kind"]): Selection {
  if (kind === "workspace") return { kind, route: "overview", pane: null };
  if (kind === "saved_run")
    return {
      kind,
      family: "risk",
      run_id: "",
      pane: "result",
      snapshot_id: null,
      source_cutoff_at: null,
      reporting_currency: null,
    };
  if (kind === "research")
    return {
      kind,
      xray_run_id: "",
      source_cutoff_at: "",
      entity_id: null,
      event_kind: null,
      review_state: "all",
    };
  return {
    kind,
    route: "performance",
    start_date: "",
    end_date: "",
    source_cutoff_at: "",
    reporting_currency: "",
    method: "twr",
    frequency: "monthly",
    knowledge: "as_of_cutoff",
    coverage: "require_complete",
    view: "summary",
    grouping: "holding",
    flow_kind: "all",
    rolling: "none",
    calendar: "none",
    capture_id: null,
  };
}
function Text({
  label,
  value,
  change,
  optional = false,
  date = false,
  maximum = 64,
}: Readonly<{
  label: string;
  value: string | null | undefined;
  change: (value: string) => void;
  optional?: boolean;
  date?: boolean;
  maximum?: number;
}>) {
  return (
    <label>
      <span>{label}</span>
      <input
        value={value ?? ""}
        onChange={(event) => change(event.target.value)}
        type={date ? "date" : "text"}
        maxLength={maximum}
        required={!optional}
        autoComplete="off"
      />
    </label>
  );
}
function Choice({
  label,
  value,
  options,
  change,
}: Readonly<{
  label: string;
  value: string | undefined;
  options: readonly string[];
  change: (value: string) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <select
        value={value ?? options[0]}
        onChange={(event) => change(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}
export function OwnerLayoutSelectionFields({
  value,
  change,
}: Readonly<{ value: Selection; change: (value: Selection) => void }>) {
  return (
    <fieldset>
      <legend>Saved view selection</legend>
      <div className={styles.fields}>
        <Choice
          label="Selection type"
          value={value.kind}
          options={["workspace", "saved_run", "historical", "research"]}
          change={(kind) =>
            change(initialLayoutSelection(kind as Selection["kind"]))
          }
        />
        {value.kind === "workspace" ? (
          <>
            <Choice
              label="Workspace"
              value={value.route}
              options={layoutRoutes}
              change={(route) =>
                change({
                  ...value,
                  route: route as typeof value.route,
                  pane: null,
                })
              }
            />
            {["risk", "scenarios", "projections"].includes(value.route) ? (
              <Choice
                label="Workspace pane"
                value={value.pane ?? "default"}
                options={
                  value.route === "projections"
                    ? ["default", "runs", "assumptions", "goals"]
                    : ["default", "runs", "definitions"]
                }
                change={(pane) =>
                  change({
                    ...value,
                    pane:
                      pane === "default" ? null : (pane as typeof value.pane),
                  })
                }
              />
            ) : null}
          </>
        ) : value.kind === "saved_run" ? (
          <>
            <Choice
              label="Saved run family"
              value={value.family}
              options={["risk", "scenario", "projection", "xray"]}
              change={(family) =>
                change({
                  ...value,
                  family: family as typeof value.family,
                  run_id: "",
                  pane: "result",
                  snapshot_id: family === "xray" ? "" : null,
                  source_cutoff_at: family === "xray" ? "" : null,
                  reporting_currency: family === "xray" ? "" : null,
                })
              }
            />
            <Text
              label="Saved run ID"
              value={value.run_id}
              maximum={36}
              change={(run_id) => change({ ...value, run_id })}
            />
            {value.family === "projection" ? (
              <Choice
                label="Saved run pane"
                value={value.pane}
                options={["result", "goal"]}
                change={(pane) =>
                  change({ ...value, pane: pane as typeof value.pane })
                }
              />
            ) : null}
            {value.family === "xray" ? (
              <>
                <Text
                  label="Original X-ray snapshot ID"
                  maximum={36}
                  value={value.snapshot_id}
                  change={(snapshot_id) => change({ ...value, snapshot_id })}
                />
                <Text
                  label="Original X-ray cutoff (ISO timestamp)"
                  value={value.source_cutoff_at}
                  change={(source_cutoff_at) =>
                    change({ ...value, source_cutoff_at })
                  }
                />
                <Text
                  label="Original X-ray reporting currency"
                  maximum={3}
                  value={value.reporting_currency}
                  change={(reporting_currency) =>
                    change({ ...value, reporting_currency })
                  }
                />
              </>
            ) : null}
          </>
        ) : value.kind === "research" ? (
          <>
            <Text
              label="Saved research X-ray ID"
              maximum={36}
              value={value.xray_run_id}
              change={(xray_run_id) => change({ ...value, xray_run_id })}
            />
            <Text
              label="Research cutoff (ISO timestamp)"
              value={value.source_cutoff_at}
              change={(source_cutoff_at) =>
                change({ ...value, source_cutoff_at })
              }
            />
            <Text
              label="Entity ID (optional)"
              maximum={36}
              optional
              value={value.entity_id}
              change={(entity_id) =>
                change({ ...value, entity_id: entity_id || null })
              }
            />
            <Choice
              label="Research event"
              value={value.event_kind ?? "all"}
              options={["all", "news", "company_overview"]}
              change={(event_kind) =>
                change({
                  ...value,
                  event_kind:
                    event_kind === "all"
                      ? null
                      : (event_kind as typeof value.event_kind),
                })
              }
            />
            <Choice
              label="Research review"
              value={value.review_state}
              options={["all", "reviewed", "unreviewed"]}
              change={(review_state) =>
                change({
                  ...value,
                  review_state: review_state as typeof value.review_state,
                })
              }
            />
          </>
        ) : (
          <>
            <Choice
              label="Historical workspace"
              value={value.route}
              options={["performance", "income"]}
              change={(route) =>
                change({
                  ...value,
                  route: route as typeof value.route,
                  view: route === "income" ? "income" : "summary",
                  grouping: "holding",
                })
              }
            />
            <Text
              label="Start date"
              date
              value={value.start_date}
              change={(start_date) => change({ ...value, start_date })}
            />
            <Text
              label="End date"
              date
              value={value.end_date}
              change={(end_date) => change({ ...value, end_date })}
            />
            <Text
              label="Historical cutoff (ISO timestamp)"
              value={value.source_cutoff_at}
              change={(source_cutoff_at) =>
                change({ ...value, source_cutoff_at })
              }
            />
            <Text
              label="Historical reporting currency"
              maximum={3}
              value={value.reporting_currency}
              change={(reporting_currency) =>
                change({ ...value, reporting_currency })
              }
            />
            <Text
              label="Saved historical capture ID (optional)"
              maximum={36}
              optional
              value={value.capture_id}
              change={(capture_id) =>
                change({ ...value, capture_id: capture_id || null })
              }
            />
            <Choice
              label="Historical view"
              value={value.view}
              options={
                value.route === "income"
                  ? ["income", "cash_flows"]
                  : ["summary", "series", "rolling", "calendar", "attribution"]
              }
              change={(view) =>
                change({ ...value, view: view as typeof value.view })
              }
            />
            <Choice
              label="Return method"
              value={value.method}
              options={
                value.view === "attribution"
                  ? ["twr", "modified_dietz"]
                  : ["twr", "mwr", "modified_dietz"]
              }
              change={(method) =>
                change({ ...value, method: method as typeof value.method })
              }
            />
            <Choice
              label="Frequency"
              value={value.frequency}
              options={["daily", "monthly"]}
              change={(frequency) =>
                change({
                  ...value,
                  frequency: frequency as typeof value.frequency,
                })
              }
            />
            <Choice
              label="Knowledge policy"
              value={value.knowledge}
              options={["as_of_cutoff", "point_in_time"]}
              change={(knowledge) =>
                change({
                  ...value,
                  knowledge: knowledge as typeof value.knowledge,
                })
              }
            />
            <Choice
              label="Coverage policy"
              value={value.coverage}
              options={["require_complete", "allow_degraded"]}
              change={(coverage) =>
                change({
                  ...value,
                  coverage: coverage as typeof value.coverage,
                })
              }
            />
            <Choice
              label="Grouping"
              value={value.grouping}
              options={
                value.route === "income"
                  ? ["holding", "group"]
                  : ["holding", "group", "sector", "asset_class", "currency"]
              }
              change={(grouping) =>
                change({
                  ...value,
                  grouping: grouping as typeof value.grouping,
                })
              }
            />
            <Choice
              label="Cash flow kind"
              value={value.flow_kind}
              options={[
                "all",
                "deposit",
                "withdrawal",
                "transfer_in",
                "transfer_out",
                "buy",
                "sell",
                "dividend",
                "interest",
                "fee",
                "tax",
                "internal_transfer",
                "fx_conversion",
                "corporate_action",
                "unknown",
              ]}
              change={(flow_kind) =>
                change({
                  ...value,
                  flow_kind: flow_kind as typeof value.flow_kind,
                })
              }
            />
            <Choice
              label="Rolling window"
              value={value.rolling}
              options={[
                "none",
                "calendar_days_30",
                "calendar_days_90",
                "calendar_days_365",
              ]}
              change={(rolling) =>
                change({ ...value, rolling: rolling as typeof value.rolling })
              }
            />
            <Choice
              label="Calendar period"
              value={value.calendar}
              options={["none", "month", "quarter", "year"]}
              change={(calendar) =>
                change({
                  ...value,
                  calendar: calendar as typeof value.calendar,
                })
              }
            />
          </>
        )}
      </div>
    </fieldset>
  );
}
