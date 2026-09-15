import "server-only";
import { ProjectionApiError } from "@trading212/api-contracts";
import {
  assertProjectionAccount,
  projectionClients,
  projectionData,
} from "./projection-adapter";
import type { ProjectionQuery } from "./projection-query";
type Clients = Awaited<ReturnType<typeof projectionClients>>;
function same(actual: string, expected: string) {
  if (actual !== expected)
    throw new ProjectionApiError(
      "CONFLICT",
      409,
      "The saved version does not belong to the selected definition.",
    );
}
export async function selectedProjectionGoal(
  clients: Clients,
  query: ProjectionQuery,
  account: string,
) {
  const api = clients.projections;
  const requested = query.goal_version
    ? projectionData(await api.get_goal_version(query.goal_version))
    : null;
  if (requested) {
    assertProjectionAccount(requested.account_id, account);
    same(requested.id, query.goal_version!);
  }
  const goalId = query.goal ?? requested?.goal_id;
  if (!goalId) return null;
  const goal = projectionData(await api.get_goal(goalId));
  assertProjectionAccount(goal.account_id, account);
  same(goal.id, goalId);
  if (requested) same(requested.goal_id, goal.id);
  const version =
    requested ??
    projectionData(await api.get_goal_version(goal.current_version_id));
  assertProjectionAccount(version.account_id, account);
  same(version.goal_id, goal.id);
  same(version.id, requested?.id ?? goal.current_version_id);
  return { goal, version };
}
export async function selectedProjectionAssumption(
  clients: Clients,
  query: ProjectionQuery,
  account: string,
  pinnedVersion?: string,
) {
  const api = clients.projections;
  if (pinnedVersion && query.version && pinnedVersion !== query.version)
    throw new ProjectionApiError(
      "CONFLICT",
      409,
      "The selected goal requires its exact immutable assumption version.",
    );
  const requestedId = pinnedVersion ?? query.version;
  const requested = requestedId
    ? projectionData(await api.get_assumption_version(requestedId))
    : null;
  if (requested) {
    assertProjectionAccount(requested.account_id, account);
    same(requested.id, requestedId!);
  }
  const setId = query.set ?? requested?.set_id;
  if (!setId) return null;
  const definition = projectionData(await api.get_assumption_set(setId));
  assertProjectionAccount(definition.account_id, account);
  same(definition.id, setId);
  if (requested) same(requested.set_id, definition.id);
  const version =
    requested ??
    projectionData(
      await api.get_assumption_version(definition.current_version_id),
    );
  assertProjectionAccount(version.account_id, account);
  same(version.set_id, definition.id);
  same(version.id, requested?.id ?? definition.current_version_id);
  return { definition, version };
}
