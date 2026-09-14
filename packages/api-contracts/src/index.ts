import { z } from "zod";

export const decimalStringSchema = z
  .string()
  .regex(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/);
const dateTimeSchema = z.iso.datetime({ offset: true });
const dateSchema = z.iso.date();

export const errorEnvelopeSchema = z.strictObject({
  error: z.strictObject({
    code: z.string(),
    message: z.string(),
    correlation_id: z.string(),
    retryable: z.boolean(),
    details: z.record(z.string(), z.string()),
  }),
});

export const qualitySchema = z.strictObject({
  state: z.enum([
    "fresh",
    "stale",
    "partial",
    "estimated",
    "unreconciled",
    "failed",
  ]),
  as_of: dateTimeSchema,
  source_timestamp: dateTimeSchema,
  freshness_threshold_seconds: z.number().int().nonnegative(),
  warnings: z.array(z.string()),
  missing_inputs: z.array(z.string()),
});

export const metricSchema = z.strictObject({
  value: decimalStringSchema.nullable(),
  reporting_currency: z.string().regex(/^[A-Z]{3}$/),
  availability: z.enum(["available", "partial", "unavailable"]),
  calculation_version: z.string(),
  methodology: z.string(),
  provenance: z.array(z.string()),
  assumptions: z.array(z.string()),
  unavailable_reason: z.string().nullable(),
});

export const principalSchema = z.strictObject({
  principal_id: z.string(),
  owner_id: z.string(),
  scopes: z.array(z.string()),
});

export const localSessionSchema = z.strictObject({
  principal: principalSchema,
  csrf_token: z.string(),
  expires_at: dateTimeSchema,
});

export const accountSchema = z.strictObject({
  id: z.string(),
  display_name: z.string(),
  provider: z.string(),
  environment: z.string(),
  account_type: z.string(),
  reporting_currency: z.string().regex(/^[A-Z]{3}$/),
  connection_state: z.string(),
  last_refresh_at: dateTimeSchema.nullable(),
});

export const accountSummarySchema = z.strictObject({
  account: accountSchema,
  total_value: metricSchema,
  cash_balance: metricSchema,
  invested_value: metricSchema,
  net_contributions: metricSchema,
  dividends_received: metricSchema,
  realized_profit_loss: metricSchema,
  unrealized_profit_loss: metricSchema,
  data_quality: qualitySchema,
  position_count: z.number().int().nonnegative(),
});

export const positionSchema = z.strictObject({
  id: z.string(),
  ticker: z.string(),
  name: z.string(),
  instrument_type: z.string(),
  quantity: decimalStringSchema,
  trading_currency: z.string().regex(/^[A-Z]{3}$/),
  current_price: decimalStringSchema.nullable(),
  market_value: metricSchema,
  provider_cost_basis: metricSchema,
  provider_unrealized_profit_loss: metricSchema,
  direct_weight: decimalStringSchema.nullable(),
  data_quality: qualitySchema,
});

export const activitySchema = z.strictObject({
  id: z.string(),
  occurred_at: dateTimeSchema,
  activity_type: z.string(),
  direction: z.string(),
  amount: metricSchema,
  ticker: z.string().nullable(),
  quantity: decimalStringSchema.nullable(),
  description: z.string(),
  data_quality: qualitySchema,
});

export const dividendSchema = z.strictObject({
  id: z.string(),
  paid_on: dateSchema,
  ticker: z.string(),
  net_amount: metricSchema,
  gross_amount: metricSchema,
  withholding_tax: metricSchema,
  quantity: decimalStringSchema.nullable(),
  data_quality: qualitySchema,
});

export const orderSchema = z.strictObject({
  id: z.string(),
  created_at: dateTimeSchema,
  ticker: z.string(),
  side: z.string(),
  order_type: z.string(),
  status: z.string(),
  quantity: decimalStringSchema.nullable(),
  filled_quantity: decimalStringSchema.nullable(),
  limit_price: decimalStringSchema.nullable(),
  observed_value: metricSchema,
  data_quality: qualitySchema,
});

export const allocationSchema = z.strictObject({
  id: z.string(),
  label: z.string(),
  asset_type: z.string(),
  market_value: metricSchema,
  weight: decimalStringSchema.nullable(),
  weight_availability: z.enum(["available", "partial", "unavailable"]),
});

export const directAllocationSchema = z.strictObject({
  items: z.array(allocationSchema),
  returned_count: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive().max(50),
  truncated: z.boolean(),
});

export const snapshotSchema = z.strictObject({
  id: z.string(),
  valuation_at: dateTimeSchema,
  source_cutoff_at: dateTimeSchema,
  reporting_currency: z.string().regex(/^[A-Z]{3}$/),
  total_value: metricSchema,
  cash_value: metricSchema,
  invested_value: metricSchema,
  net_contributions: metricSchema,
  data_quality: qualitySchema,
});

export const snapshotDetailSchema = snapshotSchema.extend({
  dividends_received: metricSchema,
  realized_profit_loss: metricSchema,
  unrealized_profit_loss: metricSchema,
});

export const snapshotComparisonSchema = z.strictObject({
  start: snapshotSchema,
  end: snapshotSchema,
  value_change: metricSchema,
  net_external_flows: metricSchema,
  investment_result: metricSchema,
  reconciliation_residual: metricSchema,
  data_quality: qualitySchema,
});

export const reconciliationIssueSchema = z.strictObject({
  id: z.string(),
  issue_type: z.string(),
  severity: z.string(),
  status: z.string(),
  summary: z.string(),
  expected_value: decimalStringSchema.nullable(),
  observed_value: decimalStringSchema.nullable(),
  residual: decimalStringSchema.nullable(),
  tolerance: decimalStringSchema.nullable(),
  currency: z.string().nullable(),
});

export const reconciliationSchema = z.strictObject({
  status: z.string(),
  evaluated_at: dateTimeSchema,
  algorithm_version: z.string(),
  tolerance_version: z.string(),
  issues: z.array(reconciliationIssueSchema),
  discrepancy_count: z.number().int().nonnegative(),
  data_quality: qualitySchema,
});

export const refreshRunSchema = z.strictObject({
  id: z.string(),
  account_id: z.string(),
  status: z.string(),
  requested_at: dateTimeSchema,
  completed_at: dateTimeSchema.nullable(),
  correlation_id: z.string(),
  capabilities: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const brokerConnectionSchema = z.strictObject({
  id: z.string(),
  provider: z.string(),
  environment: z.string(),
  status: z.string(),
  state: z.string(),
  credential_state: z.enum(["configured", "not_configured"]),
  last_successful_refresh_at: dateTimeSchema.nullable(),
  read_only: z.literal(true),
});

export const instrumentSchema = z.strictObject({
  id: z.string(),
  instrument_id: z.string(),
  listing_id: z.string(),
  ticker: z.string(),
  name: z.string(),
  canonical_name: z.string(),
  instrument_type: z.string(),
  isin: z.string().nullable(),
  exchange_mic: z.string().nullable(),
  exchange_id: z.string().nullable(),
  trading_currency: z.string().regex(/^[A-Z]{3}$/),
  provider: z.string(),
  environment: z.string(),
  listing_status: z.string(),
});

export const returnMetricSchema = z.strictObject({
  method_id: z.string(),
  value_kind: z.string(),
  period_start: dateTimeSchema.nullable(),
  period_end: dateTimeSchema,
  value: decimalStringSchema.nullable(),
  annualized_value: decimalStringSchema.nullable(),
  availability: z.string(),
  calculation_version: z.string(),
  methodology: z.string(),
  converged: z.boolean().nullable(),
  iterations: z.number().int().nonnegative().nullable(),
  missing_inputs: z.array(z.string()),
  assumptions: z.array(z.string()),
  warnings: z.array(z.string()),
  quality_state: z.string(),
  unavailable_reason: z.string().nullable(),
});

export const performanceSummarySchema = z.strictObject({
  period_start: dateSchema.nullable(),
  period_end: dateSchema,
  money_weighted_return: returnMetricSchema,
  time_weighted_return: returnMetricSchema,
  modified_dietz_return: returnMetricSchema,
  data_quality: qualitySchema,
});

export const capabilityQualitySchema = z.strictObject({
  capability: z.string(),
  data_quality: qualitySchema,
});

export const refreshStepQualitySchema = z.strictObject({
  capability: z.string(),
  status: z.string(),
  warnings: z.array(z.string()),
});

export const refreshRunQualitySchema = z.strictObject({
  id: z.string(),
  status: z.string(),
  started_at: dateTimeSchema,
  completed_at: dateTimeSchema.nullable(),
  steps: z.array(refreshStepQualitySchema),
});

export const checkpointQualitySchema = z.strictObject({
  capability: z.string(),
  version: z.number().int().positive(),
  coverage_start_at: dateTimeSchema.nullable(),
  coverage_end_at: dateTimeSchema.nullable(),
  coverage_complete: z.boolean(),
});

export const dataQualitySummarySchema = z.strictObject({
  as_of: dateTimeSchema,
  reporting_currency: z.string().regex(/^[A-Z]{3}$/),
  data_quality: qualitySchema,
  capabilities: z.array(capabilityQualitySchema),
  failed_or_partial_runs: z.array(z.string()),
  latest_refresh_run: refreshRunQualitySchema.nullable(),
  latest_runs_by_status: z.array(refreshRunQualitySchema).max(3),
  checkpoints: z.array(checkpointQualitySchema),
  latest_snapshot_id: z.string().nullable(),
  latest_snapshot_source_cutoff_at: dateTimeSchema.nullable(),
  materialization_state: z.enum(["available", "partial", "missing"]),
  reconciliation_status: z.string(),
  missing_fx_record_count: z.number().int().nonnegative(),
  unknown_mapping_record_count: z.number().int().nonnegative(),
  read_only: z.literal(true),
});

export const pageSchema = <ItemSchema extends z.ZodType>(item: ItemSchema) =>
  z.strictObject({
    items: z.array(item),
    next_cursor: z.string().nullable(),
    limit: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  });

export type ErrorEnvelope = z.infer<typeof errorEnvelopeSchema>;
export type Quality = z.infer<typeof qualitySchema>;
export type Metric = z.infer<typeof metricSchema>;
export type Principal = z.infer<typeof principalSchema>;
export type LocalSession = z.infer<typeof localSessionSchema>;
export type Account = z.infer<typeof accountSchema>;
export type AccountSummary = z.infer<typeof accountSummarySchema>;
export type Position = z.infer<typeof positionSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type Dividend = z.infer<typeof dividendSchema>;
export type Order = z.infer<typeof orderSchema>;
export type Allocation = z.infer<typeof allocationSchema>;
export type DirectAllocation = z.infer<typeof directAllocationSchema>;
export type Snapshot = z.infer<typeof snapshotSchema>;
export type SnapshotDetail = z.infer<typeof snapshotDetailSchema>;
export type SnapshotComparison = z.infer<typeof snapshotComparisonSchema>;
export type Reconciliation = z.infer<typeof reconciliationSchema>;
export type ReconciliationIssue = z.infer<typeof reconciliationIssueSchema>;
export type RefreshRun = z.infer<typeof refreshRunSchema>;
export type BrokerConnection = z.infer<typeof brokerConnectionSchema>;
export type Instrument = z.infer<typeof instrumentSchema>;
export type PerformanceSummary = z.infer<typeof performanceSummarySchema>;
export type DataQualitySummary = z.infer<typeof dataQualitySummarySchema>;
export type Page<Item> = {
  items: Item[];
  next_cursor: string | null;
  limit: number;
  total: number;
};

export class PortfolioApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly correlationId: string | null;
  public readonly retryable: boolean;

  constructor(status: number, envelope: ErrorEnvelope | null) {
    super(
      envelope?.error.message ??
        `Portfolio API request failed with status ${status}`,
    );
    this.name = "PortfolioApiError";
    this.status = status;
    this.code = envelope?.error.code ?? "UNEXPECTED_RESPONSE";
    this.correlationId = envelope?.error.correlation_id ?? null;
    this.retryable = envelope?.error.retryable ?? false;
  }
}

export interface PortfolioApiClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  fetch?: typeof fetch;
  headers?: () => HeadersInit;
}

export interface PageOptions {
  cursor?: string | null;
  limit?: number;
}

export interface PositionPageOptions extends PageOptions {
  sort?: "market_value_desc" | "ticker_asc" | "weight_desc";
  search?: string;
}

export interface ActivityPageOptions extends PageOptions {
  startDate?: string;
  endDate?: string;
  activityType?:
    | "all"
    | "buy"
    | "sell"
    | "deposit"
    | "withdrawal"
    | "dividend"
    | "interest"
    | "fee"
    | "tax"
    | "fx_conversion"
    | "unknown";
}

export interface DividendPageOptions extends PageOptions {
  startDate?: string;
  endDate?: string;
}

export interface RefreshOptions {
  idempotencyKey: string;
  scope?: "all" | "current" | "history";
  mode?: "incremental" | "full";
  createSnapshot?: true;
  create_snapshot?: true;
}

export class PortfolioApiClient {
  readonly #baseUrl: string;
  readonly #fetch: typeof fetch;
  readonly #headers: () => HeadersInit;
  #csrfToken: string | null = null;

  constructor(options: PortfolioApiClientOptions = {}) {
    this.#baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
    this.#fetch = options.fetchImpl ?? options.fetch ?? fetch;
    this.#headers = options.headers ?? (() => ({}));
  }

  async createLocalSession(): Promise<LocalSession> {
    const session = await this.#request(
      "/api/v1/auth/local-session",
      localSessionSchema,
      { method: "POST" },
    );
    this.#csrfToken = session.csrf_token;
    return session;
  }

  async logout(): Promise<void> {
    await this.#requestNoContent("/api/v1/auth/logout", {
      method: "POST",
      headers: this.#csrfHeaders(),
    });
    this.#csrfToken = null;
  }

  me(): Promise<Principal> {
    return this.#request("/api/v1/me", principalSchema);
  }

  listConnections(): Promise<BrokerConnection[]> {
    return this.#request(
      "/api/v1/broker-connections",
      z.array(brokerConnectionSchema),
    );
  }

  listAccounts(): Promise<Account[]> {
    return this.#request("/api/v1/accounts", z.array(accountSchema));
  }

  getAccount(accountId: string): Promise<Account> {
    return this.#request(this.#accountPath(accountId), accountSchema);
  }

  getSummary(accountId: string): Promise<AccountSummary> {
    return this.#request(
      `${this.#accountPath(accountId)}/summary`,
      accountSummarySchema,
    );
  }

  listPositions(
    accountId: string,
    options: PositionPageOptions = {},
  ): Promise<Page<Position>> {
    const parameters = this.#pageParameters(options);
    if (options.sort) parameters.set("sort", options.sort);
    if (options.search) parameters.set("search", options.search);
    return this.#request(
      `${this.#accountPath(accountId)}/positions${this.#query(parameters)}`,
      pageSchema(positionSchema),
    );
  }

  getPosition(accountId: string, positionId: string): Promise<Position> {
    return this.#request(
      `${this.#accountPath(accountId)}/positions/${encodeURIComponent(positionId)}`,
      positionSchema,
    );
  }

  listTransactions(
    accountId: string,
    options: ActivityPageOptions = {},
  ): Promise<Page<Activity>> {
    const parameters = this.#pageParameters(options);
    if (options.startDate) parameters.set("start_date", options.startDate);
    if (options.endDate) parameters.set("end_date", options.endDate);
    if (options.activityType)
      parameters.set("activity_type", options.activityType);
    return this.#request(
      `${this.#accountPath(accountId)}/transactions${this.#query(parameters)}`,
      pageSchema(activitySchema),
    );
  }

  listDividends(
    accountId: string,
    options: DividendPageOptions = {},
  ): Promise<Page<Dividend>> {
    const parameters = this.#pageParameters(options);
    if (options.startDate) parameters.set("start_date", options.startDate);
    if (options.endDate) parameters.set("end_date", options.endDate);
    return this.#request(
      `${this.#accountPath(accountId)}/dividends${this.#query(parameters)}`,
      pageSchema(dividendSchema),
    );
  }

  listOrders(
    accountId: string,
    options: PageOptions = {},
  ): Promise<Page<Order>> {
    return this.#request(
      `${this.#accountPath(accountId)}/orders${this.#pageQuery(options)}`,
      pageSchema(orderSchema),
    );
  }

  getAllocation(
    accountId: string,
    options: { limit?: number } = {},
  ): Promise<DirectAllocation> {
    const parameters = new URLSearchParams();
    if (options.limit !== undefined)
      parameters.set("limit", String(options.limit));
    return this.#request(
      `${this.#accountPath(accountId)}/allocation${this.#query(parameters)}`,
      directAllocationSchema,
    );
  }

  getPerformance(accountId: string): Promise<PerformanceSummary> {
    return this.#request(
      `${this.#accountPath(accountId)}/performance/summary`,
      performanceSummarySchema,
    );
  }

  listSnapshots(
    accountId: string,
    options: PageOptions = {},
  ): Promise<Page<Snapshot>> {
    return this.#request(
      `${this.#accountPath(accountId)}/snapshots${this.#pageQuery(options)}`,
      pageSchema(snapshotSchema),
    );
  }

  getLatestSnapshot(accountId: string): Promise<SnapshotDetail> {
    return this.#request(
      `${this.#accountPath(accountId)}/snapshots/latest`,
      snapshotDetailSchema,
    );
  }

  getSnapshot(accountId: string, snapshotId: string): Promise<SnapshotDetail> {
    return this.#request(
      `${this.#accountPath(accountId)}/snapshots/${encodeURIComponent(snapshotId)}`,
      snapshotDetailSchema,
    );
  }

  compareSnapshots(
    accountId: string,
    startId: string,
    endId: string,
  ): Promise<SnapshotComparison> {
    const query = new URLSearchParams({ start_id: startId, end_id: endId });
    return this.#request(
      `${this.#accountPath(accountId)}/snapshots/compare?${query}`,
      snapshotComparisonSchema,
    );
  }

  getReconciliation(accountId: string): Promise<Reconciliation> {
    return this.#request(
      `${this.#accountPath(accountId)}/reconciliation`,
      reconciliationSchema,
    );
  }

  listReconciliationDiscrepancies(
    accountId: string,
    options: PageOptions = {},
  ): Promise<Page<ReconciliationIssue>> {
    return this.#request(
      `${this.#accountPath(accountId)}/reconciliation/discrepancies${this.#pageQuery(options)}`,
      pageSchema(reconciliationIssueSchema),
    );
  }

  getQuality(accountId: string): Promise<DataQualitySummary> {
    return this.#request(
      `${this.#accountPath(accountId)}/data-quality`,
      dataQualitySummarySchema,
    );
  }

  refresh(accountId: string, options: RefreshOptions): Promise<RefreshRun> {
    return this.#request(
      `${this.#accountPath(accountId)}/refresh`,
      refreshRunSchema,
      {
        method: "POST",
        headers: {
          ...this.#csrfHeaders(),
          "Content-Type": "application/json",
          "X-Idempotency-Key": options.idempotencyKey,
        },
        body: JSON.stringify({
          scope: options.scope ?? "all",
          mode: options.mode ?? "incremental",
          create_snapshot:
            options.createSnapshot ?? options.create_snapshot ?? true,
        }),
      },
    );
  }

  getRefreshRun(runId: string): Promise<RefreshRun> {
    return this.#request(
      `/api/v1/refresh-runs/${encodeURIComponent(runId)}`,
      refreshRunSchema,
    );
  }

  listInstruments(
    options: PageOptions & { query?: string } = {},
  ): Promise<Page<Instrument>> {
    const parameters = new URLSearchParams();
    if (options.query) parameters.set("query", options.query);
    if (options.cursor) parameters.set("cursor", options.cursor);
    if (options.limit !== undefined)
      parameters.set("limit", String(options.limit));
    const query = parameters.size > 0 ? `?${parameters}` : "";
    return this.#request(
      `/api/v1/instruments${query}`,
      pageSchema(instrumentSchema),
    );
  }

  getInstrument(instrumentId: string): Promise<Instrument> {
    return this.#request(
      `/api/v1/instruments/${encodeURIComponent(instrumentId)}`,
      instrumentSchema,
    );
  }

  #accountPath(accountId: string): string {
    return `/api/v1/accounts/${encodeURIComponent(accountId)}`;
  }

  #pageQuery(options: PageOptions): string {
    return this.#query(this.#pageParameters(options));
  }

  #pageParameters(options: PageOptions): URLSearchParams {
    const parameters = new URLSearchParams();
    if (options.cursor) parameters.set("cursor", options.cursor);
    if (options.limit !== undefined)
      parameters.set("limit", String(options.limit));
    return parameters;
  }

  #query(parameters: URLSearchParams): string {
    return parameters.size > 0 ? `?${parameters}` : "";
  }

  #csrfHeaders(): Record<string, string> {
    return this.#csrfToken === null ? {} : { "X-CSRF-Token": this.#csrfToken };
  }

  async #request<Output>(
    path: string,
    schema: z.ZodType<Output>,
    init: RequestInit = {},
  ): Promise<Output> {
    const response = await this.#fetch(`${this.#baseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...this.#headers(),
        ...init.headers,
      },
    });
    if (!response.ok) throw await this.#apiError(response);
    return schema.parse(await response.json());
  }

  async #requestNoContent(path: string, init: RequestInit): Promise<void> {
    const response = await this.#fetch(`${this.#baseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...this.#headers(),
        ...init.headers,
      },
    });
    if (!response.ok) throw await this.#apiError(response);
  }

  async #apiError(response: Response): Promise<PortfolioApiError> {
    let envelope: ErrorEnvelope | null = null;
    try {
      const parsed = errorEnvelopeSchema.safeParse(await response.json());
      envelope = parsed.success ? parsed.data : null;
    } catch {
      envelope = null;
    }
    return new PortfolioApiError(response.status, envelope);
  }
}
export * from "./targets.generated";
export { TargetApiError } from "./target-transport";
export type {
  TargetApiResponse,
  TargetClientOptions,
  TargetCommandOptions,
  TargetReadOptions,
} from "./target-transport";

export * from "./planning.generated";
export { PlanningApiError } from "./planning-transport";
export type {
  PlanningApiResponse,
  PlanningClientOptions,
  PlanningCommandOptions,
  PlanningReadOptions,
} from "./planning-transport";

export * from "./sources.generated";
export { SourceApiError } from "./source-transport";
export type {
  SourceApiResponse,
  SourceClientOptions,
  SourceCommandOptions,
  SourceReadOptions,
} from "./source-transport";

export * from "./historical.generated";
export { HistoricalApiError } from "./historical-transport";
export type {
  HistoricalApiResponse,
  HistoricalClientOptions,
  HistoricalReadOptions,
} from "./historical-transport";

export * from "./xray.generated";
export { XrayApiError } from "./xray-transport";
export type {
  XrayApiResponse,
  XrayClientOptions,
  XrayReadOptions,
} from "./xray-transport";

export * from "./reports.generated";
export { ReportApiError } from "./report-transport";
export type {
  ReportApiResponse,
  ReportClientOptions,
  ReportReadOptions,
  ReportCommandOptions,
  ReportGrantOptions,
  ReportDownloadOptions,
  ReportArtifactResponse,
} from "./report-transport";

export * from "./alerts.generated";
export { AlertApiError } from "./alert-transport";
export type {
  AlertApiResponse,
  AlertClientOptions,
  AlertReadOptions,
  AlertCommandOptions,
} from "./alert-transport";

export * from "./risk.generated";
export { RiskApiError } from "./risk-transport";
export type {
  RiskApiResponse,
  RiskClientOptions,
  RiskReadOptions,
  RiskCommandOptions,
} from "./risk-transport";
