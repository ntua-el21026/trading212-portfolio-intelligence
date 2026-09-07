/** Display a canonical planning amount without rounding or numeric conversion. */
export function formatPlanningMoney(value: string | null): string {
  if (value === null) return "Unavailable";
  const parts = /^(-?)(0|[1-9][0-9]{0,19})(?:\.([0-9]{1,18}))?$/.exec(value);
  if (!parts)
    throw new Error("Planning amount must be a canonical decimal string.");
  const whole = parts[2];
  // Omit insignificant trailing zeros, while retaining the usual two-place display.
  const fraction = (parts[3] ?? "").replace(/0+$/, "").padEnd(2, "0");
  const negative =
    parts[1] === "-" && (whole !== "0" || /[1-9]/.test(fraction));
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${grouped}.${fraction}`;
}
