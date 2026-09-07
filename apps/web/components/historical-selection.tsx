"use client";

import Link from "next/link";
import { useState } from "react";
import { Surface } from "@trading212/ui";
import {
  historicalHref,
  historicalGroupings,
  flowKinds,
  type HistoricalQuery,
} from "../lib/historical-query";
import { titleCase } from "../lib/format";

export interface HistoricalChoice {
  id: string;
  label: string;
}

export function HistoricalSelectionForm({
  pathname,
  query,
  accounts,
  benchmarks,
  benchmarkTotal,
  nextBenchmarkCursor,
  targets,
  targetTotal,
}: Readonly<{
  pathname: "/performance" | "/income";
  query: HistoricalQuery;
  accounts: readonly HistoricalChoice[];
  benchmarks: readonly HistoricalChoice[];
  benchmarkTotal: number;
  nextBenchmarkCursor: string | null;
  targets: readonly HistoricalChoice[];
  targetTotal: number;
}>) {
  const performance = pathname === "/performance";
  const [selectedTarget, setSelectedTarget] = useState(query.target ?? "");
  const [selectedGrouping, setSelectedGrouping] = useState<string>(
    query.grouping,
  );
  const attribution = query.view === "attribution";
  const benchmark = query.view === "benchmark" || attribution;
  const groups = attribution || query.view === "income";
  return (
    <Surface>
      <h2>Period and sources</h2>
      <form
        action={pathname}
        method="get"
        className="target-form historical-filters"
      >
        <input type="hidden" name="view" value={query.view} />
        <label>
          <span>Account</span>
          <select name="account" defaultValue={query.account} required>
            {accounts.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Start date</span>
          <input type="date" name="start" defaultValue={query.start} required />
        </label>
        <label>
          <span>End date</span>
          <input type="date" name="end" defaultValue={query.end} required />
        </label>
        <label>
          <span>Knowledge cutoff (UTC)</span>
          <input
            type="text"
            name="cutoff"
            defaultValue={query.cutoff}
            aria-describedby="historical-cutoff-help"
            maxLength={32}
            required
          />
          <small id="historical-cutoff-help">
            UTC timestamp, for example 2026-08-31T12:00:00.123456Z.
          </small>
        </label>
        <label>
          <span>Reporting currency</span>
          <input
            name="currency"
            defaultValue={query.currency}
            pattern="[A-Z]{3}"
            minLength={3}
            maxLength={3}
            required
          />
        </label>
        <label>
          <span>Historical knowledge</span>
          <select name="knowledge" defaultValue={query.knowledge}>
            <option value="as_of_cutoff">Restated at the cutoff</option>
            <option value="point_in_time">Known at each valuation</option>
          </select>
        </label>
        <label>
          <span>Coverage policy</span>
          <select name="coverage" defaultValue={query.coverage}>
            <option value="require_complete">Require complete inputs</option>
            <option value="allow_degraded">
              Show labeled covered subtotals
            </option>
          </select>
        </label>
        {performance && query.view !== "benchmark" ? (
          <label>
            <span>Return method</span>
            <select name="method" defaultValue={query.method}>
              <option value="twr">Time-weighted return</option>
              {!attribution ? (
                <option value="mwr">Money-weighted return / XIRR</option>
              ) : null}
              <option value="modified_dietz">Modified Dietz</option>
            </select>
          </label>
        ) : null}
        {!attribution && query.view !== "income" ? (
          <label>
            <span>Frequency</span>
            <select name="frequency" defaultValue={query.frequency}>
              <option value="daily">Daily</option>
              <option value="monthly">Monthly</option>
            </select>
          </label>
        ) : null}
        {query.view === "rolling" || query.view === "benchmark" ? (
          <label>
            <span>Rolling window</span>
            <select name="rolling" defaultValue={query.rolling}>
              {query.view === "benchmark" ? (
                <option value="none">No rolling comparison</option>
              ) : null}
              <option value="calendar_days_30">30 calendar days</option>
              <option value="calendar_days_90">90 calendar days</option>
              <option value="calendar_days_365">365 calendar days</option>
            </select>
          </label>
        ) : null}
        {query.view === "calendar" || query.view === "benchmark" ? (
          <label>
            <span>Calendar period</span>
            <select name="calendar" defaultValue={query.calendar}>
              {query.view === "benchmark" ? (
                <option value="none">No calendar comparison</option>
              ) : null}
              <option value="month">Month</option>
              <option value="quarter">Quarter</option>
              <option value="year">Year</option>
            </select>
          </label>
        ) : null}
        {benchmark ? (
          <label>
            <span>
              Benchmark version{attribution ? " for cash drag (optional)" : ""}
            </span>
            <select
              name="benchmark"
              defaultValue={query.benchmark ?? ""}
              required={!attribution}
            >
              <option value="">
                {attribution
                  ? "No counterfactual benchmark"
                  : "Choose a published benchmark"}
              </option>
              {query.benchmark &&
              !benchmarks.some((row) => row.id === query.benchmark) ? (
                <option value={query.benchmark}>
                  Selected immutable benchmark version
                </option>
              ) : null}
              {benchmarks.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {groups ? (
          <label>
            <span>Grouping</span>
            <select
              name="grouping"
              value={selectedGrouping}
              onChange={(event) => setSelectedGrouping(event.target.value)}
            >
              {(attribution ? historicalGroupings : ["holding", "group"]).map(
                (value) => (
                  <option key={value} value={value}>
                    {titleCase(value)}
                  </option>
                ),
              )}
            </select>
          </label>
        ) : null}
        {groups ? (
          <label>
            <span>Published target for group comparison</span>
            <select
              name="target"
              value={selectedTarget}
              onChange={(event) => setSelectedTarget(event.target.value)}
              required={selectedGrouping === "group"}
            >
              <option value="">No target selected</option>
              {query.target &&
              !targets.some((row) => row.id === query.target) ? (
                <option value={query.target}>
                  Selected immutable target version
                </option>
              ) : null}
              {targets.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {groups && selectedTarget ? (
          <label>
            <span>Target timing</span>
            <select
              name="grouping_policy"
              defaultValue={query.grouping_policy ?? "explicit_comparison"}
            >
              <option value="explicit_comparison">
                Explicit comparison with selected target
              </option>
              <option value="historical_assignment">
                Only assignments known at that time
              </option>
            </select>
          </label>
        ) : null}
        {groups ? (
          <label>
            <span>Top components</span>
            <input
              name="top"
              type="number"
              min={1}
              max={50}
              step={1}
              defaultValue={query.top}
            />
          </label>
        ) : null}
        {query.view === "cash_flows" ? (
          <label>
            <span>Event kind</span>
            <select name="kind" defaultValue={query.kind}>
              {flowKinds.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {query.view === "series" || query.view === "cash_flows" ? (
          <label>
            <span>Rows per page</span>
            <input
              name="limit"
              type="number"
              min={1}
              max={100}
              step={1}
              defaultValue={query.limit}
            />
          </label>
        ) : null}
        {query.view === "summary" || query.view === "series" ? (
          <label>
            <span>Flow overlay</span>
            <select name="flows" defaultValue={query.flows}>
              <option value="show">Show external flows</option>
              <option value="hide">Hide overlay</option>
            </select>
          </label>
        ) : null}
        <button type="submit">Apply filters</button>
      </form>
      {query.capture ? (
        <p className="muted">
          This view replays retained inputs. Applying filters requests a new
          compatible capture.
        </p>
      ) : null}
      {benchmark ? (
        <p className="muted">
          {benchmarks.length} benchmark choices on this page of {benchmarkTotal}{" "}
          definitions.{" "}
          {nextBenchmarkCursor ? (
            <Link
              prefetch={false}
              href={historicalHref(pathname, query, {
                benchmarks_cursor: nextBenchmarkCursor,
              })}
            >
              Browse more benchmark definitions
            </Link>
          ) : null}{" "}
          <Link prefetch={false} href="/sources?kind=definitions">
            Inspect benchmark history
          </Link>
          .
        </p>
      ) : null}
      {groups ? (
        <p className="muted">
          {targets.length} active target choices from {targetTotal} Pies.{" "}
          <Link prefetch={false} href="/pies">
            Browse all Pies and immutable versions
          </Link>
          .
        </p>
      ) : null}
    </Surface>
  );
}

export function HistoricalTabs({
  query,
  pathname,
}: Readonly<{ query: HistoricalQuery; pathname: "/performance" | "/income" }>) {
  const views =
    pathname === "/performance"
      ? ([
          "summary",
          "benchmark",
          "series",
          "rolling",
          "calendar",
          "attribution",
        ] as const)
      : (["income", "cash_flows"] as const);
  return (
    <nav
      aria-label={
        pathname === "/performance" ? "Performance views" : "Income views"
      }
      className="historical-tabs"
    >
      {views.map((view) => (
        <Link
          prefetch={false}
          key={view}
          href={historicalHref(pathname, query, {
            view,
            ...(view === "rolling" && query.rolling === "none"
              ? { rolling: "calendar_days_30" as const }
              : {}),
            ...(view === "calendar" && query.calendar === "none"
              ? { calendar: "month" as const }
              : {}),
            ...(view === "attribution" && query.method === "mwr"
              ? { method: "twr" as const }
              : {}),
          })}
          aria-current={query.view === view ? "page" : undefined}
        >
          {titleCase(view)}
        </Link>
      ))}
    </nav>
  );
}
