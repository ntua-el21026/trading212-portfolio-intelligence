"use server";

import {
  CreateRiskDefinitionRequestSchema,
  CreateRiskVersionRequestSchema,
  CreateRiskRunRequestSchema,
  RiskApiError,
  type RiskDefinitionResponse,
  type RiskVersionResponse,
  type RiskRunResponse,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { riskClients, riskData } from "./risk-adapter";

const key = z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/);
const id = z.string().uuid();
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("create_definition"),
    account_id: id,
    idempotency_key: key,
    body: CreateRiskDefinitionRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("create_version"),
    definition_id: id,
    idempotency_key: key,
    if_match: z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]{0,2}"$/),
    body: CreateRiskVersionRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("create_run"),
    account_id: id,
    idempotency_key: key,
    body: CreateRiskRunRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("cancel_run"),
    run_id: id,
    idempotency_key: key,
  }),
]);
export type RiskActionCommand = z.input<typeof commandSchema>;
export type RiskActionResult =
  | { ok: true; kind: "definition"; value: RiskDefinitionResponse }
  | { ok: true; kind: "version"; value: RiskVersionResponse }
  | { ok: true; kind: "run"; value: RiskRunResponse }
  | { ok: false; code: string; message: string };

export async function submitRiskCommand(
  input: unknown,
): Promise<RiskActionResult> {
  // Every invocation reauthenticates and validates the session origin/CSRF.
  const { risk } = await riskClients(true);
  try {
    const raw = JSON.stringify(input);
    if (raw === undefined || new TextEncoder().encode(raw).byteLength > 65536)
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The risk request exceeds 64 KiB.",
      };
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message: "Review the risk definition and selected inputs.",
      };
    const command = parsed.data;
    const options = { idempotencyKey: command.idempotency_key };
    let result: RiskActionResult;
    switch (command.kind) {
      case "create_definition":
        result = {
          ok: true,
          kind: "definition",
          value: riskData(
            await risk.create_risk_definition(
              command.account_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "create_version":
        result = {
          ok: true,
          kind: "version",
          value: riskData(
            await risk.create_risk_version(
              command.definition_id,
              command.body,
              { ...options, ifMatch: command.if_match },
            ),
          ),
        };
        break;
      case "create_run":
        result = {
          ok: true,
          kind: "run",
          value: riskData(
            await risk.create_risk_run(
              command.account_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "cancel_run":
        result = {
          ok: true,
          kind: "run",
          value: riskData(
            await risk.cancel_risk_run(command.run_id, {}, options),
          ),
        };
        break;
    }
    revalidatePath("/risk", "page");
    return result;
  } catch (error) {
    if (error instanceof RiskApiError)
      return { ok: false, code: error.code, message: error.message };
    return {
      ok: false,
      code: "RISK_UNAVAILABLE",
      message:
        "The risk request could not be completed. Your input is preserved; retry uses the same request identity.",
    };
  }
}
