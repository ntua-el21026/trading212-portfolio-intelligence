import { z } from "zod";
import { readDateParam, readOpaqueCursor } from "./collection-query";

export type HistoricalSearch = Record<string, string | string[] | undefined>;
export const returnMethods = ["twr", "mwr", "modified_dietz"] as const;
export const historicalFrequencies = ["daily", "monthly"] as const;
export const historicalViews = [
  "summary",
  "benchmark",
  "series",
  "rolling",
  "calendar",
  "attribution",
] as const;
export const incomeViews = ["income", "cash_flows"] as const;
export const historicalGroupings = [
  "holding",
  "group",
  "sector",
  "asset_class",
  "currency",
] as const;
export const flowKinds = [
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
] as const;

const querySchema = z.strictObject({
  account: z.string().uuid().optional(),
  start: z.string(),
  end: z.string(),
  cutoff: z.string(),
  currency: z.string().regex(/^[A-Z]{3}$/u),
  method: z.enum(returnMethods),
  frequency: z.enum(historicalFrequencies),
  knowledge: z.enum(["as_of_cutoff", "point_in_time"]),
  coverage: z.enum(["require_complete", "allow_degraded"]),
  view: z.enum([...historicalViews, ...incomeViews]),
  rolling: z.enum([
    "none",
    "calendar_days_30",
    "calendar_days_90",
    "calendar_days_365",
  ]),
  calendar: z.enum(["none", "month", "quarter", "year"]),
  grouping: z.enum(historicalGroupings),
  kind: z.enum(flowKinds),
  benchmark: z.string().uuid().optional(),
  target: z.string().uuid().optional(),
  grouping_policy: z
    .enum(["historical_assignment", "explicit_comparison"])
    .optional(),
  capture: z.string().uuid().optional(),
  cursor: z.string().nullable(),
  benchmarks_cursor: z.string().nullable(),
  top: z.number().int().min(1).max(50),
  limit: z.number().int().min(1).max(100),
  flows: z.enum(["show", "hide"]),
});

export type HistoricalQuery = z.infer<typeof querySchema>;

export class HistoricalQueryError extends Error {
  constructor() {
    super(
      "The historical filters are invalid. Use one value per field, a valid UTC cutoff and a period of at most 3,661 dates.",
    );
    this.name = "HistoricalQueryError";
  }
}

/** URL validation only. Financial values and returns come from the typed API. */
export function readHistoricalQuery(
  search: HistoricalSearch,
  options: {
    now: Date;
    currency: string;
    pathname: "/performance" | "/income";
  },
): HistoricalQuery {
  try {
    const values: Record<string, string | undefined> = {};
    const allowed = new Set(Object.keys(querySchema.shape));
    for (const [key, value] of Object.entries(search)) {
      if (!allowed.has(key) || Array.isArray(value))
        throw new HistoricalQueryError();
      if (value && value.length > 2048) throw new HistoricalQueryError();
      values[key] = value || undefined;
    }
    const previousYear = options.now.getUTCFullYear() - 1;
    const start = readDateParam(values.start) ?? `${previousYear}-01-01`;
    const end = readDateParam(values.end) ?? `${previousYear}-12-31`;
    const startAt = new Date(`${start}T00:00:00Z`).valueOf();
    const endAt = new Date(`${end}T00:00:00Z`).valueOf();
    if (endAt < startAt || endAt - startAt > 3660 * 86_400_000)
      throw new HistoricalQueryError();
    const rawCutoff = values.cutoff ?? options.now.toISOString();
    // The form explicitly labels datetime-local input UTC; external URL offsets
    // remain supported and normalize to the same unambiguous instant.
    const cutoffText =
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?$/u.test(
        rawCutoff,
      )
        ? `${rawCutoff}Z`
        : rawCutoff;
    if (
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$/u.test(
        cutoffText,
      )
    )
      throw new HistoricalQueryError();
    const cutoff = new Date(cutoffText);
    const hour = Number(cutoffText.slice(11, 13));
    const minute = Number(cutoffText.slice(14, 16));
    const second =
      cutoffText[16] === ":" ? Number(cutoffText.slice(17, 19)) : 0;
    if (hour > 23 || minute > 59 || second > 59)
      throw new HistoricalQueryError();
    readDateParam(cutoffText.slice(0, 10));
    const fraction = /\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/u.exec(cutoffText)?.[1];
    if (
      !Number.isFinite(cutoff.valueOf()) ||
      cutoff > options.now ||
      endAt + 86_400_000 > options.now.valueOf()
    )
      throw new HistoricalQueryError();
    if (
      BigInt(cutoff.valueOf()) * 1000n +
        BigInt((fraction ?? "").padEnd(6, "0").slice(3)) >
      BigInt(options.now.valueOf()) * 1000n
    )
      throw new HistoricalQueryError();
    const normalizedCutoff = `${cutoff.toISOString().slice(0, 19)}${fraction ? `.${fraction}` : ""}Z`;
    for (const field of ["top", "limit"] as const) {
      if (values[field] && !/^\d+$/u.test(values[field]))
        throw new HistoricalQueryError();
    }
    const query = querySchema.parse({
      account: values.account,
      start,
      end,
      cutoff: normalizedCutoff,
      currency: values.currency ?? options.currency,
      method: values.method ?? "twr",
      frequency: values.frequency ?? "monthly",
      knowledge: values.knowledge ?? "as_of_cutoff",
      coverage: values.coverage ?? "require_complete",
      view:
        values.view ?? (options.pathname === "/income" ? "income" : "summary"),
      rolling: values.rolling ?? "none",
      calendar: values.calendar ?? "none",
      grouping: values.grouping ?? "holding",
      kind: values.kind ?? "all",
      benchmark: values.benchmark,
      target: values.target,
      grouping_policy: values.grouping_policy,
      capture: values.capture,
      cursor: readOpaqueCursor(values.cursor),
      benchmarks_cursor: readOpaqueCursor(values.benchmarks_cursor),
      top: values.top ? Number(values.top) : 25,
      limit: values.limit ? Number(values.limit) : 25,
      flows: values.flows ?? "show",
    });
    if (
      options.pathname === "/income"
        ? !incomeViews.some((view) => view === query.view)
        : !historicalViews.some((view) => view === query.view)
    )
      throw new HistoricalQueryError();
    if (query.grouping_policy && !query.target)
      throw new HistoricalQueryError();
    if (
      options.pathname === "/income" &&
      query.grouping !== "holding" &&
      query.grouping !== "group"
    )
      throw new HistoricalQueryError();
    if (query.view === "attribution" && query.method === "mwr")
      throw new HistoricalQueryError();
    return query;
  } catch {
    throw new HistoricalQueryError();
  }
}

export function historicalHref(
  pathname: "/performance" | "/income",
  query: HistoricalQuery,
  changes: Partial<HistoricalQuery> = {},
): string {
  const values = { ...query, ...changes };
  const changed = Object.keys(changes);
  if (
    changed.some((key) => key === "limit" || key === "top") &&
    !("cursor" in changes)
  )
    values.cursor = null;
  if (
    changed.some(
      (key) =>
        ![
          "cursor",
          "benchmarks_cursor",
          "top",
          "limit",
          "capture",
          "flows",
        ].includes(key),
    )
  ) {
    if (!("capture" in changes)) values.capture = undefined;
    if (!("cursor" in changes)) values.cursor = null;
  }
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== "")
      parameters.set(key, String(value));
  }
  return `${pathname}?${parameters.toString()}`;
}
