import { z } from "zod";

export const ALERT_FAMILIES = [
  "target_drift",
  "group_drift",
  "holding_drift",
  "concentration",
  "effective_company_concentration",
  "etf_overlap",
  "cash_threshold",
  "stale_data",
  "missing_coverage",
  "reconciliation_failure",
  "provider_failure",
  "failed_refresh",
  "dividend_received",
  "unusual_activity",
  "report_outcome",
] as const;
export const ALERT_SEVERITIES = ["info", "warning", "critical"] as const;
export const ALERT_RULE_STATES = [
  "draft",
  "active",
  "paused",
  "archived",
] as const;
export const ALERT_EVENT_STATES = ["open", "resolved"] as const;

const page = z
  .string()
  .regex(/^[1-9][0-9]{0,2}$/)
  .transform(Number)
  .pipe(z.number().int().min(1).max(100));
const cursor = z.string().regex(/^[A-Za-z0-9_-]{1,2048}$/);
const querySchema = z
  .strictObject({
    account: z.string().uuid().optional(),
    view: z.enum(["rules", "events"]).default("rules"),
    rule: z.string().uuid().optional(),
    event: z.string().uuid().optional(),
    rule_state: z.enum([...ALERT_RULE_STATES, "all"]).default("all"),
    event_state: z.enum([...ALERT_EVENT_STATES, "all"]).default("all"),
    family: z.enum([...ALERT_FAMILIES, "all"]).default("all"),
    severity: z.enum([...ALERT_SEVERITIES, "all"]).default("all"),
    start_date: z.iso.date().optional(),
    end_date: z.iso.date().optional(),
    cursor: cursor.optional(),
    limit: page.optional(),
    evaluation_cursor: cursor.optional(),
    evaluation_limit: page.optional(),
    destination_cursor: cursor.optional(),
    version_cursor: cursor.optional(),
    version_limit: page.optional(),
  })
  .superRefine((value, context) => {
    if (Boolean(value.start_date) !== Boolean(value.end_date)) {
      context.addIssue({
        code: "custom",
        message: "Supply both history dates.",
      });
    }
    if (value.start_date && value.end_date) {
      const span =
        (Date.parse(value.end_date) - Date.parse(value.start_date)) /
        86_400_000;
      if (span < 0 || span > 3660)
        context.addIssue({
          code: "custom",
          message: "The history period exceeds its bounds.",
        });
    }
  });

export type AlertSearch = Record<string, string | string[] | undefined>;
export type AlertQuery = z.output<typeof querySchema>;

export function parseAlertUrl(
  search: Pick<URLSearchParams, "keys" | "getAll">,
): AlertQuery {
  const values = Object.create(null) as AlertSearch;
  for (const key of search.keys()) {
    const all = search.getAll(key);
    values[key] = all.length === 1 ? all[0] : all;
  }
  return parseAlertQuery(values);
}

export function parseAlertQuery(search: AlertSearch): AlertQuery {
  // Keep duplicate values as arrays: strict scalar validation must reject them.
  const optional = new Set([
    "account",
    "rule",
    "event",
    "start_date",
    "end_date",
    "cursor",
    "limit",
    "evaluation_cursor",
    "evaluation_limit",
    "destination_cursor",
    "version_cursor",
    "version_limit",
  ]);
  return querySchema.parse(
    Object.fromEntries(
      Object.entries(search).filter(
        ([key, value]) => !(optional.has(key) && value === ""),
      ),
    ),
  );
}

export function alertHref(query: Partial<AlertQuery>): string {
  const values = new URLSearchParams();
  for (const [key, value] of Object.entries(query))
    if (value !== undefined) values.set(key, String(value));
  const parsed = parseAlertQuery(Object.fromEntries(values));
  const normalized = new URLSearchParams();
  for (const [key, value] of Object.entries(parsed))
    if (value !== undefined) normalized.set(key, String(value));
  return `/alerts${normalized.size ? `?${normalized}` : ""}`;
}
