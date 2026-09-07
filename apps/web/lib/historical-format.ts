import Decimal from "decimal.js";

// Presentation only: preserve every canonical fractional digit, including tiny
// nonzero values. Percentage scaling changes notation, never the server result.
const DisplayDecimal = Decimal.clone({
  precision: 80,
  rounding: Decimal.ROUND_HALF_EVEN,
});

export function formatHistoricalDecimal(
  value: string | null,
  minimumDigits = 0,
): string {
  if (value === null) return "Unavailable";
  const decimal = new DisplayDecimal(value);
  const [whole, fraction] = decimal
    .toFixed(Math.max(minimumDigits, decimal.decimalPlaces()))
    .split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/gu, ",").replace(/^-/, "−")}${fraction ? `.${fraction}` : ""}`;
}

export function formatHistoricalPercent(value: string | null): string {
  return value === null
    ? "Unavailable"
    : `${formatHistoricalDecimal(new DisplayDecimal(value).times(100).toFixed(), 1)}%`;
}
