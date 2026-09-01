import type {
  AccountSummaryResponse,
  ActivityResponse,
  AllocationResponse,
  DemoViewState,
  DirectAllocationResponse,
  DividendResponse,
  MetricResponse,
  PortfolioBundle,
  PositionResponse,
  QualityResponse,
  ReconciliationResponse,
  SnapshotResponse,
} from "./contracts";

const AS_OF = "2026-08-31T09:30:00Z";
const SOURCE_AT = "2026-08-31T09:28:00Z";
const CALCULATION_VERSION = "phase1-core-accounting/1.0.0";

function quality(
  state: QualityResponse["state"] = "fresh",
  warnings: string[] = [],
  missingInputs: string[] = [],
): QualityResponse {
  return {
    state,
    as_of: AS_OF,
    source_timestamp: SOURCE_AT,
    freshness_threshold_seconds: 900,
    warnings,
    missing_inputs: missingInputs,
  };
}

function metric(
  value: string,
  methodology: string,
  provenance: string[] = ["synthetic_canonical_fixture"],
): MetricResponse {
  return {
    value,
    reporting_currency: "EUR",
    availability: "available",
    calculation_version: CALCULATION_VERSION,
    methodology,
    provenance,
    assumptions: [],
    unavailable_reason: null,
  };
}

function unavailable(reason: string, methodology: string): MetricResponse {
  return {
    value: null,
    reporting_currency: "EUR",
    availability: "unavailable",
    calculation_version: CALCULATION_VERSION,
    methodology,
    provenance: ["coverage_gate"],
    assumptions: [],
    unavailable_reason: reason,
  };
}

const freshQuality = quality();

const positions: PositionResponse[] = [
  [
    "vwce",
    "VWCE",
    "Vanguard FTSE All-World UCITS ETF",
    "etf",
    "412.5",
    "252.121212",
    "104000",
    "96720.00",
    "7280.00",
    "0.418626849994",
  ],
  [
    "iwda",
    "IWDA",
    "iShares Core MSCI World UCITS ETF",
    "etf",
    "612.75",
    "104.447164",
    "64000",
    "59520.00",
    "4480.00",
    "0.257616523073",
  ],
  [
    "asml",
    "ASML",
    "ASML Holding",
    "equity",
    "48",
    "750",
    "36000",
    "33480.00",
    "2520.00",
    "0.144909294229",
  ],
  [
    "msft",
    "MSFT",
    "Microsoft",
    "equity",
    "52",
    "423.076923",
    "22000",
    "20460.00",
    "1540.00",
    "0.088555679806",
  ],
  [
    "novo",
    "NOVO-B",
    "Novo Nordisk",
    "equity",
    "125",
    "80",
    "10000",
    "9300.00",
    "700.00",
    "0.040252581730",
  ],
].map(
  ([
    id,
    ticker,
    name,
    instrumentType,
    quantity,
    price,
    value,
    cost,
    profit,
    weight,
  ]) => ({
    id,
    ticker,
    name,
    instrument_type: instrumentType,
    quantity,
    trading_currency: "EUR",
    current_price: price,
    market_value: metric(value, "provider-observed market value"),
    provider_cost_basis: metric(cost, "provider-reported cost basis", [
      "provider_position_observations",
    ]),
    provider_unrealized_profit_loss: metric(
      profit,
      "provider-reported unrealized profit/loss",
      ["provider_position_observations"],
    ),
    direct_weight: weight,
    data_quality: freshQuality,
  }),
);

const activity: ActivityResponse[] = [
  {
    id: "tx-2026-08-dividend-vwce",
    occurred_at: "2026-08-28T08:00:00Z",
    activity_type: "dividend",
    direction: "credit",
    amount: metric("418.20", "normalized investment income"),
    ticker: "VWCE",
    quantity: null,
    description: "Dividend received",
    data_quality: freshQuality,
  },
  {
    id: "tx-2026-08-buy-asml",
    occurred_at: "2026-08-12T14:32:00Z",
    activity_type: "buy",
    direction: "internal_exchange",
    amount: metric("-7500.00", "normalized security purchase cash leg"),
    ticker: "ASML",
    quantity: "10",
    description: "Bought 10 ASML shares",
    data_quality: freshQuality,
  },
  {
    id: "tx-2026-07-deposit",
    occurred_at: "2026-07-01T09:15:00Z",
    activity_type: "deposit",
    direction: "external_inflow",
    amount: metric("10000.00", "normalized external contribution"),
    ticker: null,
    quantity: null,
    description: "Bank transfer contribution",
    data_quality: freshQuality,
  },
];

const dividends: DividendResponse[] = [
  {
    id: "dividend-vwce-20260828",
    paid_on: "2026-08-28",
    ticker: "VWCE",
    net_amount: metric("418.20", "normalized provider dividend"),
    gross_amount: metric("492.00", "provider-reported gross dividend"),
    withholding_tax: metric("-73.80", "provider-reported withholding"),
    quantity: "412.5",
    data_quality: freshQuality,
  },
];

const snapshots: SnapshotResponse[] = [
  {
    id: "snapshot-2026-07-31",
    valuation_at: "2026-07-31T16:30:00Z",
    source_cutoff_at: "2026-07-31T16:28:00Z",
    reporting_currency: "EUR",
    total_value: metric("241220.18", "immutable portfolio snapshot"),
    cash_value: metric("10420.18", "immutable cash snapshot"),
    invested_value: metric("230800.00", "immutable position snapshots"),
    net_contributions: metric("230000.00", "covered external cash flows"),
    data_quality: freshQuality,
  },
  {
    id: "snapshot-2026-08-31",
    valuation_at: AS_OF,
    source_cutoff_at: SOURCE_AT,
    reporting_currency: "EUR",
    total_value: metric("248431.27", "immutable portfolio snapshot"),
    cash_value: metric("12431.27", "immutable cash snapshot"),
    invested_value: metric("236000.00", "immutable position snapshots"),
    net_contributions: metric("230000.00", "covered external cash flows"),
    data_quality: freshQuality,
  },
];

const allocationItems: AllocationResponse[] = [
  ...positions.map((position) => ({
    id: position.id,
    label: position.name,
    asset_type: position.instrument_type,
    market_value: position.market_value,
    weight: position.direct_weight,
    weight_availability: "available" as const,
  })),
  {
    id: "cash",
    label: "Cash",
    asset_type: "cash",
    market_value: metric("12431.27", "canonical cash ledger"),
    weight: "0.050039071168",
    weight_availability: "available",
  },
];

const allocation: DirectAllocationResponse = {
  items: allocationItems,
  returned_count: allocationItems.length,
  total: allocationItems.length,
  limit: 50,
  truncated: false,
};

const summary: AccountSummaryResponse = {
  account: {
    id: "f0f5c66e-b128-59b2-a620-83bc8faa4a57",
    display_name: "Demo portfolio",
    provider: "synthetic",
    environment: "synthetic",
    account_type: "invest",
    reporting_currency: "EUR",
    connection_state: "connected_read_only",
    last_refresh_at: AS_OF,
  },
  total_value: metric("248431.27", "broker account plus canonical components"),
  cash_balance: metric("12431.27", "canonical cash ledger"),
  invested_value: metric(
    "236000.00",
    "sum of direct provider-observed positions",
  ),
  net_contributions: metric("230000.00", "covered external cash flows only"),
  dividends_received: metric("1738.20", "covered normalized dividend history"),
  realized_profit_loss: unavailable(
    "Complete disposal basis is not available in the synthetic fixture.",
    "weighted-average acquisition policy",
  ),
  unrealized_profit_loss: metric(
    "18431.27",
    "provider-reported unrealized profit/loss retained separately",
    ["provider_position_observations"],
  ),
  data_quality: freshQuality,
  position_count: positions.length,
};

const reconciliation: ReconciliationResponse = {
  status: "reconciled",
  evaluated_at: AS_OF,
  algorithm_version: "phase1-reconciliation/1.0.0",
  tolerance_version: "phase1-tolerance/1.0.0",
  issues: [],
  discrepancy_count: 0,
  data_quality: freshQuality,
};

const defaultBundle: PortfolioBundle = {
  summary,
  positions: {
    items: positions,
    next_cursor: null,
    limit: 50,
    total: positions.length,
  },
  activity: {
    items: activity,
    next_cursor: null,
    limit: 50,
    total: activity.length,
  },
  dividends: {
    items: dividends,
    next_cursor: null,
    limit: 50,
    total: dividends.length,
  },
  allocation,
  snapshots: {
    items: snapshots,
    next_cursor: null,
    limit: 50,
    total: snapshots.length,
  },
  reconciliation,
  quality: freshQuality,
};

function largeCollectionFixture(bundle: PortfolioBundle): PortfolioBundle {
  if (process.env.PORTFOLIO_E2E_LARGE_COLLECTIONS !== "1") {
    return bundle;
  }

  const extraPositions = Array.from({ length: 60 }, (_, index) => {
    const sequence = String(index + 1).padStart(3, "0");
    const marketValue = String(9_000 - index * 100);
    return {
      id: `fixture-position-${sequence}`,
      ticker: `FX${sequence}`,
      name: `Deterministic fixture holding ${sequence}`,
      instrument_type: "equity",
      quantity: "1",
      trading_currency: "EUR",
      current_price: marketValue,
      market_value: metric(marketValue, "deterministic browser fixture"),
      provider_cost_basis: metric(marketValue, "deterministic browser fixture"),
      provider_unrealized_profit_loss: metric(
        "0",
        "deterministic browser fixture",
      ),
      direct_weight: `0.0${String(39 - Math.floor(index / 2)).padStart(2, "0")}`,
      data_quality: freshQuality,
    } satisfies PositionResponse;
  });
  const extraActivity = Array.from({ length: 60 }, (_, index) => {
    const sequence = String(index + 1).padStart(3, "0");
    const occurredAt = new Date(
      Date.UTC(2026, 5, 30, 12) - index * 86_400_000,
    ).toISOString();
    return {
      id: `fixture-activity-${sequence}`,
      occurred_at: occurredAt,
      activity_type: index % 2 === 0 ? "buy" : "sell",
      direction: "internal_exchange",
      amount: metric(
        index % 2 === 0 ? "-100.00" : "100.00",
        "deterministic browser fixture",
      ),
      ticker: `FX${String((index % 60) + 1).padStart(3, "0")}`,
      quantity: "1",
      description: `Deterministic activity fixture ${sequence}`,
      data_quality: freshQuality,
    } satisfies ActivityResponse;
  });
  const extraDividends = Array.from({ length: 60 }, (_, index) => {
    const sequence = String(index + 1).padStart(3, "0");
    const paidOn = new Date(Date.UTC(2026, 5, 30) - index * 86_400_000)
      .toISOString()
      .slice(0, 10);
    return {
      id: `fixture-dividend-${sequence}`,
      paid_on: paidOn,
      ticker: `FX${String((index % 60) + 1).padStart(3, "0")}`,
      net_amount: metric("1.00", "deterministic browser fixture"),
      gross_amount: metric("1.20", "deterministic browser fixture"),
      withholding_tax: metric("-0.20", "deterministic browser fixture"),
      quantity: "1",
      data_quality: freshQuality,
    } satisfies DividendResponse;
  });
  const extraSnapshots = Array.from({ length: 63 }, (_, index) => {
    const sequence = String(index + 1).padStart(3, "0");
    const valuationAt = new Date(
      Date.UTC(2026, 5, 30, 16, 30) - index * 86_400_000,
    ).toISOString();
    const sourceAt = new Date(Date.parse(valuationAt) - 120_000).toISOString();
    return {
      id: `fixture-snapshot-${sequence}`,
      valuation_at: valuationAt,
      source_cutoff_at: sourceAt,
      reporting_currency: "EUR",
      total_value: metric(
        String(240_000 - index * 100),
        "deterministic browser fixture",
      ),
      cash_value: metric("10000", "deterministic browser fixture"),
      invested_value: metric(
        String(230_000 - index * 100),
        "deterministic browser fixture",
      ),
      net_contributions: metric("230000", "deterministic browser fixture"),
      data_quality: freshQuality,
    } satisfies SnapshotResponse;
  });
  const extraDiscrepancies: ReconciliationResponse["issues"] =
    bundle.reconciliation.issues.length === 0
      ? []
      : Array.from({ length: 60 }, (_, index) => {
          const sequence = String(index + 1).padStart(3, "0");
          return {
            id: `fixture-discrepancy-${sequence}`,
            issue_type: "quantity_mismatch",
            severity: "warning",
            status: "open",
            summary: `Deterministic discrepancy fixture ${sequence}.`,
            expected_value: "10",
            observed_value: "9",
            residual: "-1",
            tolerance: "0.000001",
            currency: null,
          };
        });

  const allAllocationItems = [
    ...bundle.allocation.items.filter((item) => item.asset_type !== "cash"),
    ...extraPositions.map(
      (position) =>
        ({
          id: position.id,
          label: position.name,
          asset_type: position.instrument_type,
          market_value: position.market_value,
          weight: position.direct_weight,
          weight_availability: "available",
        }) satisfies AllocationResponse,
    ),
  ].sort(
    (left, right) =>
      Number(right.weight ?? "-1") - Number(left.weight ?? "-1") ||
      left.id.localeCompare(right.id),
  );
  const cash = bundle.allocation.items.find(
    (item) => item.asset_type === "cash",
  );
  const boundedAllocationItems = [
    ...allAllocationItems.slice(0, 50),
    ...(cash === undefined ? [] : [cash]),
  ];

  return {
    ...bundle,
    summary: {
      ...bundle.summary,
      position_count: bundle.positions.items.length + extraPositions.length,
    },
    positions: {
      ...bundle.positions,
      items: [...bundle.positions.items, ...extraPositions],
      total: bundle.positions.items.length + extraPositions.length,
    },
    activity: {
      ...bundle.activity,
      items: [...bundle.activity.items, ...extraActivity],
      total: bundle.activity.items.length + extraActivity.length,
    },
    dividends: {
      ...bundle.dividends,
      items: [...bundle.dividends.items, ...extraDividends],
      total: bundle.dividends.items.length + extraDividends.length,
    },
    allocation: {
      items: boundedAllocationItems,
      returned_count: boundedAllocationItems.length,
      total: allAllocationItems.length + (cash === undefined ? 0 : 1),
      limit: 50,
      truncated: allAllocationItems.length > 50,
    },
    snapshots: {
      ...bundle.snapshots,
      items: [...bundle.snapshots.items, ...extraSnapshots],
      total: bundle.snapshots.items.length + extraSnapshots.length,
    },
    reconciliation: {
      ...bundle.reconciliation,
      issues: [...bundle.reconciliation.issues, ...extraDiscrepancies],
      discrepancy_count:
        bundle.reconciliation.issues.length + extraDiscrepancies.length,
    },
  };
}

function withQuality(
  bundle: PortfolioBundle,
  next: QualityResponse,
): PortfolioBundle {
  return {
    ...bundle,
    summary: { ...bundle.summary, data_quality: next },
    positions: {
      ...bundle.positions,
      items: bundle.positions.items.map((item) => ({
        ...item,
        data_quality: next,
      })),
    },
    activity: {
      ...bundle.activity,
      items: bundle.activity.items.map((item) => ({
        ...item,
        data_quality: next,
      })),
    },
    dividends: {
      ...bundle.dividends,
      items: bundle.dividends.items.map((item) => ({
        ...item,
        data_quality: next,
      })),
    },
    snapshots: {
      ...bundle.snapshots,
      items: bundle.snapshots.items.map((item) => ({
        ...item,
        data_quality: next,
      })),
    },
    reconciliation: { ...bundle.reconciliation, data_quality: next },
    quality: next,
  };
}

export function getDemoPortfolio(
  state: DemoViewState = "default",
): PortfolioBundle {
  if (state === "error") {
    throw new Error("Synthetic error state requested for local UI validation.");
  }
  if (state === "empty") {
    return {
      ...defaultBundle,
      summary: {
        ...summary,
        total_value: metric("0", "empty synthetic portfolio"),
        cash_balance: metric("0", "empty synthetic portfolio"),
        invested_value: metric("0", "empty synthetic portfolio"),
        net_contributions: metric("0", "empty synthetic portfolio"),
        dividends_received: metric("0", "empty synthetic portfolio"),
        unrealized_profit_loss: metric("0", "empty synthetic portfolio"),
        position_count: 0,
      },
      positions: { items: [], next_cursor: null, limit: 50, total: 0 },
      activity: { items: [], next_cursor: null, limit: 50, total: 0 },
      dividends: { items: [], next_cursor: null, limit: 50, total: 0 },
      allocation: {
        items: [],
        returned_count: 0,
        total: 0,
        limit: 50,
        truncated: false,
      },
      snapshots: { items: [], next_cursor: null, limit: 50, total: 0 },
    };
  }
  if (state === "stale") {
    return withQuality(
      defaultBundle,
      quality("stale", [
        "The last complete source observation is older than the freshness policy.",
      ]),
    );
  }
  if (state === "partial") {
    return withQuality(
      defaultBundle,
      quality(
        "partial",
        ["Dividend history is incomplete for the selected coverage period."],
        ["historical_dividends"],
      ),
    );
  }
  if (state === "unreconciled") {
    const next = quality("unreconciled", [
      "One cash observation is outside the active reconciliation tolerance.",
    ]);
    return largeCollectionFixture({
      ...withQuality(defaultBundle, next),
      reconciliation: {
        status: "unreconciled",
        evaluated_at: AS_OF,
        algorithm_version: "phase1-reconciliation/1.0.0",
        tolerance_version: "phase1-tolerance/1.0.0",
        issues: [
          {
            id: "demo-cash-residual",
            issue_type: "cash_residual",
            severity: "warning",
            status: "open",
            summary: "Observed cash differs from the covered canonical ledger.",
            expected_value: "12431.27",
            observed_value: "12430.97",
            residual: "-0.30",
            tolerance: "0.01",
            currency: "EUR",
          },
        ],
        discrepancy_count: 1,
        data_quality: next,
      },
    });
  }
  return largeCollectionFixture(defaultBundle);
}

export const demoRefreshRun = {
  id: "79c326d4-79b3-5a28-a69e-cbc9a3bc5df6",
  account_id: "f0f5c66e-b128-59b2-a620-83bc8faa4a57",
  status: "succeeded",
  requested_at: AS_OF,
  completed_at: AS_OF,
  correlation_id: "local-demo-refresh",
  capabilities: [
    "account_summary",
    "portfolio_positions",
    "historical_transactions",
    "historical_dividends",
  ],
  warnings: ["Synthetic local provider; no external broker request was made."],
} as const;
