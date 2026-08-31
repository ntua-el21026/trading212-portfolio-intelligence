import type { ReactNode } from "react";

import { AppShell } from "../../components/app-shell";
import { loadPortfolioBundle } from "../../lib/api-adapter";
import { requireWebAccess } from "../../lib/auth";

export const dynamic = "force-dynamic";

export default async function PortfolioLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const access = await requireWebAccess();
  const bundle = await loadPortfolioBundle();
  return (
    <AppShell access={access} summary={bundle.summary}>
      {children}
    </AppShell>
  );
}
