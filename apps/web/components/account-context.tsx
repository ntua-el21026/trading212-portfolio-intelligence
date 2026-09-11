"use client";

import { useNavigationVersionRef } from "./navigation-intent";

import type { Account } from "@trading212/api-contracts";
import { Notice } from "@trading212/ui";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  createContext,
  useContext,
  useState,
  useSyncExternalStore,
  useTransition,
  type ReactNode,
} from "react";

import {
  accountParameter,
  accountSwitchHref,
  isPrivateTemplateSelection,
  resolveAccountSelection,
  type AccountSelection,
} from "../lib/account-selection";
import styles from "./account-context.module.css";

interface AccountContextValue {
  accounts: readonly Account[];
  selection: AccountSelection;
  templateScope: boolean;
  switchAccount: (accountId: string) => void;
}

const AccountContext = createContext<AccountContextValue | null>(null);
const subscribeHydration = () => () => {};
const hydratedClient = () => true;
const hydratedServer = () => false;

export function AccountProvider({
  accounts,
  preferred,
  children,
}: Readonly<{
  accounts: readonly Account[];
  preferred?: string;
  children: ReactNode;
}>) {
  const query = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const navigationRef = useNavigationVersionRef();
  const [pending, startTransition] = useTransition();
  const [intent, setIntent] = useState<string | null>(null);
  const requested = pending && intent ? intent : accountParameter(query);
  // Pending selection masks the prior view and permits a second account choice
  // before the first server response arrives. Browser history remains authoritative.
  const templateScope = isPrivateTemplateSelection(
    pathname,
    requested,
    accounts.length,
    query.has("template"),
  );
  const selection: AccountSelection = templateScope
    ? { kind: "choose", account: null }
    : resolveAccountSelection(accounts, requested, preferred);
  function switchAccount(accountId: string) {
    if (!accounts.some((account) => account.id === accountId)) return;
    navigationRef.current += 1;
    setIntent(accountId);
    startTransition(() =>
      router.push(accountSwitchHref(pathname, query, accountId)),
    );
  }
  return (
    <AccountContext.Provider
      value={{ accounts, selection, templateScope, switchAccount }}
    >
      {children}
    </AccountContext.Provider>
  );
}

export function useAccountSelection() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("Portfolio account context is unavailable.");
  return value;
}

export function AccountSelect({
  label = "Portfolio account",
  name,
}: Readonly<{ label?: string; name?: string }>) {
  const { accounts, selection, templateScope, switchAccount } =
    useAccountSelection();
  // Server HTML must not accept a selection before its change handler is ready.
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    hydratedClient,
    hydratedServer,
  );
  return (
    <select
      aria-label={label}
      name={name}
      disabled={!accounts.length || !hydrated}
      value={selection.account?.id ?? ""}
      onChange={(event) => switchAccount(event.target.value)}
    >
      <option value="" disabled>
        {templateScope
          ? "Private templates"
          : selection.kind === "empty"
            ? "No authorized accounts"
            : selection.kind === "invalid"
              ? "Account unavailable"
              : "Choose an account"}
      </option>
      {accounts.map((account) => (
        <option key={account.id} value={account.id}>
          {account.display_name}
        </option>
      ))}
    </select>
  );
}

export function AccountSelector({
  mobile = false,
}: Readonly<{ mobile?: boolean }>) {
  return (
    <label className={mobile ? styles.mobileSelector : styles.selector}>
      <span className="ui-visually-hidden">Portfolio account</span>
      <AccountSelect />
    </label>
  );
}

export function AccountRequired({
  selection,
}: Readonly<{ selection: AccountSelection }>) {
  const description =
    selection.kind === "empty"
      ? "No portfolio account is available for this session."
      : selection.kind === "invalid"
        ? "The requested account is invalid or unavailable for this session. Choose an authorized account to continue."
        : "Choose a portfolio account to view its data.";
  return (
    <section className="page-stack">
      <h1>Portfolio account</h1>
      <Notice
        title={
          selection.kind === "invalid"
            ? "Account unavailable"
            : "Choose a portfolio"
        }
      >
        {description}
      </Notice>
    </section>
  );
}

/** Never display a retained server subtree under a different account heading. */
export function AccountView({
  accountId,
  children,
}: Readonly<{ accountId: string | null; children: ReactNode }>) {
  const { selection, templateScope } = useAccountSelection();
  if (
    accountId === null ? !templateScope : selection.account?.id !== accountId
  ) {
    return <div role="status">Loading the selected portfolio…</div>;
  }
  return (
    <div
      key={accountId ?? "template"}
      data-portfolio-account={accountId ?? "template"}
    >
      {children}
    </div>
  );
}
