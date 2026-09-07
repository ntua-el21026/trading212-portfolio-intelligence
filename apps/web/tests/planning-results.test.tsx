import { render, screen, within } from "@testing-library/react";
import type { PlanningDriftRow } from "@trading212/api-contracts";
import { describe, expect, it } from "vitest";

import { DriftTable, Objective } from "../components/planning-results";

const row: PlanningDriftRow = {
  key: "cash",
  node_id: null,
  holding_id: null,
  kind: "cash",
  parent_key: null,
  name: "Cash",
  depth: 0,
  listing_id: null,
  instrument_id: null,
  target_weight: "0",
  actual_value: { amount: "0", currency: "CHF" },
  actual_direct_weight: "0",
  effective_weight: null,
  effective_weight_reason: "effective_exposure_target_unavailable",
  signed_drift: "0",
  absolute_drift: "0",
  relative_drift: null,
  relative_drift_reason: "zero_target_weight",
  classification: "on_target",
  monetary_gap: { amount: "0", currency: "CHF" },
  quality: "fresh",
};

describe("canonical planning result display", () => {
  it("keeps zero amounts distinct from unavailable ratios and shows the reason", () => {
    render(<DriftTable rows={[row]} caption="Canonical drift" />);
    const table = screen.getByRole("table", { name: "Canonical drift" });
    expect(within(table).getAllByText("CHF 0.00")).toHaveLength(2);
    expect(within(table).getByText("Zero Target Weight")).toBeVisible();
    expect(within(table).getByText("Unavailable")).toBeVisible();
    expect(within(table).getByText(/On Target/)).toBeVisible();
  });

  it("renders all nine server objective frontiers without reducing their precision", () => {
    const scores = Array.from(
      { length: 9 },
      (_, index) => `0.00000000000000000${index + 1}`,
    );
    render(
      <Objective
        value={{
          scores,
          quantum: "0.000000000000000001",
          rounding: "ROUND_HALF_EVEN",
          rounding_error_bound: "half_quantum",
        }}
      />,
    );
    expect(screen.getByText(scores.join(" / "))).toBeVisible();
  });
});
