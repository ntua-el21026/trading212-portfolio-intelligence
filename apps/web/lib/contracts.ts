import type {
  Account,
  AccountSummary,
  Activity,
  Allocation,
  BrokerConnection,
  DirectAllocation,
  Dividend,
  Metric,
  Page,
  Position,
  Principal,
  Quality,
  Reconciliation,
  ReconciliationIssue,
  RefreshRun,
  Snapshot,
} from "@trading212/api-contracts";

// Presentation aliases keep transport naming isolated to this adapter boundary.
export type AccountResponse = Account;
export type AccountSummaryResponse = AccountSummary;
export type ActivityResponse = Activity;
export type AllocationResponse = Allocation;
export type DirectAllocationResponse = DirectAllocation;
export type BrokerConnectionResponse = BrokerConnection;
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
  allocation: DirectAllocation;
  snapshots: Page<Snapshot>;
  reconciliation: Reconciliation;
  quality: Quality;
}

export interface PortfolioContext {
  summary: AccountSummary;
}

export interface OverviewBundle {
  summary: AccountSummary;
  positions: Page<Position>;
  allocation: DirectAllocation;
  reconciliation: Reconciliation;
}

export interface AllocationBundle {
  summary: AccountSummary;
  allocation: DirectAllocation;
}

export interface DividendBundle {
  summary: AccountSummary;
  dividends: Page<Dividend>;
  quality: Quality;
}

export interface QualityBundle {
  discrepancies: Page<ReconciliationIssue>;
  summary: AccountSummary;
  quality: Quality;
  reconciliation: Reconciliation;
}

export interface SettingsBundle {
  summary: AccountSummary;
  connections: BrokerConnection[];
}

export interface SynchronizationBundle {
  summary: AccountSummary;
  quality: Quality;
}

export type DemoViewState =
  "default" | "empty" | "stale" | "partial" | "unreconciled" | "error";
