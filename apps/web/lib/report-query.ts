import { z } from "zod";

export const REPORT_TYPES = [
  "monthly",
  "quarterly",
  "annual",
  "portfolio_summary",
  "target_drift",
  "contribution_plan",
  "performance_benchmark",
  "dividend_income",
  "portfolio_xray",
  "quality_reconciliation",
] as const;
export const REPORT_SECTIONS = [
  "overview",
  "allocation",
  "targets",
  "drift",
  "contribution_plan",
  "performance",
  "benchmark",
  "income",
  "cash_flows",
  "attribution",
  "xray",
  "quality",
  "activity",
] as const;
export const EXPORT_DATASETS = [
  "positions",
  "activity",
  "dividends",
  "targets",
  "plans",
  "performance",
  "xray",
  "alerts",
] as const;
export const REPORT_STATES = [
  "all",
  "queued",
  "running",
  "succeeded",
  "failed",
  "expired",
  "cancelled",
] as const;
export const REQUIRED_SECTIONS: Readonly<
  Record<
    (typeof REPORT_TYPES)[number],
    readonly (typeof REPORT_SECTIONS)[number][]
  >
> = {
  monthly: [
    "overview",
    "allocation",
    "performance",
    "income",
    "cash_flows",
    "quality",
  ],
  quarterly: [
    "overview",
    "allocation",
    "performance",
    "income",
    "cash_flows",
    "quality",
  ],
  annual: [
    "overview",
    "allocation",
    "performance",
    "income",
    "cash_flows",
    "quality",
  ],
  portfolio_summary: ["overview", "allocation", "quality"],
  target_drift: ["overview", "targets", "drift", "quality"],
  contribution_plan: ["overview", "targets", "contribution_plan", "quality"],
  performance_benchmark: ["overview", "performance", "benchmark", "quality"],
  dividend_income: ["overview", "income", "cash_flows", "quality"],
  portfolio_xray: ["overview", "xray", "quality"],
  quality_reconciliation: ["overview", "quality", "activity"],
};

const uuid = z.string().uuid();
const schema = z.strictObject({
  account: uuid.optional(),
  snapshot: uuid.optional(),
  report: uuid.optional(),
  export: uuid.optional(),
  kind: z.enum(["report", "export"]).default("report"),
  report_type: z.enum(REPORT_TYPES).default("portfolio_summary"),
  dataset: z.enum(EXPORT_DATASETS).default("positions"),
  state: z.enum(REPORT_STATES).default("all"),
  history_type: z.enum(["all", ...REPORT_TYPES]).default("all"),
  history_dataset: z.enum(["all", ...EXPORT_DATASETS]).default("all"),
  cursor: z
    .string()
    .regex(/^[A-Za-z0-9_-]{1,2048}$/)
    .optional(),
  snapshots_cursor: z
    .string()
    .regex(/^[A-Za-z0-9_-]{1,2048}$/)
    .optional(),
  start_date: z.iso.date().optional(),
  end_date: z.iso.date().optional(),
  source_cutoff_at: z.string().max(40).optional(),
  reporting_currency: z
    .string()
    .regex(/^[A-Z]{3}$/)
    .optional(),
  target_version_id: uuid.optional(),
  plan_revision_id: uuid.optional(),
  benchmark_version_id: uuid.optional(),
  constituent_snapshot_id: uuid.optional(),
  xray_run_id: uuid.optional(),
  formats: z
    .string()
    .regex(/^(pdf|csv|json|xlsx)(,(pdf|csv|json|xlsx)){0,3}$/)
    .optional(),
  sections: z.string().max(240).optional(),
  field_set: z.enum(["standard", "audit"]).default("standard"),
  ttl_days: z
    .string()
    .regex(/^(?:[1-9]|[12][0-9]|30)$/)
    .default("7"),
  request_key: z
    .string()
    .regex(/^[A-Za-z0-9._:-]{1,180}$/)
    .optional(),
  request_digest: z
    .string()
    .regex(/^[a-f0-9]{64}$/)
    .optional(),
});

export type ReportQuery = z.infer<typeof schema>;
export type ReportSearch = Record<string, string | string[] | undefined>;

export function parseReportQuery(search: ReportSearch): ReportQuery {
  if (Object.values(search).some(Array.isArray))
    throw new Error("The report selection is invalid.");
  const parsed = schema.safeParse(search);
  if (!parsed.success) throw new Error("The report selection is invalid.");
  if (
    parsed.data.sections &&
    parsed.data.sections
      .split(",")
      .some(
        (section) => !(REPORT_SECTIONS as readonly string[]).includes(section),
      )
  )
    throw new Error("The report sections are invalid.");
  if (
    parsed.data.start_date &&
    parsed.data.end_date &&
    parsed.data.start_date > parsed.data.end_date
  )
    throw new Error("The report period is invalid.");
  return parsed.data;
}

const selectionFields = [
  "kind",
  "report_type",
  "dataset",
  "start_date",
  "end_date",
  "source_cutoff_at",
  "reporting_currency",
  "target_version_id",
  "plan_revision_id",
  "benchmark_version_id",
  "constituent_snapshot_id",
  "xray_run_id",
  "formats",
  "sections",
  "field_set",
  "ttl_days",
] as const;
const selectionDefaults: Partial<
  Record<(typeof selectionFields)[number], string>
> = {
  kind: "report",
  report_type: "portfolio_summary",
  dataset: "positions",
  field_set: "standard",
  ttl_days: "7",
};

// Local edits can temporarily contain incomplete values; validate only a restored URL.
export function reportSelectionSearchKey(
  search: Pick<URLSearchParams, "get">,
): string {
  return JSON.stringify(
    selectionFields.map(
      (field) => search.get(field) ?? selectionDefaults[field] ?? null,
    ),
  );
}

export function reportHref(
  values: Readonly<Record<string, string | null | undefined>>,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value) query.set(key, value);
  return query.size ? `/reports?${query}` : "/reports";
}
