"use server";
import { z } from "zod";
import { revalidatePath } from "next/cache";
import {
  CreateOwnerLayoutRequestSchema,
  OwnerLayoutApiError,
  type OwnerLayoutView,
  type OwnerLayoutArchiveReceipt,
} from "@trading212/api-contracts";
import {
  ownerLayoutClients,
  ownerLayoutData,
  ownerLayoutResult,
} from "./owner-layout-adapter";

const id = z.string().uuid();
const base = { idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/) };
const schema = z.discriminatedUnion("kind", [
  z.strictObject({
    ...base,
    kind: z.literal("create"),
    body: CreateOwnerLayoutRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("update"),
    layout_id: id,
    revision: z.number().int().min(1).max(129),
    body: CreateOwnerLayoutRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("archive"),
    layout_id: id,
    revision: z.number().int().min(1).max(129),
  }),
]);
export type OwnerLayoutAction = z.input<typeof schema>;
export type OwnerLayoutActionResult =
  | { ok: true; kind: "saved"; value: OwnerLayoutView }
  | { ok: true; kind: "archived"; value: OwnerLayoutArchiveReceipt }
  | { ok: false; code: string; message: string };

export async function submitOwnerLayoutCommand(
  input: unknown,
): Promise<OwnerLayoutActionResult> {
  const outcome = await ownerLayoutResult(
    async (): Promise<OwnerLayoutActionResult> => {
      // Session, current token scopes, origin and CSRF precede untrusted parsing.
      const clients = await ownerLayoutClients(true);
      const raw = JSON.stringify(input);
      if (raw === undefined || new TextEncoder().encode(raw).byteLength > 65536)
        throw new OwnerLayoutApiError(
          "REQUEST_TOO_LARGE",
          422,
          "The complete request must fit within 64 KiB.",
        );
      const parsed = schema.safeParse(input);
      if (!parsed.success)
        throw new OwnerLayoutApiError(
          "VALIDATION_FAILED",
          422,
          "Review the bounded layout fields and current revision.",
        );
      const command = parsed.data;
      const options = { idempotencyKey: command.idempotency_key };
      let result: Extract<OwnerLayoutActionResult, { ok: true }>;
      if (command.kind === "archive") {
        result = {
          ok: true,
          kind: "archived",
          value: ownerLayoutData(
            await clients.layouts.archive_owner_layout(
              command.layout_id,
              {},
              {
                ...options,
                ifMatch: `"${command.layout_id}:${command.revision}"`,
              },
            ),
          ),
        };
      } else if (command.kind === "update") {
        result = {
          ok: true,
          kind: "saved",
          value: ownerLayoutData(
            await clients.layouts.update_owner_layout(
              command.layout_id,
              command.body,
              {
                ...options,
                ifMatch: `"${command.layout_id}:${command.revision}"`,
              },
            ),
          ),
        };
      } else
        result = {
          ok: true,
          kind: "saved",
          value: ownerLayoutData(
            await clients.layouts.create_owner_layout(command.body, options),
          ),
        };
      revalidatePath("/settings/layouts", "page");
      return result;
    },
  );
  return outcome.ok ? outcome.data : outcome;
}
