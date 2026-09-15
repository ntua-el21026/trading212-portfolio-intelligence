import { describe, expect, it, vi } from "vitest";
import {
  account,
  id,
  other,
  assumption,
  definition,
  goal,
} from "./projection-fixtures";
import { readProjectionQuery } from "../lib/projection-query";
vi.mock("server-only", () => ({}));
import {
  selectedProjectionAssumption,
  selectedProjectionGoal,
} from "../lib/projection-selection";
import type { projectionClients } from "../lib/projection-adapter";
const response = <T>(data: T) => ({ data, notModified: false, etag: null });
function clients() {
  const api = {
    get_assumption_version: vi.fn().mockResolvedValue(response(assumption)),
    get_assumption_set: vi.fn().mockResolvedValue(response(definition)),
    get_goal_version: vi.fn().mockResolvedValue(response(goal)),
    get_goal: vi.fn().mockResolvedValue(response({ ...definition, id: other })),
  };
  return {
    api,
    value: { projections: api } as unknown as Awaited<
      ReturnType<typeof projectionClients>
    >,
  };
}
describe("saved projection selection authority", () => {
  it("loads the exact selected immutable version even when a newer head exists", async () => {
    const c = clients();
    c.api.get_assumption_set.mockResolvedValue(
      response({ ...definition, current_version_id: other, revision: 3 }),
    );
    const result = await selectedProjectionAssumption(
      c.value,
      readProjectionQuery({ account, set: id, version: id, view: "new" }),
      account,
    );
    expect(result?.version).toEqual(assumption);
    expect(c.api.get_assumption_version).toHaveBeenCalledOnce();
    expect(c.api.get_assumption_version).toHaveBeenCalledWith(id);
  });
  it("fails an explicit assumption/goal pin conflict before any private client call", async () => {
    const c = clients();
    await expect(
      selectedProjectionAssumption(
        c.value,
        readProjectionQuery({ account, version: other }),
        account,
        id,
      ),
    ).rejects.toMatchObject({ code: "CONFLICT" });
    expect(c.api.get_assumption_version).not.toHaveBeenCalled();
  });
  it("rejects version ownership before reading the aggregate or its current head", async () => {
    const c = clients();
    c.api.get_assumption_version.mockResolvedValue(
      response({ ...assumption, account_id: other }),
    );
    await expect(
      selectedProjectionAssumption(
        c.value,
        readProjectionQuery({ account, version: id }),
        account,
      ),
    ).rejects.toMatchObject({ code: "NOT_FOUND" });
    expect(c.api.get_assumption_set).not.toHaveBeenCalled();
  });
  it("rejects a goal version paired with a different aggregate", async () => {
    const c = clients();
    c.api.get_goal.mockResolvedValue(response(definition));
    await expect(
      selectedProjectionGoal(
        c.value,
        readProjectionQuery({ account, goal: id, goal_version: other }),
        account,
      ),
    ).rejects.toMatchObject({ code: "CONFLICT" });
  });
});
