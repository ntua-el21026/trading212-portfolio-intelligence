"use server";
import {
  CreateScenarioRequestSchema,
  CreateScenarioVersionRequestSchema,
  CreateScenarioRunRequestSchema,
  ScenarioApiError,
  type ScenarioDefinitionResponse,
  type ScenarioVersionResponse,
  type ScenarioRunResponse,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  assertScenarioAccount,
  savedScenarioXray,
  scenarioClients,
  scenarioData,
  scenarioResult,
} from "./scenario-adapter";

const id = z.string().uuid();
const base = {
  account_id: id,
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
};
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    ...base,
    kind: z.literal("create_definition"),
    body: CreateScenarioRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_version"),
    definition_id: id,
    if_match: z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]{0,2}"$/),
    body: CreateScenarioVersionRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_run"),
    body: CreateScenarioRunRequestSchema,
  }),
  z.strictObject({ ...base, kind: z.literal("cancel_run"), run_id: id }),
]);
export type ScenarioActionCommand = z.input<typeof commandSchema>;
export type ScenarioActionResult =
  | { ok: true; kind: "definition"; value: ScenarioDefinitionResponse }
  | { ok: true; kind: "version"; value: ScenarioVersionResponse }
  | { ok: true; kind: "run"; value: ScenarioRunResponse }
  | { ok: false; code: string; message: string };

export async function submitScenarioCommand(
  input: unknown,
): Promise<ScenarioActionResult> {
  // Authenticate and verify origin/CSRF on every invocation before body parsing.
  const clients = await scenarioClients(true);
  try {
    const raw = JSON.stringify(input);
    if (raw === undefined || new TextEncoder().encode(raw).byteLength > 65536)
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The scenario request exceeds 64 KiB.",
      };
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message: "Review the scenario assumptions and saved input selections.",
      };
    const command = parsed.data;
    const options = { idempotencyKey: command.idempotency_key };
    const outcome = await scenarioResult(
      async (): Promise<ScenarioActionResult> => {
        const api = clients.scenarios;
        let result: ScenarioActionResult;
        if (command.kind === "create_definition")
          result = {
            ok: true,
            kind: "definition",
            value: scenarioData(
              await api.create_scenario(
                command.account_id,
                command.body,
                options,
              ),
            ),
          };
        else if (command.kind === "create_version") {
          assertScenarioAccount(
            scenarioData(await api.get_scenario(command.definition_id))
              .account_id,
            command.account_id,
          );
          result = {
            ok: true,
            kind: "version",
            value: scenarioData(
              await api.create_scenario_version(
                command.definition_id,
                command.body,
                { ...options, ifMatch: command.if_match },
              ),
            ),
          };
        } else if (command.kind === "create_run") {
          const version = scenarioData(
            await api.get_scenario_version(command.body.scenario_version_id),
          );
          assertScenarioAccount(version.account_id, command.account_id);
          if (command.body.replay && (version.content.shocks?.length ?? 0) > 0)
            throw new ScenarioApiError(
              "VALIDATION_FAILED",
              422,
              "Replay requires a saved version with no hypothetical shocks.",
            );
          await savedScenarioXray(clients, command.account_id, command.body);
          result = {
            ok: true,
            kind: "run",
            value: scenarioData(
              await api.create_scenario_run(
                command.account_id,
                command.body,
                options,
              ),
            ),
          };
        } else {
          assertScenarioAccount(
            scenarioData(
              await api.get_scenario_run(command.run_id, {
                component_limit: 1,
              }),
            ).account_id,
            command.account_id,
          );
          result = {
            ok: true,
            kind: "run",
            value: scenarioData(
              await api.cancel_scenario_run(command.run_id, {}, options),
            ),
          };
        }
        assertScenarioAccount(result.value.account_id, command.account_id);
        return result;
      },
    );
    if (!outcome.ok) return outcome;
    revalidatePath("/scenarios", "page");
    return outcome.data;
  } catch {
    return {
      ok: false,
      code: "SCENARIO_UNAVAILABLE",
      message:
        "The request could not be completed. Retry preserves its identity and your input.",
    };
  }
}
