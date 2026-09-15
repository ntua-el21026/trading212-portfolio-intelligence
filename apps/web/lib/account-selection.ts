import type { Account } from "@trading212/api-contracts";
import { z } from "zod";

export type AccountParameter = string | string[] | undefined;
export type AccountSelection =
  | { kind: "selected"; account: Account }
  | { kind: "empty" | "choose" | "invalid"; account: null };

export const accountIdSchema = z.string().uuid();

/** Explicit URL selection never falls back to another authorized account. */
export function resolveAccountSelection(
  accounts: readonly Account[],
  requested: AccountParameter,
  preferred?: string,
): AccountSelection {
  if (requested !== undefined) {
    const parsed = accountIdSchema.safeParse(requested);
    if (!parsed.success) return { kind: "invalid", account: null };
    const account = accounts.find((item) => item.id === parsed.data);
    return account
      ? { kind: "selected", account }
      : { kind: "invalid", account: null };
  }
  const configured = accounts.find((item) => item.id === preferred?.trim());
  if (configured) return { kind: "selected", account: configured };
  if (accounts.length === 1) return { kind: "selected", account: accounts[0] };
  return { kind: accounts.length ? "choose" : "empty", account: null };
}

export function accountParameter(
  query: Pick<URLSearchParams, "getAll">,
): AccountParameter {
  const values = query.getAll("account");
  return values.length === 0
    ? undefined
    : values.length === 1
      ? values[0]
      : values;
}

export function accountHref(
  pathname: string,
  accountId: string | null,
): string {
  return accountId
    ? `${pathname}?${new URLSearchParams({ account: accountId })}`
    : pathname;
}

/** Only account-independent dates survive an account switch. Owned pins and cursors do not. */
export function accountSwitchHref(
  pathname: string,
  query: Pick<URLSearchParams, "getAll">,
  accountId: string,
): string {
  const section = pathname.split("/")[1];
  const destination = new Set([
    "holdings",
    "pies",
    "planner",
    "sources",
    "xray",
  ]).has(section)
    ? `/${section}`
    : pathname;
  const next = new URLSearchParams({ account: accountId });
  if (
    destination === "/reports/premium" &&
    query.getAll("profile").length === 1 &&
    query.getAll("profile")[0] === "report_sections_v3"
  ) {
    next.set("profile", "report_sections_v3");
    const families = query.getAll("family");
    if (families.length === 1 && ["risk", "scenario"].includes(families[0]))
      next.set("family", families[0]);
  }
  const dateKeys = ["/performance", "/income", "/risk"].includes(destination)
    ? ["start", "end"]
    : ["start_date", "end_date"];
  for (const key of dateKeys) {
    const values = query.getAll(key);
    if (values.length !== 1 || !/^\d{4}-\d{2}-\d{2}$/.test(values[0])) continue;
    const date = new Date(`${values[0]}T00:00:00Z`);
    if (
      !Number.isNaN(date.valueOf()) &&
      date.toISOString().slice(0, 10) === values[0]
    ) {
      next.set(key, values[0]);
    }
  }
  return `${destination}?${next}`;
}

/** Preserve bounded page selection while making a resource's authorized account explicit. */
export function resourceAccountHref(
  pathname: string,
  accountId: string | null,
  query: Readonly<Record<string, AccountParameter>>,
): string {
  const parameters = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (key === "account" || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value])
      parameters.append(key, item);
  }
  parameters.set("account", accountId ?? "template");
  return `${pathname}?${parameters}`;
}

/** Private templates remain reachable without a broker account; explicit invalid accounts never fall back. */
export function isPrivateTemplateSelection(
  pathname: string,
  requested: AccountParameter,
  accountCount: number,
  hasTemplateReference = false,
): boolean {
  if (pathname !== "/pies" && !pathname.startsWith("/pies/")) return false;
  return (
    requested === "template" ||
    (pathname === "/pies" &&
      requested === undefined &&
      (accountCount === 0 || hasTemplateReference))
  );
}
