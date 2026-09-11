import { z } from "zod";
import { readOpaqueCursor, type SearchParamValue } from "./collection-query";

export const intelligenceKinds = [
  "valuation",
  "actual_vs_target",
  "drift",
  "performance",
  "benchmark",
  "income",
  "attribution",
  "cash_flow",
  "xray",
] as const;
export type IntelligenceKind = (typeof intelligenceKinds)[number];
type QualitySearch = Readonly<Record<string, SearchParamValue>>;
const kindSchema = z.enum(intelligenceKinds).default("valuation");
const limitSchema = z
  .string()
  .regex(/^(?:[1-9]|[1-9][0-9]|100)$/)
  .optional();
const legacyStateSchema = z
  .enum(["default", "empty", "stale", "partial", "unreconciled", "error"])
  .optional();

export interface IntelligenceQualityQuery {
  analytics_kind: IntelligenceKind;
  cursor: string | null;
  limit: number;
}

export interface IntelligenceQualityFields {
  analytics_kind?: IntelligenceKind;
  sources_limit?: string;
  sources_cursor?: string;
}

export interface LegacyQualityFields {
  state?: z.infer<typeof legacyStateSchema>;
  cursor?: string;
}

function cursorSelection(value: SearchParamValue) {
  try {
    if (Array.isArray(value)) throw new Error("Use one cursor.");
    return { valid: true as const, value: readOpaqueCursor(value) };
  } catch {
    return { valid: false as const, value: null };
  }
}

/** Each panel validates independently; only recognized valid fields enter links. */
export function readQualityNavigation(search: QualitySearch) {
  const kind = kindSchema.safeParse(search.analytics_kind);
  const limit = limitSchema.safeParse(search.sources_limit);
  const sourceCursor = cursorSelection(search.sources_cursor);
  const state = legacyStateSchema.safeParse(search.state);
  const legacyCursor = cursorSelection(search.cursor);
  const intelligenceFields: IntelligenceQualityFields = {
    ...(kind.success && search.analytics_kind !== undefined
      ? { analytics_kind: kind.data }
      : {}),
    ...(limit.success && limit.data !== undefined
      ? { sources_limit: limit.data }
      : {}),
    // A cursor cannot survive an invalid kind that no longer identifies its binding.
    ...(kind.success && sourceCursor.valid && sourceCursor.value
      ? { sources_cursor: sourceCursor.value }
      : {}),
  };
  const legacyFields: LegacyQualityFields = {
    ...(state.success && state.data !== undefined ? { state: state.data } : {}),
    ...(state.success && legacyCursor.valid && legacyCursor.value
      ? { cursor: legacyCursor.value }
      : {}),
  };
  const intelligenceQuery: IntelligenceQualityQuery | null =
    kind.success && limit.success && sourceCursor.valid
      ? {
          analytics_kind: kind.data,
          limit: limit.data ? Number(limit.data) : 25,
          cursor: sourceCursor.value,
        }
      : null;
  const legacyQuery =
    state.success && legacyCursor.valid
      ? { state: state.data, cursor: legacyCursor.value }
      : null;
  return {
    intelligence: { query: intelligenceQuery, fields: intelligenceFields },
    legacy: { query: legacyQuery, fields: legacyFields },
  };
}

export function readIntelligenceQualityQuery(
  search: QualitySearch,
): IntelligenceQualityQuery {
  const query = readQualityNavigation(search).intelligence.query;
  if (!query)
    throw new Error("Use valid single values for intelligence filters.");
  return query;
}

export function intelligenceQualityHref(
  accountId: string,
  query: IntelligenceQualityQuery,
  cursor: string | null,
  legacy: LegacyQualityFields = {},
): string {
  const values = new URLSearchParams({
    account: accountId,
    analytics_kind: query.analytics_kind,
    sources_limit: String(query.limit),
  });
  if (cursor) values.set("sources_cursor", cursor);
  if (legacy.state !== undefined) values.set("state", legacy.state);
  if (legacy.cursor) values.set("cursor", legacy.cursor);
  return `/quality?${values}`;
}
