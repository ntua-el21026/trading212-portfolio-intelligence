import type { RiskVersionResponse, Snapshot } from "@trading212/api-contracts";
import { Button } from "@trading212/ui";
import type { RiskQuery } from "../lib/risk-query";

export function RiskSelectionForm({
  query,
  versions,
  snapshots,
  benchmarks,
}: Readonly<{
  query: RiskQuery;
  versions: readonly RiskVersionResponse[];
  snapshots: readonly Snapshot[];
  benchmarks: readonly { id: string; label: string }[];
}>) {
  return (
    <form
      action="/risk"
      method="get"
      className="target-form historical-filters"
      aria-label="Risk inputs"
    >
      <input type="hidden" name="view" value="new" />
      <input type="hidden" name="account" value={query.account} />
      {query.definition ? (
        <input type="hidden" name="definition" value={query.definition} />
      ) : null}
      <label>
        <span>Definition version</span>
        <select name="version" defaultValue={query.version ?? ""} required>
          <option value="" disabled>
            Choose an immutable version
          </option>
          {versions.map((row) => (
            <option key={row.id} value={row.id}>
              {row.content.name} · version {row.version_number}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Portfolio snapshot</span>
        <select name="snapshot" defaultValue={query.snapshot ?? ""} required>
          <option value="" disabled>
            Choose a snapshot
          </option>
          {snapshots.map((row) => (
            <option key={row.id} value={row.id}>
              {row.valuation_at} · {row.reporting_currency}
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
          name="cutoff"
          defaultValue={query.cutoff}
          maxLength={32}
          required
          aria-describedby="risk-cutoff-help"
        />
        <small id="risk-cutoff-help">
          UTC timestamp, for example 2026-08-31T12:00:00Z.
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
          <option value="allow_degraded">Show labeled covered subtotals</option>
        </select>
      </label>
      <label>
        <span>Benchmark version</span>
        <select name="benchmark" defaultValue={query.benchmark ?? ""}>
          <option value="">No benchmark (beta and alpha unavailable)</option>
          {query.benchmark &&
          !benchmarks.some((row) => row.id === query.benchmark) ? (
            <option value={query.benchmark}>
              Retained benchmark selection
            </option>
          ) : null}
          {benchmarks.map((row) => (
            <option key={row.id} value={row.id}>
              {row.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Look-through concentration</span>
        <select name="xray_mode" defaultValue={query.xray_mode}>
          <option value="omit">Omit X-ray concentration</option>
          <option value="capture">Include sourced X-ray at this cutoff</option>
        </select>
      </label>
      <Button type="submit">Prepare risk inputs</Button>
    </form>
  );
}
