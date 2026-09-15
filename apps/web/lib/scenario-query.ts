import { z } from "zod";
import type { HistoricalSearch } from "./historical-query";
import { readDateParam } from "./collection-query";

const ids = [
  "account",
  "definition",
  "version",
  "run",
  "before",
  "after",
  "snapshot",
  "xray",
  "capture",
] as const;
export const scenarioCursors = [
  "definitions_cursor",
  "versions_cursor",
  "runs_cursor",
  "snapshots_cursor",
  "component_cursor",
] as const;
const views = z.enum(["runs", "definitions", "new", "result", "compare"]);
const accepted = new Set<string>([
  ...ids,
  ...scenarioCursors,
  "view",
  "currency",
  "cutoff",
  "replay",
  "start_date",
  "end_date",
  "market_cutoff",
  "holdings",
  "knowledge",
]);
export type ScenarioQuery = Partial<Record<(typeof ids)[number], string>> &
  Record<(typeof scenarioCursors)[number], string | null> & {
    view: z.infer<typeof views>;
    currency: string;
    cutoff: string;
    replay: "none" | "historical";
    start_date: string;
    end_date: string;
    market_cutoff: string;
    holdings: "current_holdings" | "historical_holdings";
    knowledge: "point_in_time" | "retrospective";
  };

export class ScenarioQueryError extends Error {
  constructor() {
    super(
      "Use one value per field, valid saved identities and an explicit bounded replay window.",
    );
    this.name = "ScenarioQueryError";
  }
}

function instant(value: string) {
  // Preserve sub-millisecond digits: saved cutoffs are exact pins, not JS dates.
  const local = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)
    ? `${value}:00`
    : value;
  const text = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$/.test(local)
    ? `${local}Z`
    : local;
  if (
    !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(
      text,
    ) ||
    Number.isNaN(Date.parse(text))
  )
    throw new ScenarioQueryError();
  readDateParam(text.slice(0, 10));
  return text;
}

export function readScenarioQuery(
  search: HistoricalSearch,
  options: { now: Date; currency: string },
): ScenarioQuery {
  try {
    const values: Record<string, string | undefined> = {};
    for (const [name, value] of Object.entries(search)) {
      if (
        !accepted.has(name) ||
        Array.isArray(value) ||
        (value?.length ?? 0) > 2048
      )
        throw new ScenarioQueryError();
      values[name] = value || undefined;
    }
    const year = options.now.getUTCFullYear() - 1;
    const result: ScenarioQuery = {
      view: views.parse(values.view ?? (values.run ? "result" : "runs")),
      currency: z
        .string()
        .regex(/^[A-Z]{3}$/)
        .parse(values.currency ?? options.currency),
      cutoff: instant(values.cutoff ?? options.now.toISOString()),
      replay: z.enum(["none", "historical"]).parse(values.replay ?? "none"),
      start_date: readDateParam(values.start_date) ?? `${year}-01-01`,
      end_date: readDateParam(values.end_date) ?? `${year}-12-31`,
      market_cutoff: instant(
        values.market_cutoff ?? values.cutoff ?? options.now.toISOString(),
      ),
      holdings: z
        .enum(["current_holdings", "historical_holdings"])
        .parse(values.holdings ?? "current_holdings"),
      knowledge: z
        .enum(["point_in_time", "retrospective"])
        .parse(values.knowledge ?? "point_in_time"),
      definitions_cursor: null,
      versions_cursor: null,
      runs_cursor: null,
      snapshots_cursor: null,
      component_cursor: null,
    };
    for (const name of ids)
      if (values[name]) result[name] = z.string().uuid().parse(values[name]);
    for (const name of scenarioCursors)
      result[name] = values[name]
        ? z
            .string()
            .min(1)
            .max(2048)
            .regex(/^[A-Za-z0-9_-]+$/)
            .parse(values[name])
        : null;
    const days =
      (Date.parse(result.end_date) - Date.parse(result.start_date)) /
      86_400_000;
    if (
      days <= 0 ||
      days > 3660 ||
      (result.view === "result" && !result.run) ||
      (result.before && result.before === result.after)
    )
      throw new ScenarioQueryError();
    return result;
  } catch {
    throw new ScenarioQueryError();
  }
}

export function scenarioHref(
  query: ScenarioQuery,
  changes: Partial<Record<keyof ScenarioQuery, string | null>> = {},
): string {
  const parameters = new URLSearchParams();
  for (const [name, value] of Object.entries({ ...query, ...changes }))
    if (value !== undefined && value !== null && value !== "")
      parameters.set(name, value);
  return `/scenarios?${parameters}`;
}
