import { z } from "zod";
import type { HistoricalSearch } from "./historical-query";

export const researchCursors = [
  "cursor",
  "notes_cursor",
  "versions_cursor",
] as const;
const schema = z.strictObject({
  account: z.string().uuid().optional(),
  view: z.enum(["summary", "notes", "item"]),
  xray: z.string().uuid().optional(),
  item: z.string().uuid().optional(),
  note: z.string().uuid().optional(),
  entity: z.string().uuid().optional(),
  cutoff: z
    .string()
    .datetime({ offset: true })
    .regex(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/,
    ),
  event_kind: z.enum(["all", "news", "company_overview"]),
  review_state: z.enum(["all", "reviewed", "unreviewed"]),
  cursor: z
    .string()
    .min(1)
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/)
    .nullable(),
  notes_cursor: z
    .string()
    .min(1)
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/)
    .nullable(),
  versions_cursor: z
    .string()
    .min(1)
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/)
    .nullable(),
});
export type ResearchQuery = z.infer<typeof schema>;
export class ResearchQueryError extends Error {
  constructor() {
    super(
      "Use one value per field, a saved X-ray identity and an exact ISO source cutoff.",
    );
    this.name = "ResearchQueryError";
  }
}
export function readResearchQuery(
  search: HistoricalSearch,
  now: Date,
): ResearchQuery {
  try {
    const values: Record<string, string | undefined> = {};
    for (const [key, value] of Object.entries(search)) {
      if (
        !Object.hasOwn(schema.shape, key) ||
        Array.isArray(value) ||
        (value?.length ?? 0) > 2048
      )
        throw new ResearchQueryError();
      values[key] = value || undefined;
    }
    const query = schema.parse({
      ...values,
      view: values.view ?? (values.item ? "item" : "summary"),
      cutoff: values.cutoff ?? now.toISOString(),
      event_kind: values.event_kind ?? "all",
      review_state: values.review_state ?? "all",
      cursor: values.cursor ?? null,
      notes_cursor: values.notes_cursor ?? null,
      versions_cursor: values.versions_cursor ?? null,
    });
    if (
      (query.view === "item" && !query.item) ||
      (query.cursor && !query.xray) ||
      (query.versions_cursor && !query.note)
    )
      throw new ResearchQueryError();
    return query;
  } catch {
    throw new ResearchQueryError();
  }
}
export function researchHref(
  query: ResearchQuery,
  changes: Partial<{
    [K in keyof ResearchQuery]: ResearchQuery[K] | null;
  }> = {},
): string {
  const next = { ...query, ...changes };
  // A filter or selected identity starts new immutable collections.
  if (
    [
      "xray",
      "cutoff",
      "entity",
      "event_kind",
      "review_state",
      "view",
      "item",
      "note",
    ].some(
      (key) =>
        Object.hasOwn(changes, key) &&
        changes[key as keyof ResearchQuery] !==
          query[key as keyof ResearchQuery],
    )
  )
    for (const cursor of researchCursors) next[cursor] = null;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(next))
    if (value !== null && value !== undefined && value !== "")
      params.set(key, value);
  return `/research?${params}`;
}
