import Link from "./navigation-intent";
import { Surface } from "@trading212/ui";

import {
  planningHref,
  type PlanningSelection,
} from "../lib/planning-selection";
import { formatDateTime } from "../lib/format";

export function PlanningSelectionForms({
  data,
  pathname,
}: Readonly<{
  data: PlanningSelection;
  pathname: "/drift" | "/planner" | `/planner/${string}`;
}>) {
  const { accounts, account, selection } = data;
  const fixedScope = pathname.startsWith("/planner/");
  const pins = {
    account: account?.id,
    pie: selection?.pie?.id,
    version: selection?.version?.id,
    snapshot: selection?.snapshot?.id,
    edit: pathname.startsWith("/planner/") ? "1" : undefined,
  };
  const pies = [
    ...new Map(
      [
        ...(selection?.pies?.items ?? []),
        ...(selection?.pie ? [selection.pie] : []),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  const versions = [
    ...new Map(
      [
        ...(selection?.versions?.items ?? []),
        ...(selection?.version ? [selection.version] : []),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  const snapshots = [
    ...new Map(
      [
        ...(selection?.snapshots?.items ?? []),
        ...(selection?.snapshot ? [selection.snapshot] : []),
      ].map((item) => [item.id, item]),
    ).values(),
  ];
  if (selection && !selection.browse)
    return (
      <Surface>
        <h2>Selected sources</h2>
        <p>
          {account?.display_name} · {selection.pie?.name} · target version{" "}
          {selection.version?.version_number}
        </p>
        <p className="muted">
          {selection.snapshot
            ? formatDateTime(selection.snapshot.valuation_at)
            : "Snapshot unavailable"}{" "}
          · {selection.version?.reporting_currency}
        </p>
        <Link
          prefetch={false}
          className="text-link"
          href={planningHref(pathname, { ...pins, choose: "1" })}
        >
          Change source selections
        </Link>
      </Surface>
    );
  return (
    <Surface>
      <h2>Choose your comparison</h2>
      <div className="planning-selectors">
        {!fixedScope ? (
          <form method="get" action={pathname} className="target-form">
            {pathname.startsWith("/planner/") ? (
              <input type="hidden" name="edit" value="1" />
            ) : null}
            <label>
              <span>Account</span>
              <select name="account" defaultValue={account?.id} required>
                {accounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit">Choose account</button>
          </form>
        ) : (
          <p>
            {account?.display_name} · {selection?.pie?.name}. Revisions retain
            this account and Pie.
          </p>
        )}
        {account && selection ? (
          <>
            {!fixedScope ? (
              <form method="get" action={pathname} className="target-form">
                {pathname.startsWith("/planner/") ? (
                  <input type="hidden" name="edit" value="1" />
                ) : null}
                <input type="hidden" name="account" value={account.id} />
                <label>
                  <span>Virtual Pie</span>
                  <select name="pie" defaultValue={selection.pie?.id} required>
                    {pies.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="submit" disabled={!pies.length}>
                  Choose Pie
                </button>
                {selection.pies?.next_cursor ? (
                  <Link
                    prefetch={false}
                    href={planningHref(pathname, {
                      account: account.id,
                      edit: pins.edit,
                      pies_cursor: selection.pies.next_cursor,
                    })}
                  >
                    More Pies
                  </Link>
                ) : null}
              </form>
            ) : null}
            {selection.pie ? (
              <form method="get" action={pathname} className="target-form">
                {pathname.startsWith("/planner/") ? (
                  <input type="hidden" name="edit" value="1" />
                ) : null}
                <input type="hidden" name="account" value={account.id} />
                <input type="hidden" name="pie" value={selection.pie.id} />
                <label>
                  <span>Published target version</span>
                  <select
                    name="version"
                    defaultValue={selection.version?.id}
                    required
                  >
                    {versions.map((item) => (
                      <option
                        key={item.id}
                        value={item.id}
                        disabled={!item.published_at}
                      >
                        Version {item.version_number} · {item.state}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Portfolio snapshot</span>
                  <select
                    name="snapshot"
                    defaultValue={selection.snapshot?.id}
                    required
                  >
                    {snapshots.map((item) => (
                      <option key={item.id} value={item.id}>
                        {formatDateTime(item.valuation_at)} ·{" "}
                        {item.reporting_currency}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="submit"
                  disabled={
                    !snapshots.length ||
                    !versions.some((item) => item.published_at)
                  }
                >
                  Compare selection
                </button>
                <div className="target-actions target-form__wide">
                  {selection.versions?.next_cursor ? (
                    <Link
                      prefetch={false}
                      href={planningHref(pathname, {
                        ...pins,
                        versions_cursor: selection.versions.next_cursor,
                      })}
                    >
                      Older target versions
                    </Link>
                  ) : null}
                  {selection.snapshots?.next_cursor ? (
                    <Link
                      prefetch={false}
                      href={planningHref(pathname, {
                        ...pins,
                        snapshots_cursor: selection.snapshots.next_cursor,
                      })}
                    >
                      Older snapshots
                    </Link>
                  ) : null}
                </div>
              </form>
            ) : null}
          </>
        ) : null}
      </div>
    </Surface>
  );
}
