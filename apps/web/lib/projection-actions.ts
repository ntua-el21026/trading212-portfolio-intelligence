"use server";
import {
  CreateAssumptionSetRequestSchema,
  CreateAssumptionVersionRequestSchema,
  CreateGoalRequestSchema,
  CreateGoalVersionRequestSchema,
  CreateProjectionRunRequestSchema,
  ProjectionApiError,
  type AssumptionSetResponse,
  type AssumptionVersionResponse,
  type GoalResponse,
  type GoalVersionResponse,
  type ProjectionOperationalRunResponse,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  assertProjectionAccount,
  projectionClients,
  projectionData,
  projectionResult,
} from "./projection-adapter";
const id = z.string().uuid();
const base = {
  account_id: id,
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
};
const revision = z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]{0,2}"$/);
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    ...base,
    kind: z.literal("create_set"),
    body: CreateAssumptionSetRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_assumption_version"),
    set_id: id,
    if_match: revision,
    body: CreateAssumptionVersionRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_goal"),
    body: CreateGoalRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_goal_version"),
    goal_id: id,
    if_match: revision,
    body: CreateGoalVersionRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_run"),
    body: CreateProjectionRunRequestSchema,
  }),
  z.strictObject({ ...base, kind: z.literal("cancel_run"), run_id: id }),
]);
export type ProjectionActionCommand = z.input<typeof commandSchema>;
export type ProjectionActionResult =
  | { ok: true; kind: "set"; value: AssumptionSetResponse }
  | { ok: true; kind: "assumption_version"; value: AssumptionVersionResponse }
  | { ok: true; kind: "goal"; value: GoalResponse }
  | { ok: true; kind: "goal_version"; value: GoalVersionResponse }
  | { ok: true; kind: "run"; value: ProjectionOperationalRunResponse }
  | { ok: false; code: string; message: string };
export async function submitProjectionCommand(
  input: unknown,
): Promise<ProjectionActionResult> {
  // Every action verifies the current session, origin and CSRF before parsing input.
  const clients = await projectionClients(true);
  try {
    const raw = JSON.stringify(input);
    if (raw === undefined || new TextEncoder().encode(raw).byteLength > 65536)
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The projection request exceeds 64 KiB.",
      };
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Review the exact amounts, dates, assumptions and saved selections.",
      };
    const command = parsed.data;
    const options = { idempotencyKey: command.idempotency_key };
    const outcome = await projectionResult(
      async (): Promise<ProjectionActionResult> => {
        const api = clients.projections;
        let result: ProjectionActionResult;
        if (command.kind === "create_set")
          result = {
            ok: true,
            kind: "set",
            value: projectionData(
              await api.create_assumption_set(
                command.account_id,
                command.body,
                options,
              ),
            ),
          };
        else if (command.kind === "create_assumption_version") {
          assertProjectionAccount(
            projectionData(await api.get_assumption_set(command.set_id))
              .account_id,
            command.account_id,
          );
          result = {
            ok: true,
            kind: "assumption_version",
            value: projectionData(
              await api.create_assumption_version(
                command.set_id,
                command.body,
                { ...options, ifMatch: command.if_match },
              ),
            ),
          };
        } else if (
          command.kind === "create_goal" ||
          command.kind === "create_goal_version"
        ) {
          assertProjectionAccount(
            projectionData(
              await api.get_assumption_version(
                command.body.content.assumption_version_id,
              ),
            ).account_id,
            command.account_id,
          );
          if (command.kind === "create_goal")
            result = {
              ok: true,
              kind: "goal",
              value: projectionData(
                await api.create_goal(
                  command.account_id,
                  command.body,
                  options,
                ),
              ),
            };
          else {
            assertProjectionAccount(
              projectionData(await api.get_goal(command.goal_id)).account_id,
              command.account_id,
            );
            result = {
              ok: true,
              kind: "goal_version",
              value: projectionData(
                await api.create_goal_version(command.goal_id, command.body, {
                  ...options,
                  ifMatch: command.if_match,
                }),
              ),
            };
          }
        } else if (command.kind === "create_run") {
          assertProjectionAccount(
            projectionData(
              await api.get_assumption_version(
                command.body.assumption_version_id,
              ),
            ).account_id,
            command.account_id,
          );
          if (command.body.goal_version_id) {
            const goal = projectionData(
              await api.get_goal_version(command.body.goal_version_id),
            );
            assertProjectionAccount(goal.account_id, command.account_id);
            if (
              goal.content.assumption_version_id !==
              command.body.assumption_version_id
            )
              throw new ProjectionApiError(
                "CONFLICT",
                409,
                "The selected goal pins a different immutable assumption version.",
              );
          }
          if (command.body.initial_basis.snapshot_id) {
            const snapshot = await clients.portfolio.getSnapshot(
              command.account_id,
              command.body.initial_basis.snapshot_id,
            );
            if (snapshot.id !== command.body.initial_basis.snapshot_id)
              throw new ProjectionApiError(
                "CONFLICT",
                409,
                "The returned snapshot differs from the saved selection.",
              );
          }
          result = {
            ok: true,
            kind: "run",
            value: projectionData(
              await api.create_projection_run(
                command.account_id,
                command.body,
                options,
              ),
            ),
          };
        } else {
          assertProjectionAccount(
            projectionData(
              await api.get_projection_run(command.run_id, { point_limit: 1 }),
            ).account_id,
            command.account_id,
          );
          result = {
            ok: true,
            kind: "run",
            value: projectionData(
              await api.cancel_projection_run(command.run_id, {}, options),
            ),
          };
        }
        assertProjectionAccount(result.value.account_id, command.account_id);
        return result;
      },
    );
    if (!outcome.ok) return outcome;
    revalidatePath("/projections", "page");
    return outcome.data;
  } catch {
    return {
      ok: false,
      code: "PROJECTION_UNAVAILABLE",
      message:
        "The request could not be completed. Retry preserves its identity and your input.",
    };
  }
}
