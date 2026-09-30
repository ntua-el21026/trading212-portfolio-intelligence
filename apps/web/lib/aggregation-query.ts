import { z } from "zod";
import type { HistoricalSearch } from "./historical-query";
const schema = z.strictObject({
  account: z.string().uuid().optional(),
  view: z.enum(["selections", "new", "runs", "result"]).default("selections"),
  selection: z.string().uuid().optional(),
  run: z.string().uuid().optional(),
  table: z
    .enum(["holdings", "components", "accounts", "transfers"])
    .default("holdings"),
  cursor: z
    .string()
    .min(1)
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/)
    .optional(),
});
export type AggregationQuery = z.infer<typeof schema>;
export function readAggregationQuery(
  search: HistoricalSearch,
): AggregationQuery {
  const value = schema.parse(search);
  if (
    (value.view === "runs" && !value.selection) ||
    (value.view === "result" && (!value.selection || !value.run)) ||
    (value.view !== "result" && value.run) ||
    (value.view === "new" && (value.selection || value.cursor)) ||
    (value.view === "selections" && value.selection) ||
    (value.view !== "result" && value.table !== "holdings")
  )
    throw new Error("Choose one saved aggregate and its current page.");
  return value;
}
export function aggregationHref(query: Partial<AggregationQuery>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query))
    if (value !== undefined) params.set(key, value);
  return `/aggregation${params.size ? `?${params}` : ""}`;
}
