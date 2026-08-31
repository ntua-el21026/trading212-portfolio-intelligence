import { CircleHelp } from "lucide-react";

import { StatusPill, type StatusTone } from "@trading212/ui";

import type { MetricResponse, QualityResponse } from "../lib/contracts";
import { formatMoney, titleCase } from "../lib/format";

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
        className={
          className ? `metric-unavailable ${className}` : "metric-unavailable"
        }
      >
        <CircleHelp aria-hidden="true" size={15} />
        Unavailable
      </span>
    );
  }
  return (
    <span className={className}>
      {formatMoney(metric.value)}
      {showCurrency ? <small> {metric.reporting_currency}</small> : null}
    </span>
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
      className={primary ? "metric-card metric-card--primary" : "metric-card"}
    >
      <span className="metric-card__label">{label}</span>
      <MoneyValue
        className="metric-card__value"
        metric={metric}
        showCurrency={primary}
      />
      {note ? <span className="metric-card__note">{note}</span> : null}
      {metric.value === null && metric.unavailable_reason ? (
        <span className="metric-card__note">{metric.unavailable_reason}</span>
      ) : null}
    </div>
  );
}
