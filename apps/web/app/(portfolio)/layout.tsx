import type { ReactNode } from "react";

import { AppShell } from "../../components/app-shell";
import { loadPortfolioContext } from "../../lib/api-adapter";
import { requireWebAccess } from "../../lib/auth";

export const dynamic = "force-dynamic";

export default async function PortfolioLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const access = await requireWebAccess();
  const context = await loadPortfolioContext();
  return (
    <AppShell access={access} summary={context.summary}>
      {children}
    </AppShell>
  );
}
