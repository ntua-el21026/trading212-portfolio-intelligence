"use server";

import {
  CreateBenchmarkDefinitionRequestSchema,
  CreateBenchmarkVersionRequestSchema,
  SourceApiError,
  type BenchmarkDefinitionDetail,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import { sourceClients, sourceData } from "./source-adapter";

const identity = {
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
};
const existing = {
  ...identity,
  definition_id: z.string().uuid(),
  if_match: z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]*"$/),
};
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("create"),
    ...identity,
    body: CreateBenchmarkDefinitionRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("version"),
    ...existing,
    body: CreateBenchmarkVersionRequestSchema,
  }),
  z.strictObject({ kind: z.literal("archive"), ...existing }),
]);
export type SourceActionResult =
  | { ok: true; value: BenchmarkDefinitionDetail }
  | { ok: false; code: string; message: string };

export async function submitBenchmarkCommand(
  input: unknown,
): Promise<SourceActionResult> {
  const { sources } = await sourceClients(true);
  try {
    const serialized = JSON.stringify(input);
    if (
      serialized === undefined ||
      new TextEncoder().encode(serialized).byteLength > 65_536
    )
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The benchmark request exceeds 64 KiB.",
      };
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Review the benchmark fields, exact weights and source selections.",
      };
    const command = parsed.data;
    let response;
    if (command.kind === "create")
      response = await sources.create_benchmark_definition(command.body, {
        idempotencyKey: command.idempotency_key,
      });
    else if (command.kind === "version")
      response = await sources.create_benchmark_version(
        command.definition_id,
        command.body,
        { idempotencyKey: command.idempotency_key, ifMatch: command.if_match },
      );
    else
      response = await sources.archive_benchmark_definition(
        command.definition_id,
        {},
        { idempotencyKey: command.idempotency_key, ifMatch: command.if_match },
      );
    const value = sourceData(response);
    revalidatePath("/sources");
    revalidatePath(`/sources/benchmarks/${value.definition.id}`);
    return { ok: true, value };
  } catch (error) {
    return error instanceof SourceApiError
      ? { ok: false, code: error.code, message: error.message }
      : {
          ok: false,
          code: "SOURCES_UNAVAILABLE",
          message:
            "Your inputs are preserved. Retry when source services are available.",
        };
  }
}
