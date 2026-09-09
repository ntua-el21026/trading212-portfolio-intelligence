import { z } from "zod";

export type XraySearch = Record<string, string | string[] | undefined>;
export const xrayDimensions = [
  "company",
  "sector",
  "industry",
  "country",
  "region",
  "currency",
] as const;
export const xrayViews = [
  "exposures",
  "paths",
  "held_funds",
  "pairs",
  "common_entities",
] as const;
const uuid = z
  .string()
  .uuid()
  .transform((value) => value.toLowerCase());
const schema = z.strictObject({
  account: uuid.optional(),
  snapshot: uuid.optional(),
  cutoff: z.iso.datetime({ offset: true, precision: undefined }),
  currency: z.string().regex(/^[A-Z]{3}$/u),
  view: z.enum(xrayViews),
  dimension: z.enum(xrayDimensions),
  normalized: z.boolean(),
  fund_ids: z.array(uuid).max(32),
  left: uuid.optional(),
  right: uuid.optional(),
  exposure: uuid.optional(),
  run: uuid.optional(),
  cursor: z
    .string()
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/u)
    .optional(),
  limit: z.number().int().min(1).max(100),
});
export type XrayQuery = z.infer<typeof schema>;
export class XrayQueryError extends Error {
  constructor() {
    super(
      "Use valid X-ray selectors, a UTC source cutoff, and at most 32 distinct funds.",
    );
    this.name = "XrayQueryError";
  }
}

export function readXrayQuery(
  search: XraySearch,
  defaults: { now: Date; currency: string; snapshot?: string },
): XrayQuery {
  try {
    const values: Record<string, string | undefined> = {};
    const funds: string[] = [];
    for (const [key, value] of Object.entries(search)) {
      if (!Object.hasOwn(schema.shape, key)) throw new XrayQueryError();
      if (key === "fund_ids") {
        if (value) funds.push(...(Array.isArray(value) ? value : [value]));
      } else {
        if (Array.isArray(value) || (value && value.length > 2048))
          throw new XrayQueryError();
        values[key] = value || undefined;
      }
    }
    if (values.limit && !/^[1-9][0-9]{0,2}$/u.test(values.limit))
      throw new XrayQueryError();
    if (values.normalized && !["true", "false"].includes(values.normalized))
      throw new XrayQueryError();
    const cutoff = values.cutoff ?? defaults.now.toISOString();
    if (
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(
        cutoff,
      )
    )
      throw new XrayQueryError();
    const query = schema.parse({
      account: values.account,
      snapshot: values.snapshot ?? defaults.snapshot,
      cutoff,
      currency: values.currency ?? defaults.currency,
      view: values.view ?? "exposures",
      dimension: values.dimension ?? "company",
      normalized: values.normalized === "true",
      fund_ids: funds,
      left: values.left,
      right: values.right,
      exposure: values.exposure,
      run: values.run,
      cursor: values.cursor,
      limit: values.limit ? Number(values.limit) : 25,
    });
    if (new Set(query.fund_ids).size !== query.fund_ids.length)
      throw new XrayQueryError();
    if (
      ["paths", "common_entities"].includes(query.view) &&
      !query.run &&
      !query.cursor
    )
      throw new XrayQueryError();
    if (query.exposure && query.view !== "paths") throw new XrayQueryError();
    if (query.view === "pairs" || query.view === "common_entities") {
      if (query.fund_ids.length < 2) throw new XrayQueryError();
    }
    if (
      query.view === "common_entities" &&
      (!query.left ||
        !query.right ||
        query.left === query.right ||
        !query.fund_ids.includes(query.left) ||
        !query.fund_ids.includes(query.right))
    )
      throw new XrayQueryError();
    return query;
  } catch {
    throw new XrayQueryError();
  }
}

export function xrayHref(
  query: XrayQuery,
  changes: Partial<XrayQuery> = {},
): string {
  const next = { ...query, ...changes };
  const changed = Object.keys(changes);
  if (
    changed.some((key) =>
      ["account", "snapshot", "cutoff", "currency"].includes(key),
    ) &&
    !("run" in changes)
  )
    next.run = undefined;
  if (
    changed.some((key) => key !== "run" && key !== "cursor") &&
    !("cursor" in changes)
  )
    next.cursor = undefined;
  if (changes.view && changes.view !== "paths") next.exposure = undefined;
  if (changes.view && changes.view !== "common_entities") {
    next.left = undefined;
    next.right = undefined;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(next)) {
    if (Array.isArray(value)) {
      for (const id of value) params.append(key, id);
    } else if (value !== undefined) params.set(key, String(value));
  }
  return `/xray?${params.toString()}`;
}

export function xrayRunQuery(query: XrayQuery) {
  if (!query.snapshot) throw new XrayQueryError();
  return {
    snapshot_id: query.snapshot,
    source_cutoff_at: query.cutoff,
    reporting_currency: query.currency,
    run_id: query.run,
    cursor: query.cursor,
    limit: query.limit,
  };
}
