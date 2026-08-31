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
  credential_state: z.enum(["configured", "not_configured"]),
  read_only: z.literal(true),
});

export const instrumentSchema = z.strictObject({
  id: z.string(),
  ticker: z.string(),
  name: z.string(),
  instrument_type: z.string(),
  trading_currency: z.string().regex(/^[A-Z]{3}$/),
});

export const returnMetricSchema = z.strictObject({
  value: decimalStringSchema.nullable(),
  availability: z.string(),
  calculation_version: z.string(),
  methodology: z.string(),
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
export type Snapshot = z.infer<typeof snapshotSchema>;
export type SnapshotComparison = z.infer<typeof snapshotComparisonSchema>;
export type Reconciliation = z.infer<typeof reconciliationSchema>;
export type RefreshRun = z.infer<typeof refreshRunSchema>;
export type BrokerConnection = z.infer<typeof brokerConnectionSchema>;
export type Instrument = z.infer<typeof instrumentSchema>;
export type PerformanceSummary = z.infer<typeof performanceSummarySchema>;
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
    options: PageOptions = {},
  ): Promise<Page<Position>> {
    return this.#request(
      `${this.#accountPath(accountId)}/positions${this.#pageQuery(options)}`,
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
    options: PageOptions = {},
  ): Promise<Page<Activity>> {
    return this.#request(
      `${this.#accountPath(accountId)}/transactions${this.#pageQuery(options)}`,
      pageSchema(activitySchema),
    );
  }

  listDividends(
    accountId: string,
    options: PageOptions = {},
  ): Promise<Page<Dividend>> {
    return this.#request(
      `${this.#accountPath(accountId)}/dividends${this.#pageQuery(options)}`,
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

  getAllocation(accountId: string): Promise<Allocation[]> {
    return this.#request(
      `${this.#accountPath(accountId)}/allocation`,
      z.array(allocationSchema),
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

  getLatestSnapshot(accountId: string): Promise<Snapshot> {
    return this.#request(
      `${this.#accountPath(accountId)}/snapshots/latest`,
      snapshotSchema,
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

  getQuality(accountId: string): Promise<Quality> {
    return this.#request(
      `${this.#accountPath(accountId)}/data-quality`,
      qualitySchema,
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
    const parameters = new URLSearchParams();
    if (options.cursor) parameters.set("cursor", options.cursor);
    if (options.limit !== undefined)
      parameters.set("limit", String(options.limit));
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
