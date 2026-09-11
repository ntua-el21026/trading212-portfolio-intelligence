import {
  AlertRuleDefinitionSchema,
  type AlertRuleDefinition,
} from "@trading212/api-contracts";
import { REPORT_TYPES } from "./report-query";

type FieldKind = "uuid" | "decimal" | "integer" | "boolean" | "choice";
interface PredicateField {
  key: string;
  label: string;
  kind: FieldKind;
  optional?: boolean;
  options?: readonly string[];
  min?: number;
  max?: number;
  initial?: string;
}
interface MetricChoice {
  family: AlertRuleDefinition["predicate"]["family"];
  metric: AlertRuleDefinition["predicate"]["metric"];
  comparison: "decimal" | "integer" | "boolean" | "event";
  fields: readonly PredicateField[];
}
const target: PredicateField = {
  key: "target_version_id",
  label: "Published target version ID",
  kind: "uuid",
};
const source: PredicateField = {
  key: "source_id",
  label: "Source selection ID",
  kind: "uuid",
  optional: true,
};
const families = [
  "valuation",
  "history",
  "price",
  "fx",
  "constituent",
  "classification",
] as const;
const cash: PredicateField = {
  key: "include_cash",
  label: "Include cash",
  kind: "boolean",
  initial: "true",
};
const top: PredicateField = {
  key: "top_n",
  label: "Top holdings or companies",
  kind: "integer",
  min: 1,
  max: 50,
  initial: "25",
};
const currency: PredicateField = {
  key: "currency",
  label: "Currency",
  kind: "choice",
  options: [],
};
const window: PredicateField = {
  key: "window_seconds",
  label: "Observation window (seconds)",
  kind: "integer",
  min: 300,
  max: 2678400,
  initial: "86400",
};
const provider: PredicateField = {
  key: "provider_id",
  label: "Market-data provider ID",
  kind: "uuid",
};
const discrepancy: PredicateField = {
  key: "discrepancy_severity",
  label: "Discrepancy severity",
  kind: "choice",
  optional: true,
  options: ["info", "warning", "error", "critical"],
};
const activity: PredicateField = {
  key: "activity_kind",
  label: "Activity kind",
  kind: "choice",
  optional: true,
  options: [
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
  ],
};

// This is a closed presentation registry for the contract's 27 predicates.
export const ALERT_METRICS = [
  {
    family: "target_drift",
    metric: "portfolio_l1_drift",
    comparison: "decimal",
    fields: [
      target,
      {
        key: "frontier_depth",
        label: "Target frontier depth",
        kind: "integer",
        min: 1,
        max: 8,
        initial: "1",
      },
    ],
  },
  {
    family: "group_drift",
    metric: "group_absolute_drift",
    comparison: "decimal",
    fields: [
      target,
      { key: "group_node_id", label: "Target group node ID", kind: "uuid" },
    ],
  },
  {
    family: "holding_drift",
    metric: "holding_absolute_drift",
    comparison: "decimal",
    fields: [
      target,
      { key: "holding_id", label: "Canonical holding ID", kind: "uuid" },
    ],
  },
  {
    family: "concentration",
    metric: "direct_max_weight",
    comparison: "decimal",
    fields: [cash],
  },
  {
    family: "concentration",
    metric: "direct_top_n_weight",
    comparison: "decimal",
    fields: [cash, top],
  },
  {
    family: "concentration",
    metric: "direct_hhi",
    comparison: "decimal",
    fields: [cash],
  },
  {
    family: "effective_company_concentration",
    metric: "effective_entity_weight",
    comparison: "decimal",
    fields: [
      { key: "entity_id", label: "Canonical company entity ID", kind: "uuid" },
    ],
  },
  {
    family: "effective_company_concentration",
    metric: "effective_top_n_weight",
    comparison: "decimal",
    fields: [top],
  },
  {
    family: "effective_company_concentration",
    metric: "effective_hhi",
    comparison: "decimal",
    fields: [],
  },
  {
    family: "etf_overlap",
    metric: "etf_pair_overlap",
    comparison: "decimal",
    fields: [
      { key: "left_fund_id", label: "First canonical fund ID", kind: "uuid" },
      { key: "right_fund_id", label: "Second canonical fund ID", kind: "uuid" },
    ],
  },
  {
    family: "etf_overlap",
    metric: "portfolio_duplicated_exposure",
    comparison: "decimal",
    fields: [],
  },
  {
    family: "cash_threshold",
    metric: "cash_amount",
    comparison: "decimal",
    fields: [currency],
  },
  {
    family: "cash_threshold",
    metric: "cash_weight",
    comparison: "decimal",
    fields: [],
  },
  {
    family: "stale_data",
    metric: "source_age_seconds",
    comparison: "integer",
    fields: [
      {
        key: "source_family",
        label: "Source family",
        kind: "choice",
        options: families,
      },
      source,
    ],
  },
  {
    family: "stale_data",
    metric: "source_missing_sessions",
    comparison: "integer",
    fields: [
      {
        key: "source_family",
        label: "Source family",
        kind: "choice",
        options: families,
      },
      source,
      {
        key: "calendar_version_id",
        label: "Trading calendar version ID",
        kind: "uuid",
      },
    ],
  },
  {
    family: "missing_coverage",
    metric: "missing_count",
    comparison: "integer",
    fields: [
      {
        key: "domain",
        label: "Coverage domain",
        kind: "choice",
        options: families,
      },
      source,
    ],
  },
  {
    family: "missing_coverage",
    metric: "missing_fraction",
    comparison: "decimal",
    fields: [
      {
        key: "domain",
        label: "Coverage domain",
        kind: "choice",
        options: families,
      },
      source,
    ],
  },
  {
    family: "reconciliation_failure",
    metric: "reconciliation_failed",
    comparison: "boolean",
    fields: [discrepancy],
  },
  {
    family: "reconciliation_failure",
    metric: "reconciliation_discrepancy_count",
    comparison: "integer",
    fields: [discrepancy],
  },
  {
    family: "provider_failure",
    metric: "provider_failed",
    comparison: "boolean",
    fields: [provider, window],
  },
  {
    family: "provider_failure",
    metric: "provider_consecutive_failures",
    comparison: "integer",
    fields: [provider, window],
  },
  {
    family: "failed_refresh",
    metric: "refresh_failed",
    comparison: "event",
    fields: [
      {
        key: "capability_family",
        label: "Refresh capability",
        kind: "choice",
        optional: true,
        options: [
          "metadata_instruments",
          "metadata_exchanges",
          "account_summary",
          "portfolio_positions",
          "pending_orders",
          "historical_orders",
          "historical_transactions",
          "historical_dividends",
          "historical_exports",
        ],
      },
    ],
  },
  {
    family: "dividend_received",
    metric: "positive_dividend",
    comparison: "event",
    fields: [
      {
        key: "instrument_id",
        label: "Canonical instrument ID",
        kind: "uuid",
        optional: true,
      },
      {
        key: "minimum_net_amount",
        label: "Minimum positive net dividend",
        kind: "decimal",
        optional: true,
      },
      { ...currency, optional: true },
    ],
  },
  {
    family: "unusual_activity",
    metric: "absolute_external_flow_amount",
    comparison: "decimal",
    fields: [window, activity, currency],
  },
  {
    family: "unusual_activity",
    metric: "activity_count",
    comparison: "integer",
    fields: [window, activity],
  },
  {
    family: "unusual_activity",
    metric: "unclassified_activity",
    comparison: "event",
    fields: [window, activity],
  },
  {
    family: "report_outcome",
    metric: "report_terminal",
    comparison: "event",
    fields: [
      {
        key: "report_type",
        label: "Report type",
        kind: "choice",
        options: ["all", ...REPORT_TYPES],
      },
      {
        key: "outcome",
        label: "Report outcome",
        kind: "choice",
        options: ["succeeded", "failed", "either"],
      },
    ],
  },
] as const satisfies readonly MetricChoice[];

export type AlertEditorMetric = MetricChoice;
export type AlertEditorField = PredicateField;

export function alertDefinitionFromForm(
  data: FormData,
  selected: MetricChoice,
): AlertRuleDefinition {
  const predicate: Record<string, unknown> = {
    family: selected.family,
    metric: selected.metric,
  };
  for (const field of selected.fields) {
    const value = String(data.get(field.key) ?? "");
    if (field.optional && !value) continue;
    predicate[field.key] =
      field.kind === "integer"
        ? Number(value)
        : field.kind === "boolean"
          ? value === "true"
          : value;
  }
  if (selected.comparison !== "event") {
    predicate.comparison =
      selected.comparison === "boolean" ? "eq" : data.get("comparison");
    const threshold = String(data.get("threshold") ?? "");
    predicate.threshold =
      selected.comparison === "integer"
        ? Number(threshold)
        : selected.comparison === "boolean"
          ? threshold === "true"
          : threshold;
  }
  const interval = data.get("schedule_kind") === "interval";
  return AlertRuleDefinitionSchema.parse({
    name: data.get("name"),
    predicate,
    severity: data.get("severity"),
    quality_policy: data.get("quality_policy"),
    schedule: interval
      ? {
          kind: "interval",
          anchor_at: data.get("anchor_at"),
          interval_seconds: Number(data.get("interval_seconds")),
        }
      : { kind: "daily_utc", minute_utc: Number(data.get("minute_utc")) },
    cooldown_seconds: Number(data.get("cooldown_seconds")),
    destination_ids: data.getAll("destination_ids"),
    source_policy_version_id: data.get("source_policy_version_id") || null,
    remediation: data.get("remediation") ?? "",
  });
}
