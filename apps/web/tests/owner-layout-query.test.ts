import { describe, expect, it } from "vitest";
import type { OwnerLayoutWidget } from "@trading212/api-contracts";
import { accountSwitchHref } from "../lib/account-selection";
import { readHistoricalQuery } from "../lib/historical-query";
import { readXrayQuery } from "../lib/xray-query";
import { readResearchQuery } from "../lib/research-query";
import { readProjectionQuery } from "../lib/projection-query";
import {
  ownerLayoutHref,
  readOwnerLayoutQuery,
  savedLayoutSelectionHref,
} from "../lib/owner-layout-query";

const id = "00000000-0000-4000-8000-000000000001";
const account = "00000000-0000-4000-8000-000000000002";
const other = "00000000-0000-4000-8000-000000000003";
const at = "2026-09-15T12:30:20.123456Z";
type Selection = NonNullable<OwnerLayoutWidget["selection"]>;
const parsed = (selection: Selection) =>
  Object.fromEntries(
    new URL(savedLayoutSelectionHref(selection, account), "https://local.test")
      .searchParams,
  );

describe("closed saved layout destinations", () => {
  it("round trips the actual saved X-ray parser without replacing original pins", () => {
    const selection: Selection = {
      kind: "saved_run",
      family: "xray",
      run_id: id,
      pane: "result",
      snapshot_id: other,
      source_cutoff_at: at,
      reporting_currency: "USD",
    };
    const result = readXrayQuery(parsed(selection), {
      now: new Date("2030-01-01T00:00:00Z"),
      currency: "EUR",
    });
    expect(result).toMatchObject({
      account,
      run: id,
      snapshot: other,
      cutoff: at,
      currency: "USD",
      view: "exposures",
    });
    expect(() =>
      savedLayoutSelectionHref({ ...selection, snapshot_id: null }, account),
    ).toThrow();
  });
  it("preserves complete historical and research selectors using their actual parsers", () => {
    const selection: Selection = {
      kind: "historical",
      route: "performance",
      start_date: "2026-01-01",
      end_date: "2026-01-31",
      source_cutoff_at: at,
      reporting_currency: "EUR",
      method: "twr",
      frequency: "monthly",
      knowledge: "point_in_time",
      coverage: "require_complete",
      view: "calendar",
      grouping: "holding",
      flow_kind: "all",
      rolling: "none",
      calendar: "month",
      capture_id: id,
    };
    expect(
      readHistoricalQuery(parsed(selection), {
        // Browser clocks have millisecond precision; keep the exact stored
        // microsecond cutoff strictly in the past.
        now: new Date(new Date(at).valueOf() + 1000),
        currency: "USD",
        pathname: "/performance",
      }),
    ).toMatchObject({
      start: "2026-01-01",
      end: "2026-01-31",
      cutoff: at,
      currency: "EUR",
      calendar: "month",
      capture: id,
      knowledge: "point_in_time",
    });
    expect(
      readResearchQuery(
        parsed({
          kind: "research",
          xray_run_id: id,
          source_cutoff_at: at,
          entity_id: other,
          event_kind: "news",
          review_state: "unreviewed",
        }),
        new Date("2030-01-01"),
      ),
    ).toMatchObject({
      xray: id,
      cutoff: at,
      entity: other,
      event_kind: "news",
      review_state: "unreviewed",
    });
    expect(
      readProjectionQuery(
        parsed({
          kind: "saved_run",
          family: "projection",
          run_id: id,
          pane: "goal",
          snapshot_id: null,
          source_cutoff_at: null,
          reporting_currency: null,
        }),
      ),
    ).toMatchObject({ run: id, view: "goal" });
  });
  it("keeps templates account-free and clears all owned pins when switching accounts", () => {
    expect(
      savedLayoutSelectionHref(
        { kind: "workspace", route: "quality", pane: null },
        null,
      ),
    ).toBe("/quality");
    const href = ownerLayoutHref({
      account,
      layout: id,
      version: other,
      mode: "view",
      cursor: undefined,
    });
    const url = new URL(href, "https://local.test");
    expect(
      readOwnerLayoutQuery(Object.fromEntries(url.searchParams)),
    ).toMatchObject({ layout: id, version: other });
    expect(accountSwitchHref(url.pathname, url.searchParams, other)).toBe(
      `/settings/layouts?account=${other}`,
    );
    expect(() =>
      savedLayoutSelectionHref(
        {
          kind: "saved_run",
          family: "projection",
          run_id: id,
          pane: "result",
          snapshot_id: null,
          source_cutoff_at: null,
          reporting_currency: null,
        },
        null,
      ),
    ).toThrow();
  });
  it.each([
    { layout: [id, other] },
    { version: id },
    { mode: "view" },
    { mode: "edit", cursor: "page" },
    { cursor: "x".repeat(2049) },
    { query: "arbitrary" },
    { url: "https://private.invalid" },
    { archived: "1" },
  ])("rejects ambiguous or unapproved query data %o", (search) => {
    expect(() => readOwnerLayoutQuery(search)).toThrow();
  });
});
