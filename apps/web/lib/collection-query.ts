const MAX_CURSOR_LENGTH = 2048;
const MAX_SEARCH_LENGTH = 80;

export type SearchParamValue = string | string[] | undefined;

export function firstSearchParam(value: SearchParamValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function readOpaqueCursor(value: SearchParamValue): string | null {
  const cursor = firstSearchParam(value);
  if (!cursor) return null;
  if (cursor.trim() !== cursor) {
    throw new Error("The collection cursor is invalid.");
  }
  const hasControlCharacter = Array.from(cursor).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 31 || codePoint === 127;
  });
  if (cursor.length > MAX_CURSOR_LENGTH || hasControlCharacter) {
    throw new Error("The collection cursor is invalid.");
  }
  return cursor;
}

export function readBoundedSearch(value: SearchParamValue): string | undefined {
  const search = firstSearchParam(value)?.trim().replace(/\s+/gu, " ");
  if (!search) return undefined;
  if (search.length > MAX_SEARCH_LENGTH) {
    throw new Error("The collection search is too long.");
  }
  return search;
}

export function readDateParam(value: SearchParamValue): string | undefined {
  const candidate = firstSearchParam(value)?.trim();
  if (!candidate) return undefined;
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(candidate)) {
    throw new Error("The collection date filter is invalid.");
  }
  const parsed = new Date(`${candidate}T00:00:00Z`);
  if (
    Number.isNaN(parsed.valueOf()) ||
    parsed.toISOString().slice(0, 10) !== candidate
  ) {
    throw new Error("The collection date filter is invalid.");
  }
  return candidate;
}

export function validateDateRange(
  startDate: string | undefined,
  endDate: string | undefined,
): void {
  if (startDate && endDate && startDate > endDate) {
    throw new Error("The collection date range is invalid.");
  }
}

export function readEnumParam<const Value extends string>(
  value: SearchParamValue,
  allowed: ReadonlySet<Value>,
  fallback: Value,
): Value {
  const candidate = firstSearchParam(value);
  return candidate && allowed.has(candidate as Value)
    ? (candidate as Value)
    : fallback;
}
