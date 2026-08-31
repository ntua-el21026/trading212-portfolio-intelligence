import type {
  Account,
  AccountSummary,
  Activity,
  Allocation,
  Dividend,
  Metric,
  Page,
  Position,
  Principal,
  Quality,
  Reconciliation,
  RefreshRun,
  Snapshot,
} from "@trading212/api-contracts";

// Presentation aliases keep transport naming isolated to this adapter boundary.
export type AccountResponse = Account;
export type AccountSummaryResponse = AccountSummary;
export type ActivityResponse = Activity;
export type AllocationResponse = Allocation;
export type DividendResponse = Dividend;
export type MetricResponse = Metric;
export type PageResponse<Item> = Page<Item>;
export type PositionResponse = Position;
export type PrincipalResponse = Principal;
export type QualityResponse = Quality;
export type ReconciliationResponse = Reconciliation;
export type RefreshRunResponse = RefreshRun;
export type SnapshotResponse = Snapshot;
export type QualityState = Quality["state"];
export type Availability = Metric["availability"];

export interface PortfolioBundle {
  summary: AccountSummary;
  positions: Page<Position>;
  activity: Page<Activity>;
  dividends: Page<Dividend>;
  allocation: Allocation[];
  snapshots: Page<Snapshot>;
  reconciliation: Reconciliation;
  quality: Quality;
}

export type DemoViewState =
  "default" | "empty" | "stale" | "partial" | "unreconciled" | "error";
