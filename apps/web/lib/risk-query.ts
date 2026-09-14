import { z } from "zod";
import { readHistoricalQuery, type HistoricalSearch } from "./historical-query";

const ids = [
  "account",
  "definition",
  "version",
  "run",
  "snapshot",
  "capture",
  "benchmark",
  "xray",
] as const;
const cursors = [
  "definitions_cursor",
  "versions_cursor",
  "runs_cursor",
  "sources_cursor",
  "snapshots_cursor",
  "benchmarks_cursor",
] as const;
const fields = new Set<string>([
  ...ids,
  ...cursors,
  "view",
  "start",
  "end",
  "cutoff",
  "currency",
  "coverage",
  "knowledge",
  "xray_mode",
]);
const uuid = z.string().uuid();
const view = z.enum(["runs", "definitions", "new", "result"]);
export type RiskQuery = Partial<Record<(typeof ids)[number], string>> &
  Record<(typeof cursors)[number], string | null> & {
    view: z.infer<typeof view>;
    xray_mode: "omit" | "capture";
    start: string;
    end: string;
    cutoff: string;
    currency: string;
    coverage: "require_complete" | "allow_degraded";
    knowledge: "as_of_cutoff" | "point_in_time";
  };

export class RiskQueryError extends Error {
  constructor() {
    super(
      "Use valid owned selections, one value per filter and an explicit bounded historical window.",
    );
    this.name = "RiskQueryError";
  }
}

export function readRiskQuery(
  search: HistoricalSearch,
  options: { now: Date; currency: string },
): RiskQuery {
  try {
    const values: Record<string, string | undefined> = {};
    for (const [key, value] of Object.entries(search)) {
      if (
        !fields.has(key) ||
        Array.isArray(value) ||
        (value?.length ?? 0) > 2048
      )
        throw new RiskQueryError();
      values[key] = value || undefined;
    }
    const common = readHistoricalQuery(
      {
        start: values.start,
        end: values.end,
        cutoff: values.cutoff,
        currency: values.currency,
        coverage: values.coverage,
        knowledge: values.knowledge,
      },
      { ...options, pathname: "/performance" },
    );
    const result: RiskQuery = {
      start: common.start,
      end: common.end,
      cutoff: common.cutoff,
      currency: common.currency,
      coverage: common.coverage,
      knowledge: common.knowledge,
      view: view.parse(values.view ?? (values.run ? "result" : "runs")),
      definitions_cursor: null,
      versions_cursor: null,
      runs_cursor: null,
      sources_cursor: null,
      snapshots_cursor: null,
      benchmarks_cursor: null,
      xray_mode: z.enum(["omit", "capture"]).parse(values.xray_mode ?? "omit"),
    };
    for (const name of ids)
      if (values[name] !== undefined) result[name] = uuid.parse(values[name]);
    for (const name of cursors)
      result[name] = values[name]
        ? z
            .string()
            .min(1)
            .max(2048)
            .regex(/^[A-Za-z0-9_-]+$/)
            .parse(values[name])
        : null;
    if (result.view === "result" && !result.run) throw new RiskQueryError();
    return result;
  } catch {
    throw new RiskQueryError();
  }
}

export function riskHref(
  query: RiskQuery,
  changes: Partial<Record<keyof RiskQuery, string | null>> = {},
): string {
  const values = { ...query, ...changes };
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== null && value !== "")
      params.set(key, value);
  return `/risk?${params}`;
}

export function riskWindow(query: RiskQuery) {
  return {
    start_date: query.start,
    end_date: query.end,
    source_cutoff_at: query.cutoff,
    reporting_currency: query.currency,
    coverage_policy: query.coverage,
    knowledge_policy: query.knowledge,
  };
}
