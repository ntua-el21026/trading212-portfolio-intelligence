import {
  AlertTriangle,
  CalendarClock,
  Calculator,
  CheckCircle2,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";

import { Notice } from "@trading212/ui";

import type {
  MetricResponse,
  QualityResponse,
  ReconciliationResponse,
} from "../lib/contracts";
import { formatDateTime, titleCase } from "../lib/format";
import { QualityStatus } from "./financial";

export function QualityBanner({
  quality,
}: Readonly<{ quality: QualityResponse }>) {
  if (quality.state === "fresh" && quality.warnings.length === 0) {
    return null;
  }
  const isFailure =
    quality.state === "failed" || quality.state === "unreconciled";
  return (
    <Notice
      title={`${titleCase(quality.state)} portfolio data`}
      tone={isFailure ? "danger" : "warning"}
    >
      <p>
        {quality.warnings[0] ??
          "Some portfolio inputs do not meet the current quality policy. Review details before relying on affected values."}
      </p>
      {quality.missing_inputs.length > 0 ? (
        <p>Missing inputs: {quality.missing_inputs.join(", ")}</p>
      ) : null}
    </Notice>
  );
}

export function TrustRail({
  metric,
  quality,
  reconciliation,
}: Readonly<{
  metric: MetricResponse;
  quality: QualityResponse;
  reconciliation: ReconciliationResponse;
}>) {
  const reconciled = reconciliation.status === "reconciled";
  return (
    <aside className="trust-rail" aria-label="Portfolio trust details">
      <section className="trust-item">
        {reconciled ? (
          <CheckCircle2
            aria-hidden="true"
            className="trust-icon trust-icon--positive"
          />
        ) : (
          <AlertTriangle
            aria-hidden="true"
            className="trust-icon trust-icon--warning"
          />
        )}
        <div>
          <span>Reconciliation status</span>
          <strong>{titleCase(reconciliation.status)}</strong>
          <p>
            {reconciled
              ? "All covered positions and cash are accounted for."
              : `${reconciliation.issues.length} open discrepancy record${reconciliation.issues.length === 1 ? "" : "s"}.`}
          </p>
        </div>
      </section>
      <section className="trust-item">
        <ShieldCheck
          aria-hidden="true"
          className="trust-icon trust-icon--positive"
        />
        <div>
          <span>Data quality</span>
          <QualityStatus quality={quality} />
          <p>{quality.warnings[0] ?? "No data-quality warnings."}</p>
        </div>
      </section>
      <section className="trust-item">
        <CalendarClock aria-hidden="true" className="trust-icon" />
        <div>
          <span>Source cutoff</span>
          <strong>{formatDateTime(quality.source_timestamp)}</strong>
          <p>
            Freshness threshold: {quality.freshness_threshold_seconds} seconds.
          </p>
        </div>
      </section>
      <section className="trust-item">
        <Calculator aria-hidden="true" className="trust-icon" />
        <div>
          <span>Calculation</span>
          <strong>{metric.calculation_version}</strong>
          <p>{metric.methodology}</p>
        </div>
      </section>
      <section className="trust-item trust-item--boundary">
        <LockKeyhole aria-hidden="true" className="trust-icon" />
        <div>
          <span>Product boundary</span>
          <strong>Read-only</strong>
          <p>No orders, trades, or portfolio changes can be made here.</p>
        </div>
      </section>
    </aside>
  );
}

export function MethodologyDetails({
  metric,
  title = "Methodology and provenance",
}: Readonly<{ metric: MetricResponse; title?: string }>) {
  return (
    <details className="methodology-details">
      <summary>{title}</summary>
      <dl>
        <div>
          <dt>Calculation version</dt>
          <dd>{metric.calculation_version}</dd>
        </div>
        <div>
          <dt>Method</dt>
          <dd>{metric.methodology}</dd>
        </div>
        <div>
          <dt>Provenance</dt>
          <dd>{metric.provenance.join(", ")}</dd>
        </div>
        <div>
          <dt>Availability</dt>
          <dd>{titleCase(metric.availability)}</dd>
        </div>
        {metric.assumptions.length > 0 ? (
          <div>
            <dt>Assumptions</dt>
            <dd>{metric.assumptions.join(", ")}</dd>
          </div>
        ) : null}
      </dl>
    </details>
  );
}
