import type { ReactNode } from "react";

import { AppShell } from "../../components/app-shell";
import { loadAvailableAccounts } from "../../lib/api-adapter";
import { requireWebAccess } from "../../lib/auth";

export const dynamic = "force-dynamic";

export default async function PortfolioLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const access = await requireWebAccess();
  const accounts = await loadAvailableAccounts();
  const preferred = accounts.find(
    (account) => account.id === process.env.T212PI_ACCOUNT_ID?.trim(),
  )?.id;
  return (
    <AppShell
      access={{ displayName: access.displayName, isDemo: access.isDemo }}
      accounts={accounts}
      preferred={preferred}
    >
      {children}
    </AppShell>
  );
}
