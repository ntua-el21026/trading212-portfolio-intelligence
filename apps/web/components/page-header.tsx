import type { ReactNode } from "react";

export function PageHeader({
  actions,
  description,
  title,
}: Readonly<{
  actions?: ReactNode;
  description: string;
  title: string;
}>) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}
