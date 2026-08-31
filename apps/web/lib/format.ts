import Decimal from "decimal.js";

function groupedDecimal(value: string, fractionDigits: number): string {
  const fixed = new Decimal(value).toFixed(
    fractionDigits,
    Decimal.ROUND_HALF_EVEN,
  );
  const [signedWhole, fraction] = fixed.split(".");
  const negative = signedWhole.startsWith("-");
  const whole = negative ? signedWhole.slice(1) : signedWhole;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}${fraction ? `.${fraction}` : ""}`;
}

export function formatMoney(value: string | null, fractionDigits = 2): string {
  return value === null ? "Unavailable" : groupedDecimal(value, fractionDigits);
}

export function formatDecimal(
  value: string | null,
  fractionDigits = 3,
): string {
  return value === null ? "Unavailable" : groupedDecimal(value, fractionDigits);
}

export function formatPercent(value: string | null): string {
  if (value === null) {
    return "Unavailable";
  }
  return `${groupedDecimal(new Decimal(value).times(100).toString(), 1)}%`;
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(new Date(value));
}

export function formatDateTime(value: string): string {
  return `${new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
    minute: "2-digit",
    month: "short",
    timeZone: "UTC",
    year: "numeric",
  }).format(new Date(value))} UTC`;
}

export function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
