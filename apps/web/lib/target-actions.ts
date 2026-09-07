"use server";

import {
  CreateVirtualPortfolioRequestSchema,
  CreateTargetVersionRequestSchema,
  UpdateVirtualPortfolioRequestSchema,
  ReplaceTargetDraftRequestSchema,
  ValidateTargetRequestSchema,
  PublishTargetRequestSchema,
  TargetApiError,
  type TargetVersionResponse,
  type TargetValidationResponse,
  type VirtualPortfolioResponse,
  type Instrument,
  type Page,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import { targetClients, targetData } from "./target-adapter";

const identity = {
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
  if_match: z
    .string()
    .regex(/^"[0-9a-f-]{36}:[1-9][0-9]*"$/)
    .optional(),
};
const id = z.string().uuid();
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("create_portfolio"),
    ...identity,
    body: CreateVirtualPortfolioRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("update_portfolio"),
    ...identity,
    portfolio_id: id,
    body: UpdateVirtualPortfolioRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("archive_portfolio"),
    ...identity,
    portfolio_id: id,
  }),
  z.strictObject({
    kind: z.literal("create_version"),
    ...identity,
    portfolio_id: id,
    body: CreateTargetVersionRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("replace_draft"),
    ...identity,
    version_id: id,
    body: ReplaceTargetDraftRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("validate_version"),
    ...identity,
    version_id: id,
    body: ValidateTargetRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("publish_version"),
    ...identity,
    version_id: id,
    body: PublishTargetRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("archive_version"),
    ...identity,
    version_id: id,
  }),
]);

export type TargetActionCommand = z.input<typeof commandSchema>;
export type TargetActionResult =
  | { ok: true; kind: "portfolio"; value: VirtualPortfolioResponse }
  | { ok: true; kind: "version"; value: TargetVersionResponse }
  | { ok: true; kind: "validation"; value: TargetValidationResponse }
  | { ok: false; code: string; message: string; fields: string[] };

export async function submitTargetCommand(
  input: unknown,
): Promise<TargetActionResult> {
  // Authentication is repeated inside every action; a protected layout is not authorization.
  const { targets } = await targetClients(true);
  try {
    const serialized = JSON.stringify(input);
    if (
      serialized === undefined ||
      new TextEncoder().encode(serialized).byteLength > 65_536
    ) {
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The target request exceeds 64 KiB.",
        fields: [],
      };
    }
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success) {
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message: "Review the highlighted target fields.",
        fields: [
          ...new Set(parsed.error.issues.map((issue) => issue.path.join("."))),
        ].slice(0, 20),
      };
    }
    const command = parsed.data;
    const options = {
      idempotencyKey: command.idempotency_key,
      ifMatch: command.if_match,
    };
    let result: TargetActionResult;
    switch (command.kind) {
      case "create_portfolio":
        result = {
          ok: true,
          kind: "portfolio",
          value: targetData(
            await targets.create_virtual_portfolio(command.body, options),
          ),
        };
        break;
      case "update_portfolio":
        result = {
          ok: true,
          kind: "portfolio",
          value: targetData(
            await targets.update_virtual_portfolio(
              command.portfolio_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "archive_portfolio":
        result = {
          ok: true,
          kind: "portfolio",
          value: targetData(
            await targets.archive_virtual_portfolio(
              command.portfolio_id,
              {},
              options,
            ),
          ),
        };
        break;
      case "create_version":
        result = {
          ok: true,
          kind: "version",
          value: targetData(
            await targets.create_target_version(
              command.portfolio_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "replace_draft":
        result = {
          ok: true,
          kind: "version",
          value: targetData(
            await targets.replace_target_draft(
              command.version_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "validate_version":
        result = {
          ok: true,
          kind: "validation",
          value: targetData(
            await targets.validate_target_version(
              command.version_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "publish_version":
        result = {
          ok: true,
          kind: "version",
          value: targetData(
            await targets.publish_target_version(
              command.version_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "archive_version":
        result = {
          ok: true,
          kind: "version",
          value: targetData(
            await targets.archive_target_version(
              command.version_id,
              {},
              options,
            ),
          ),
        };
        break;
    }
    revalidatePath("/pies", "layout");
    return result;
  } catch (error) {
    if (error instanceof TargetApiError) {
      return {
        ok: false,
        code: error.code,
        message: error.message,
        fields: [],
      };
    }
    return {
      ok: false,
      code: "TARGETS_UNAVAILABLE",
      message:
        "The target service could not complete this request. Your edits are preserved.",
      fields: [],
    };
  }
}

export async function searchTargetInstruments(
  input: unknown,
): Promise<
  { ok: true; page: Page<Instrument> } | { ok: false; message: string }
> {
  const { portfolio } = await targetClients();
  const parsed = z
    .strictObject({
      query: z.string().max(80).optional(),
      cursor: z.string().max(2048).nullable().optional(),
    })
    .safeParse(input);
  if (!parsed.success)
    return { ok: false, message: "Use a search of at most 80 characters." };
  try {
    return {
      ok: true,
      page: await portfolio.listInstruments({ ...parsed.data, limit: 100 }),
    };
  } catch {
    return {
      ok: false,
      message:
        "The instrument catalog is unavailable. Your target edits are preserved.",
    };
  }
}
