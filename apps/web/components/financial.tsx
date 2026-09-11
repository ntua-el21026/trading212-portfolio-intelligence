import { CircleHelp } from "lucide-react";

import { StatusPill, type StatusTone } from "@trading212/ui";

import type { MetricResponse, QualityResponse } from "../lib/contracts";
import { titleCase } from "../lib/format";
import { NumberValue } from "./number-value";
import styles from "./number-value.module.css";

const qualityTone: Record<QualityResponse["state"], StatusTone> = {
  estimated: "warning",
  failed: "danger",
  fresh: "positive",
  partial: "warning",
  stale: "warning",
  unreconciled: "danger",
};

export function QualityStatus({
  quality,
}: Readonly<{ quality: QualityResponse }>) {
  return (
    <StatusPill tone={qualityTone[quality.state]}>
      {titleCase(quality.state)}
    </StatusPill>
  );
}

export function MoneyValue({
  className,
  metric,
  showCurrency = false,
}: Readonly<{
  className?: string;
  metric: MetricResponse;
  showCurrency?: boolean;
}>) {
  if (metric.value === null) {
    return (
      <span
        className={`metric-unavailable ${styles.number} ${className ?? ""}`.trim()}
        title={`Unavailable ${metric.reporting_currency}`}
      >
        <CircleHelp aria-hidden="true" size={15} />
        Unavailable
        {showCurrency ? <small> {metric.reporting_currency}</small> : null}
      </span>
    );
  }
  return (
    <NumberValue
      className={className}
      value={metric.value}
      unit={metric.reporting_currency}
      showUnit={showCurrency}
    />
  );
}

export function MetricCard({
  label,
  metric,
  note,
  primary = false,
}: Readonly<{
  label: string;
  metric: MetricResponse;
  note?: string;
  primary?: boolean;
}>) {
  return (
    <div
      className={`metric-card ${primary ? "metric-card--primary " : ""}${styles.card}`}
    >
      <span className="metric-card__label">{label}</span>
      <MoneyValue className="metric-card__value" metric={metric} showCurrency />
      {note ? <span className="metric-card__note">{note}</span> : null}
      {metric.availability === "partial" ? (
        <span className="metric-card__note">Partial value</span>
      ) : null}
      {metric.unavailable_reason ? (
        <span className="metric-card__note">{metric.unavailable_reason}</span>
      ) : null}
    </div>
  );
}
