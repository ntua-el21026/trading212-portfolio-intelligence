"use server";

import {
  CreateContributionPlanRequestSchema,
  PlanningApiError,
  type ContributionPlanJob,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import { planningClients, planningData } from "./planning-adapter";

const identity = {
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
  body: CreateContributionPlanRequestSchema,
};
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({ kind: z.literal("create"), ...identity }),
  z.strictObject({
    kind: z.literal("revise"),
    ...identity,
    plan_id: z.string().uuid(),
    if_match: z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]*"$/),
  }),
]);

export type PlanningActionResult =
  | { ok: true; job: ContributionPlanJob }
  | { ok: false; code: string; message: string };

export async function submitPlanningCommand(
  input: unknown,
): Promise<PlanningActionResult> {
  // Recheck the session, account scope and CSRF boundary for every command.
  const { planning } = await planningClients(true);
  try {
    const serialized = JSON.stringify(input);
    if (
      serialized === undefined ||
      new TextEncoder().encode(serialized).byteLength > 65_536
    ) {
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The planning request exceeds 64 KiB.",
      };
    }
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success) {
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Review the contribution, selections and allocation constraints.",
      };
    }
    const command = parsed.data;
    const job = planningData(
      command.kind === "create"
        ? await planning.create_contribution_plan(command.body, {
            idempotencyKey: command.idempotency_key,
          })
        : await planning.create_contribution_plan_revision(
            command.plan_id,
            command.body,
            {
              idempotencyKey: command.idempotency_key,
              ifMatch: command.if_match,
            },
          ),
    );
    revalidatePath("/planner");
    revalidatePath(`/planner/${job.plan_id}`);
    return { ok: true, job };
  } catch (error) {
    return error instanceof PlanningApiError
      ? { ok: false, code: error.code, message: error.message }
      : {
          ok: false,
          code: "PLANNING_UNAVAILABLE",
          message:
            "Your inputs are preserved. Retry when planning is available.",
        };
  }
}
