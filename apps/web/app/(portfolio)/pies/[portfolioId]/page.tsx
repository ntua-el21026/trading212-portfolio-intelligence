import { AccountView } from "../../../../components/account-context";
import { loadSelectedAccount } from "../../../../lib/api-adapter";
import { resourceAccountHref } from "../../../../lib/account-selection";
import Link from "../../../../components/navigation-intent";
import { notFound, redirect } from "next/navigation";
import { z } from "zod";
import { TargetApiError } from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";

import { PageHeader } from "../../../../components/page-header";
import { CollectionPagination } from "../../../../components/collection-pagination";
import {
  PieMetadataForm,
  CreateVersionForm,
} from "../../../../components/target-forms";
import { TargetEditor } from "../../../../components/target-editor";
import {
  firstSearchParam,
  readOpaqueCursor,
} from "../../../../lib/collection-query";
import { targetClients, targetData } from "../../../../lib/target-adapter";

function uuid(value: string | undefined): string | undefined {
  const parsed = z.string().uuid().optional().safeParse(value);
  if (!parsed.success) notFound();
  return parsed.data;
}

async function targetRead<T>(operation: Promise<T>): Promise<T> {
  try {
    return await operation;
  } catch (error) {
    if (error instanceof TargetApiError && error.status === 404) notFound();
    throw error;
  }
}

export default async function PieDetailPage({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ portfolioId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}>) {
  const { portfolioId } = await params;
  if (!uuid(portfolioId)) notFound();
  const query = await searchParams;
  const requestedVersion = uuid(firstSearchParam(query.version));
  const cloneId = uuid(firstSearchParam(query.clone));
  const leftId = uuid(firstSearchParam(query.left));
  const rightId = uuid(firstSearchParam(query.right));
  const showActivity =
    firstSearchParam(query.activity) === "1" || Boolean(query.events_cursor);
  const { targets } = await targetClients();
  const accountSelection =
    query.account === "template"
      ? null
      : await loadSelectedAccount(query.account);
  if (
    query.account !== undefined &&
    query.account !== "template" &&
    !accountSelection?.account
  )
    notFound();
  const pieResponse = await targetRead(
    targets.get_virtual_portfolio(portfolioId),
  );
  const pie = targetData(pieResponse);
  if (query.account === undefined)
    redirect(resourceAccountHref(`/pies/${pie.id}`, pie.account_id, query));
  if (
    pie.account_id === null
      ? query.account !== "template"
      : pie.account_id !== accountSelection?.account?.id
  )
    notFound();
  const [versionsResponse, clone] = await targetRead(
    Promise.all([
      targets.list_target_versions(portfolioId, {
        state: "all",
        cursor: readOpaqueCursor(query.cursor),
        limit: 25,
      }),
      cloneId ? targets.get_target_version(cloneId).then(targetData) : null,
    ]),
  );
  const versions = targetData(versionsResponse);
  const selectedId =
    requestedVersion ?? pie.active_version_id ?? versions.items[0]?.id;
  const selectedResponse = selectedId
    ? await targetRead(targets.get_target_version(selectedId))
    : null;
  const version = selectedResponse ? targetData(selectedResponse) : null;
  if (version && version.portfolio_id !== pie.id) notFound();
  const comparisonVersions = [
    ...new Map(
      [...versions.items, ...(version ? [version] : [])].map((item) => [
        item.id,
        item,
      ]),
    ).values(),
  ].sort((left, right) => right.version_number - left.version_number);
  const [eventsResponse, comparisonResponse] = await targetRead(
    Promise.all([
      version && showActivity
        ? targets.list_target_version_events(version.id, {
            cursor: readOpaqueCursor(query.events_cursor),
            limit: 25,
          })
        : null,
      leftId && rightId
        ? targets.compare_target_versions(pie.id, {
            left_version_id: leftId,
            right_version_id: rightId,
          })
        : null,
    ]),
  );
  const events = eventsResponse ? targetData(eventsResponse) : null;
  const comparison = comparisonResponse ? targetData(comparisonResponse) : null;
  const pieEtag = pieResponse.etag;
  if (!pieEtag || (selectedResponse && !selectedResponse.etag))
    throw new Error("Target revision header is unavailable.");
  return (
    <AccountView accountId={pie.account_id}>
      <div className="page-stack">
        <PageHeader
          title={pie.name}
          description={`${pie.account_id ? "Account target" : "Private template"} · ${pie.reporting_currency} · ${pie.state}`}
          actions={
            <Link
              prefetch={false}
              className="text-link"
              href={`/pies?account=${pie.account_id ?? "template"}`}
            >
              All Pies
            </Link>
          }
        />
        {!pie.active_version_id ? (
          <Notice title="No active target">
            Publish a validated version, or wait for its scheduled effective
            time. Archived versions do not become active again.
          </Notice>
        ) : null}
        <Surface>
          <h2>Versions</h2>
          <div className="target-version-list">
            {versions.items.map((item) => (
              <Link
                prefetch={false}
                className="target-version-link"
                aria-current={item.id === version?.id ? "page" : undefined}
                key={item.id}
                href={`/pies/${pie.id}?account=${pie.account_id ?? "template"}&version=${item.id}`}
              >
                <strong>Version {item.version_number}</strong>
                <span>
                  {item.state} · effective {item.effective_at}
                </span>
              </Link>
            ))}
          </div>
          <CollectionPagination
            pathname={`/pies/${pie.id}`}
            nextCursor={versions.next_cursor}
            total={versions.total}
            returnedCount={versions.items.length}
            preservedQuery={{
              account: pie.account_id ?? "template",
              version: requestedVersion,
            }}
          />
          <details className="target-details" open={!version || Boolean(clone)}>
            <summary>Create a draft version</summary>
            <CreateVersionForm
              key={`${version?.id ?? "empty"}:${clone?.id ?? "none"}`}
              portfolio={pie}
              etag={pieEtag}
              version={version}
              clone={clone}
              defaultEffectiveAt={new Date().toISOString().slice(0, 16)}
            />
          </details>
          <PieMetadataForm
            key={`metadata:${pie.revision}`}
            portfolio={pie}
            etag={pieEtag}
          />
        </Surface>
        {version && selectedResponse?.etag ? (
          <TargetEditor
            key={`${version.id}:${version.revision}`}
            version={version}
            etag={selectedResponse.etag}
            instruments={[]}
            instrumentTotal={null}
            instrumentCursor={null}
          />
        ) : (
          <Surface>
            <h2>Start your target hierarchy</h2>
            <p>Create a draft version, then add groups, holdings, and cash.</p>
          </Surface>
        )}
        {version ? (
          <Surface>
            <h2>Compare versions</h2>
            <form className="target-form" method="get">
              <input
                name="account"
                type="hidden"
                value={pie.account_id ?? "template"}
              />
              <input name="version" type="hidden" value={version.id} />
              <label>
                Earlier version
                <select
                  name="left"
                  defaultValue={
                    leftId ??
                    comparisonVersions.find((item) => item.id !== version.id)
                      ?.id ??
                    version.id
                  }
                >
                  {comparisonVersions.map((item) => (
                    <option key={item.id} value={item.id}>
                      Version {item.version_number} · {item.state}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Later version
                <select name="right" defaultValue={rightId ?? version.id}>
                  {comparisonVersions.map((item) => (
                    <option key={item.id} value={item.id}>
                      Version {item.version_number} · {item.state}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit">Compare versions</button>
            </form>
            {comparison ? (
              <div
                className="target-comparison"
                aria-label="Version comparison"
              >
                <p>
                  Effective date: {comparison.left_effective_at} →{" "}
                  {comparison.right_effective_at}
                </p>
                {comparison.comparison.node_changes.length ? (
                  <ul>
                    {comparison.comparison.node_changes.map((change) => (
                      <li key={change.key}>
                        <strong>
                          {change.right?.name ?? change.left?.name}
                        </strong>
                        :{" "}
                        {change.left
                          ? change.right
                            ? change.changed_fields.join(", ")
                            : "removed"
                          : "added"}
                        {change.left?.weight !== change.right?.weight
                          ? ` · weight ${change.left?.weight ?? "absent"} → ${change.right?.weight ?? "absent"}`
                          : ""}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No target node changes.</p>
                )}
                <p>
                  {comparison.comparison.constraint_changes.length} constraint
                  changes · {comparison.comparison.exclusion_changes.length}{" "}
                  exclusion changes
                </p>
                {comparison.comparison.constraint_changes.map((change) => (
                  <p key={change.key}>
                    {change.right?.kind ?? change.left?.kind}:{" "}
                    {change.left
                      ? change.right
                        ? "changed"
                        : "removed"
                      : "added"}
                  </p>
                ))}
                {comparison.comparison.exclusion_changes.map((change) => (
                  <p key={change.key}>
                    Exclusion{" "}
                    {change.left
                      ? change.right
                        ? "changed"
                        : "removed"
                      : "added"}
                    : {change.right?.reason ?? change.left?.reason}
                  </p>
                ))}
              </div>
            ) : null}
          </Surface>
        ) : null}
        {events ? (
          <Surface id="version-activity">
            <h2>Version activity</h2>
            <ol className="target-event-list">
              {events.items.map((event) => (
                <li key={event.id}>
                  <strong>{event.kind.replaceAll("_", " ")}</strong>
                  <span>{event.occurred_at}</span>
                  {event.effective_at ? (
                    <span>Effective {event.effective_at}</span>
                  ) : null}
                </li>
              ))}
            </ol>
            <CollectionPagination
              pathname={`/pies/${pie.id}`}
              nextCursor={events.next_cursor}
              cursorParameter="events_cursor"
              total={events.total}
              returnedCount={events.items.length}
              preservedQuery={{
                account: pie.account_id ?? "template",
                version: version?.id,
                cursor: firstSearchParam(query.cursor),
                activity: "1",
              }}
            />
          </Surface>
        ) : version ? (
          <Surface id="version-activity">
            <h2>Version activity</h2>
            <p className="muted">
              Review the recorded edits, validation, publication, and lifecycle
              transitions for this version.
            </p>
            <Link
              prefetch={false}
              className="text-link"
              href={`/pies/${pie.id}?account=${pie.account_id ?? "template"}&version=${version.id}&activity=1#version-activity`}
            >
              View version activity
            </Link>
          </Surface>
        ) : null}
      </div>
    </AccountView>
  );
}
