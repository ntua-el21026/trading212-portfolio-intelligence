import { describe, expect, it } from "vitest";

import {
  readBoundedSearch,
  readDateParam,
  readEnumParam,
  readOpaqueCursor,
  validateDateRange,
} from "../lib/collection-query";

describe("collection query parsing", () => {
  it("forwards an opaque cursor without decoding or normalizing it", () => {
    expect(readOpaqueCursor("v1.signed/value+token=")).toBe(
      "v1.signed/value+token=",
    );
  });

  it("rejects control characters and excessive cursor input", () => {
    expect(() => readOpaqueCursor("cursor\u0000suffix")).toThrow(/invalid/u);
    expect(() => readOpaqueCursor(" signed-cursor ")).toThrow(/invalid/u);
    expect(readOpaqueCursor("x".repeat(2048))).toHaveLength(2048);
    expect(() => readOpaqueCursor("x".repeat(2049))).toThrow(/invalid/u);
  });

  it("normalizes bounded search and validates real calendar dates", () => {
    expect(readBoundedSearch("  global   equity  ")).toBe("global equity");
    expect(readDateParam("2024-02-29")).toBe("2024-02-29");
    expect(() => readDateParam("2024-02-30")).toThrow(/invalid/u);
    expect(() => validateDateRange("2024-03-01", "2024-02-29")).toThrow(
      /invalid/u,
    );
  });

  it("falls back for unknown closed-enum values", () => {
    const allowed = new Set(["ticker_asc", "market_value_desc"] as const);
    expect(readEnumParam("internal_column", allowed, "ticker_asc")).toBe(
      "ticker_asc",
    );
  });
});
