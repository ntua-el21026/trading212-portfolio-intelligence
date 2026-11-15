/** Reduce private in-memory navigation values to a fixed, value-free schema. */
export type NavigationFlags = Readonly<{
  sameOrigin: boolean;
  routeMatches: boolean;
  cursorPresent: boolean;
  cursorSyntaxValid: boolean;
  selectionMatchesExpected: boolean;
  cursorMatchesExpectedNext: boolean;
}>;

const selection = [
  "account",
  "view",
  "xray",
  "cutoff",
  "entity",
  "event_kind",
  "review_state",
] as const;

function selectionValue(url: URL, key: (typeof selection)[number]) {
  const value = url.searchParams.get(key) ?? "";
  if (key === "view") return value || "summary";
  if (key === "event_kind" || key === "review_state") return value || "all";
  if (key === "cutoff")
    // Normalize UTC spelling only; retain every nonzero fractional digit.
    return value
      .replace(/\+00:00$/, "Z")
      .replace(/\.([0-9]*?)0+Z$/, ".$1Z")
      .replace(/\.Z$/, "Z");
  return value;
}

export function navigationFlags(
  raw: string,
  expectedSelection: string,
  expectedNext: string | null,
): NavigationFlags {
  const denied: NavigationFlags = {
    sameOrigin: false,
    routeMatches: false,
    cursorPresent: false,
    cursorSyntaxValid: false,
    selectionMatchesExpected: false,
    cursorMatchesExpectedNext: false,
  };
  try {
    const expected = new URL(expectedSelection);
    const actual = new URL(raw, expected);
    const next = expectedNext ? new URL(expectedNext, expected) : null;
    const cursor = actual.searchParams.get("cursor");
    return {
      sameOrigin: actual.origin === expected.origin,
      routeMatches: actual.pathname === expected.pathname,
      cursorPresent: cursor !== null && cursor !== "",
      cursorSyntaxValid:
        cursor !== null && /^[A-Za-z0-9_-]{1,2048}$/.test(cursor),
      selectionMatchesExpected:
        actual.origin === expected.origin &&
        actual.pathname === expected.pathname &&
        selection.every(
          (key) =>
            selectionValue(actual, key) === selectionValue(expected, key),
        ),
      cursorMatchesExpectedNext:
        cursor !== null &&
        next !== null &&
        actual.origin === next.origin &&
        actual.pathname === next.pathname &&
        cursor === next.searchParams.get("cursor"),
    };
  } catch {
    return denied;
  }
}
