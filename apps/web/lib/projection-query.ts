import { z } from "zod";
import type { HistoricalSearch } from "./historical-query";
const ids = [
  "account",
  "set",
  "version",
  "goal",
  "goal_version",
  "run",
  "snapshot",
] as const;
export const projectionCursors = [
  "sets_cursor",
  "versions_cursor",
  "goals_cursor",
  "goal_versions_cursor",
  "runs_cursor",
  "snapshots_cursor",
  "point_cursor",
] as const;
const views = z.enum(["runs", "assumptions", "goals", "new", "result", "goal"]);
const accepted = new Set<string>([...ids, ...projectionCursors, "view"]);
export type ProjectionQuery = Partial<Record<(typeof ids)[number], string>> &
  Record<(typeof projectionCursors)[number], string | null> & {
    view: z.infer<typeof views>;
  };
export class ProjectionQueryError extends Error {
  constructor() {
    super("Use one value per field and valid saved projection identities.");
    this.name = "ProjectionQueryError";
  }
}
export function readProjectionQuery(search: HistoricalSearch): ProjectionQuery {
  try {
    const values: Record<string, string | undefined> = {};
    for (const [key, value] of Object.entries(search)) {
      if (
        !accepted.has(key) ||
        Array.isArray(value) ||
        (value?.length ?? 0) > 2048
      )
        throw new ProjectionQueryError();
      values[key] = value || undefined;
    }
    const query: ProjectionQuery = {
      view: views.parse(values.view ?? (values.run ? "result" : "runs")),
      sets_cursor: null,
      versions_cursor: null,
      goals_cursor: null,
      goal_versions_cursor: null,
      runs_cursor: null,
      snapshots_cursor: null,
      point_cursor: null,
    };
    for (const key of ids)
      if (values[key]) query[key] = z.string().uuid().parse(values[key]);
    for (const key of projectionCursors)
      query[key] = values[key]
        ? z
            .string()
            .max(2048)
            .regex(/^[A-Za-z0-9_-]+$/)
            .parse(values[key])
        : null;
    if (
      (query.view === "result" ||
        query.view === "goal" ||
        query.point_cursor) &&
      !query.run
    )
      throw new ProjectionQueryError();
    return query;
  } catch {
    throw new ProjectionQueryError();
  }
}
export function projectionHref(
  query: ProjectionQuery,
  changes: Partial<Record<keyof ProjectionQuery, string | null>> = {},
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...query, ...changes }))
    if (value !== undefined && value !== null && value !== "")
      params.set(key, value);
  return `/projections?${params}`;
}
/** Moving between saved inputs drops result/cursor state; back restores the exact prior URL. */
export function projectionSelectionHref(
  query: ProjectionQuery,
  changes: Partial<Record<keyof ProjectionQuery, string | null>>,
): string {
  return projectionHref(query, {
    run: null,
    point_cursor: null,
    versions_cursor: null,
    goal_versions_cursor: null,
    ...changes,
  });
}
