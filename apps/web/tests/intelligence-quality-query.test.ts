import { describe, expect, it } from "vitest";
import {
  intelligenceKinds,
  intelligenceQualityHref,
  readIntelligenceQualityQuery,
  readQualityNavigation,
} from "../lib/intelligence-quality-query";
import { accountSwitchHref } from "../lib/account-selection";

describe("bounded intelligence quality URL state", () => {
  it("defaults to valuation with an explicit bounded source page", () => {
    expect(readIntelligenceQualityQuery({})).toEqual({
      analytics_kind: "valuation",
      cursor: null,
      limit: 25,
    });
  });
  it.each(intelligenceKinds)("accepts the fixed %s family", (kind) => {
    expect(
      readIntelligenceQualityQuery({
        analytics_kind: kind,
        sources_limit: "100",
      }),
    ).toEqual({
      analytics_kind: kind,
      cursor: null,
      limit: 100,
    });
  });
  it.each([
    { analytics_kind: "any-provider-operation" },
    { analytics_kind: ["valuation", "xray"] },
    { sources_limit: "0" },
    { sources_limit: "101" },
    { sources_limit: "1.5" },
    { sources_limit: "01" },
    { sources_limit: ["25"] },
    { sources_cursor: ["abc", "def"] },
    { sources_cursor: "a".repeat(2049) },
  ])("rejects ambiguous or unbounded state", (query) => {
    expect(() => readIntelligenceQualityQuery(query)).toThrow();
  });
  it("preserves account, kind and limit while replacing only the source cursor", () => {
    const account = "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1";
    const query = {
      analytics_kind: "xray" as const,
      cursor: "previous",
      limit: 10,
    };
    const next = new URL(
      intelligenceQualityHref(account, query, "next_cursor"),
      "http://localhost",
    );
    expect(Object.fromEntries(next.searchParams)).toEqual({
      account,
      analytics_kind: "xray",
      sources_limit: "10",
      sources_cursor: "next_cursor",
    });
    expect(
      new URL(
        intelligenceQualityHref(account, query, null),
        "http://localhost",
      ).searchParams.has("sources_cursor"),
    ).toBe(false);
  });
});

describe("independent quality panel state", () => {
  const account = "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1";
  const both = {
    analytics_kind: "performance",
    sources_limit: "50",
    sources_cursor: "source-old",
    state: "partial",
    cursor: "legacy-old",
    unknown: "private-unknown-canary",
  };

  it("preserves the valid companion while changing the source cursor", () => {
    const navigation = readQualityNavigation(both);
    const next = new URL(
      intelligenceQualityHref(
        account,
        navigation.intelligence.query!,
        "source-next",
        navigation.legacy.fields,
      ),
      "http://localhost",
    );
    expect(Object.fromEntries(next.searchParams)).toEqual({
      account,
      analytics_kind: "performance",
      sources_limit: "50",
      sources_cursor: "source-next",
      state: "partial",
      cursor: "legacy-old",
    });
    const first = new URL(
      intelligenceQualityHref(
        account,
        navigation.intelligence.query!,
        null,
        navigation.legacy.fields,
      ),
      "http://localhost",
    );
    expect(first.searchParams.get("cursor")).toBe("legacy-old");
    expect(first.searchParams.has("sources_cursor")).toBe(false);
    expect(next.href).not.toContain("private-unknown-canary");
  });

  it.each([
    { cursor: ["legacy-old"] },
    { cursor: "x".repeat(2049) },
    { cursor: "space " },
    { cursor: "control\u0001character" },
    { state: ["partial", "stale"] },
    { state: "private-invalid-state" },
  ])(
    "rejects invalid legacy fields without rejecting intelligence",
    (invalid) => {
      const navigation = readQualityNavigation({ ...both, ...invalid });
      expect(navigation.legacy.query).toBeNull();
      expect(navigation.intelligence.query).toEqual({
        analytics_kind: "performance",
        limit: 50,
        cursor: "source-old",
      });
      expect(readIntelligenceQualityQuery({ ...both, ...invalid })).toEqual(
        navigation.intelligence.query,
      );
      expect(JSON.stringify(navigation.legacy.fields)).not.toContain(
        "private-invalid-state",
      );
    },
  );

  it("keeps a valid legacy state while omitting only its malformed cursor", () => {
    const navigation = readQualityNavigation({
      ...both,
      cursor: ["bad", "other"],
    });
    expect(navigation.legacy.fields).toEqual({ state: "partial" });
  });

  it("drops a legacy cursor when its state basis is invalid", () => {
    const navigation = readQualityNavigation({
      ...both,
      state: "private-invalid-state",
    });
    expect(navigation.legacy.fields).toEqual({});
  });

  it("keeps valid intelligence kind and limit when only its cursor is invalid", () => {
    const navigation = readQualityNavigation({
      ...both,
      sources_cursor: ["bad", "other"],
    });
    expect(navigation.intelligence.query).toBeNull();
    expect(navigation.intelligence.fields).toEqual({
      analytics_kind: "performance",
      sources_limit: "50",
    });
    expect(navigation.legacy.query).toEqual({
      state: "partial",
      cursor: "legacy-old",
    });
  });

  it("cannot carry a source cursor across an invalid intelligence kind", () => {
    const navigation = readQualityNavigation({
      ...both,
      analytics_kind: "private-invalid-kind",
    });
    expect(navigation.intelligence.query).toBeNull();
    expect(navigation.intelligence.fields).toEqual({ sources_limit: "50" });
    expect(navigation.legacy.query).not.toBeNull();
  });

  it("retains valid kind and cursor when the page size alone needs resetting", () => {
    const navigation = readQualityNavigation({ ...both, sources_limit: "01" });
    expect(navigation.intelligence.query).toBeNull();
    expect(navigation.intelligence.fields).toEqual({
      analytics_kind: "performance",
      sources_cursor: "source-old",
    });
  });

  it("keeps both cursors bounded at the existing 2048-character limit", () => {
    const cursor = "a".repeat(2048);
    const navigation = readQualityNavigation({
      cursor,
      sources_cursor: cursor,
    });
    expect(navigation.intelligence.query?.cursor).toBe(cursor);
    expect(navigation.legacy.query?.cursor).toBe(cursor);
  });

  it.each(["default", "empty", "stale", "partial", "unreconciled", "error"])(
    "preserves the recognized legacy %s state",
    (state) => {
      expect(readQualityNavigation({ state }).legacy.fields).toEqual({ state });
    },
  );

  it("clears both dependent cursors on the existing account-switch path", () => {
    const other = "f791a374-cc3e-4e73-9168-a120c0d54cec";
    const switched = new URL(
      accountSwitchHref(
        "/quality",
        new URLSearchParams({ account, ...both }),
        other,
      ),
      "http://localhost",
    );
    expect(Object.fromEntries(switched.searchParams)).toEqual({
      account: other,
    });
  });
});
