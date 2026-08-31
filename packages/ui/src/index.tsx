import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

export type StatusTone = "positive" | "warning" | "danger" | "neutral" | "info";

function classes(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export interface SurfaceProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  compact?: boolean;
}

export function Surface({
  children,
  className,
  compact = false,
  ...props
}: Readonly<SurfaceProps>) {
  return (
    <section
      className={classes(
        "ui-surface",
        compact && "ui-surface--compact",
        className,
      )}
      {...props}
    >
      {children}
    </section>
  );
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "quiet" | "danger";
}

export function Button({
  children,
  className,
  type = "button",
  variant = "primary",
  ...props
}: Readonly<ButtonProps>) {
  return (
    <button
      className={classes("ui-button", `ui-button--${variant}`, className)}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
}

export function StatusPill({
  children,
  className,
  tone = "neutral",
}: Readonly<{
  children: ReactNode;
  className?: string;
  tone?: StatusTone;
}>) {
  return (
    <span className={classes("ui-status", `ui-status--${tone}`, className)}>
      <span aria-hidden="true" className="ui-status__dot" />
      {children}
    </span>
  );
}

export function Notice({
  children,
  className,
  title,
  tone = "info",
}: Readonly<{
  children: ReactNode;
  className?: string;
  title: string;
  tone?: StatusTone;
}>) {
  return (
    <aside
      className={classes("ui-notice", `ui-notice--${tone}`, className)}
      role={tone === "danger" ? "alert" : "status"}
    >
      <strong>{title}</strong>
      <div>{children}</div>
    </aside>
  );
}

export function EmptyState({
  action,
  description,
  icon,
  title,
}: Readonly<{
  action?: ReactNode;
  description: string;
  icon?: ReactNode;
  title: string;
}>) {
  return (
    <div className="ui-empty-state">
      {icon ? <span className="ui-empty-state__icon">{icon}</span> : null}
      <h2>{title}</h2>
      <p>{description}</p>
      {action ? <div className="ui-empty-state__action">{action}</div> : null}
    </div>
  );
}

export function Skeleton({
  className,
  height = "1rem",
  width = "100%",
}: Readonly<{ className?: string; height?: string; width?: string }>) {
  return (
    <span
      aria-hidden="true"
      className={classes("ui-skeleton", className)}
      style={{ height, width }}
    />
  );
}

export function VisuallyHidden({
  children,
}: Readonly<{ children: ReactNode }>) {
  return <span className="ui-visually-hidden">{children}</span>;
}

// Compatibility alias for consumers of the initial workspace shell.
export const Panel = Surface;
