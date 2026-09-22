import { z } from "zod";
import type { OwnerLayoutWidget } from "@trading212/api-contracts";
import type { HistoricalSearch } from "./historical-query";

type LayoutSelection = NonNullable<OwnerLayoutWidget["selection"]>;

const schema = z.strictObject({
  account: z.string().uuid().optional(),
  layout: z.string().uuid().optional(),
  version: z.string().uuid().optional(),
  mode: z.enum(["list", "edit", "view"]).default("list"),
  cursor: z
    .string()
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/)
    .optional(),
  archived: z.enum(["true", "false"]).default("false"),
});
export type OwnerLayoutQuery = z.infer<typeof schema>;
export function readOwnerLayoutQuery(
  search: HistoricalSearch,
): OwnerLayoutQuery {
  const value = schema.parse(search);
  if (
    (value.version && !value.layout) ||
    (value.mode === "view" && !value.layout) ||
    (value.cursor && value.mode !== "list")
  )
    throw new Error(
      "Use one saved layout and one immutable version at a time.",
    );
  return value;
}
export function ownerLayoutHref(query: Partial<OwnerLayoutQuery>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query))
    if (value !== undefined) params.set(key, value);
  return `/settings/layouts${params.size ? `?${params}` : ""}`;
}

export const layoutRoutes = [
  "overview",
  "holdings",
  "allocation",
  "activity",
  "dividends",
  "snapshots",
  "synchronization",
  "quality",
  "pies",
  "drift",
  "planner",
  "sources",
  "performance",
  "risk",
  "scenarios",
  "projections",
  "research",
  "income",
  "xray",
  "reports",
  "alerts",
  "settings",
] as const;
const workspacePaths = Object.fromEntries(
  layoutRoutes.map((route) => [
    route,
    route === "overview" ? "/" : `/${route}`,
  ]),
);

/** Every destination is a fixed owned workspace; no caller URL or arbitrary query. */
export function savedLayoutSelectionHref(
  selection: LayoutSelection,
  account: string | null | undefined,
): string {
  const params = new URLSearchParams();
  if (account) params.set("account", z.string().uuid().parse(account));
  let path: string;
  if (selection.kind === "workspace") {
    path = workspacePaths[selection.route];
    if (!path) throw new Error("Unknown saved workspace.");
    if (selection.pane) params.set("view", selection.pane);
  } else {
    if (!account) throw new Error("The saved view requires its exact account.");
    if (selection.kind === "saved_run") {
      const destinations = {
        risk: "/risk",
        scenario: "/scenarios",
        projection: "/projections",
        xray: "/xray",
      };
      path = destinations[selection.family];
      params.set("run", selection.run_id);
      params.set(
        "view",
        selection.family === "xray"
          ? "exposures"
          : (selection.pane ?? "result"),
      );
      if (selection.family === "xray") {
        if (
          !selection.snapshot_id ||
          !selection.source_cutoff_at ||
          !selection.reporting_currency
        )
          throw new Error("The original X-ray context is required.");
        params.set("snapshot", selection.snapshot_id);
        params.set("cutoff", selection.source_cutoff_at);
        params.set("currency", selection.reporting_currency);
      }
    } else if (selection.kind === "research") {
      path = "/research";
      params.set("view", "summary");
      params.set("xray", selection.xray_run_id);
      params.set("cutoff", selection.source_cutoff_at);
      params.set("review_state", selection.review_state ?? "all");
      params.set("event_kind", selection.event_kind ?? "all");
      if (selection.entity_id) params.set("entity", selection.entity_id);
    } else {
      path = `/${selection.route}`;
      const fields = {
        start: selection.start_date,
        end: selection.end_date,
        cutoff: selection.source_cutoff_at,
        currency: selection.reporting_currency,
        method: selection.method,
        frequency: selection.frequency,
        knowledge: selection.knowledge,
        coverage: selection.coverage,
        view: selection.view,
        grouping: selection.grouping,
        kind: selection.flow_kind,
        rolling: selection.rolling,
        calendar: selection.calendar,
      };
      for (const [key, value] of Object.entries(fields))
        if (value !== undefined) params.set(key, value);
      if (selection.capture_id) params.set("capture", selection.capture_id);
    }
  }
  return `${path}${params.size ? `?${params}` : ""}`;
}
