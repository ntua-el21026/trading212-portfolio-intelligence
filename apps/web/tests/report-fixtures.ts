import type {
  Metric,
  ReportJobStatus,
  Snapshot,
} from "@trading212/api-contracts";
export const accountId = "10000000-0000-4000-8000-000000000001";
export const snapshotId = "10000000-0000-4000-8000-000000000002";
export const jobId = "10000000-0000-4000-8000-000000000003";
export const at = "2026-09-07T12:00:00Z";
const unavailable: Metric = {
  value: null,
  reporting_currency: "EUR",
  availability: "unavailable",
  calculation_version: "synthetic",
  methodology: "presentation_test",
  provenance: [],
  assumptions: [],
  unavailable_reason: "Not part of this presentation test",
};
export const snapshot: Snapshot = {
  id: snapshotId,
  valuation_at: at,
  source_cutoff_at: at,
  reporting_currency: "EUR",
  total_value: unavailable,
  cash_value: unavailable,
  invested_value: unavailable,
  net_contributions: unavailable,
  data_quality: {
    state: "partial",
    as_of: at,
    source_timestamp: at,
    freshness_threshold_seconds: 0,
    warnings: [],
    missing_inputs: ["presentation_only"],
  },
};
export const job: ReportJobStatus = {
  account_id: accountId,
  job_id: jobId,
  report_id: null,
  state: "queued",
  requested_at: at,
  completed_at: null,
  expires_at: "2026-09-14T12:00:00Z",
  report_type: "portfolio_summary",
  formats: ["json"],
  failure_code: null,
  manifest_digest: null,
  artifacts: [],
  context: {
    snapshot_id: snapshotId,
    valuation_at: at,
    source_cutoff_at: at,
    reporting_currency: "EUR",
    input_digest: "a".repeat(64),
    document_digest: "b".repeat(64),
    profile_version: "report_sections_v1",
    schema_version: "1.0.0",
    pins: [
      {
        family: "snapshot",
        role: "snapshot",
        subject_id: snapshotId,
        content_digest: "c".repeat(64),
        parent_id: null,
        method_key: null,
        method_version: null,
      },
    ],
    quality: {
      state: "partial",
      availability: "partial",
      evaluated_at: at,
      warnings: [
        {
          key: "warning:one",
          family: "snapshot",
          kind: "warning",
          code: "synthetic_gap",
          text: "Synthetic source coverage is partial.",
          related_provenance_set_key: null,
        },
      ],
      warning_count: 3,
      warning_omitted_count: 2,
    },
  },
};
