"use client";

import Link from "next/link";
import { useState } from "react";
import { Surface } from "@trading212/ui";
import type { XrayHeldFundsResponse } from "@trading212/api-contracts";
import { formatDateTime } from "../lib/format";
import { formatHistoricalPercent } from "../lib/historical-format";
import { xrayHref, type XrayQuery } from "../lib/xray-query";

export function XrayFundSelection({
  data,
  query,
}: Readonly<{ data: XrayHeldFundsResponse; query: XrayQuery }>) {
  const [selected, setSelected] = useState(query.fund_ids);
  const current = { ...query, fund_ids: selected };
  return (
    <Surface>
      <h2>Held funds</h2>
      <p>
        Select two to 32 funds. Selection is preserved as you browse the
        complete held-fund catalogue.
      </p>
      <p role="status">{selected.length} funds selected</p>
      <fieldset>
        <legend>Funds on this page</legend>
        {data.held_funds.items.map((fund) => (
          <label key={fund.instrument_id} className="xray-fund-choice">
            <input
              type="checkbox"
              checked={selected.includes(fund.instrument_id)}
              disabled={
                selected.length >= 32 && !selected.includes(fund.instrument_id)
              }
              onChange={(event) =>
                setSelected(
                  event.target.checked
                    ? [...selected, fund.instrument_id]
                    : selected.filter((id) => id !== fund.instrument_id),
                )
              }
            />
            <span>
              <strong>{fund.name}</strong> · {fund.position_count} positions
              <br />
              Coverage {formatHistoricalPercent(fund.unit_coverage.value)} ·
              Unresolved {formatHistoricalPercent(fund.unresolved_weight.value)}{" "}
              · {fund.quality}
              <br />
              Source{" "}
              {fund.source_at
                ? formatDateTime(fund.source_at)
                : "Unavailable"}{" "}
              · Confidence{" "}
              {fund.confidence === null
                ? "Unknown"
                : formatHistoricalPercent(fund.confidence)}
            </span>
          </label>
        ))}
      </fieldset>
      {selected.length >= 2 ? (
        <Link
          prefetch={false}
          className="button button--primary"
          href={xrayHref(current, { view: "pairs" })}
        >
          Compare selected funds
        </Link>
      ) : (
        <p>Select at least two funds to compare overlap.</p>
      )}
      <button
        type="button"
        onClick={() => setSelected([])}
        disabled={!selected.length}
      >
        Clear selection
      </button>
      <nav className="collection-pagination" aria-label="Held-fund pagination">
        <p>
          {data.held_funds.items.length} funds on this page of{" "}
          {data.held_funds.total} held funds.
        </p>
        {data.held_funds.next_cursor ? (
          <Link
            prefetch={false}
            href={xrayHref(current, { cursor: data.held_funds.next_cursor })}
          >
            Next funds
          </Link>
        ) : null}
        {query.cursor ? (
          <Link
            prefetch={false}
            href={xrayHref(current, { cursor: undefined })}
          >
            First funds
          </Link>
        ) : null}
      </nav>
    </Surface>
  );
}
