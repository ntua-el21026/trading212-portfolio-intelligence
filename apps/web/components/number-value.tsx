import { formatHistoricalDecimal } from "../lib/historical-format";
import styles from "./number-value.module.css";

// Decimal formatting changes notation only. The original server string remains
// the full value for assistive technology, selection and the native tooltip.
export function NumberValue({
  value,
  unit,
  showUnit = true,
  minimumDigits = 2,
  className,
}: Readonly<{
  value: string;
  unit?: string;
  showUnit?: boolean;
  minimumDigits?: number;
  className?: string;
}>) {
  const fullValue = unit ? `${value} ${unit}` : value;
  return (
    <span
      className={`${styles.number} ${className ?? ""}`.trim()}
      title={fullValue}
      data-canonical-value={value}
    >
      <span aria-hidden="true">
        <span className={styles.formatted}>
          {formatHistoricalDecimal(value, minimumDigits)}
        </span>
        {showUnit && unit ? (
          <small className={styles.unit}> {unit}</small>
        ) : null}
      </span>
      <span className="ui-visually-hidden">{fullValue}</span>
    </span>
  );
}
