"use server";
import {
  CreateResearchNoteRequestSchema,
  CreateResearchNoteVersionRequestSchema,
  ResearchApiError,
  type ResearchNoteRevision,
  type ResearchReviewAcknowledgment,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  researchClients,
  researchData,
  researchResult,
  assertResearchAccount,
  assertResearchItem,
} from "./research-adapter";
const id = z.string().uuid();
const base = {
  account_id: id,
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
};
const schema = z.discriminatedUnion("kind", [
  z.strictObject({
    ...base,
    kind: z.literal("create_note"),
    body: CreateResearchNoteRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("create_version"),
    note_id: id,
    if_match: z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]{0,2}"$/),
    body: CreateResearchNoteVersionRequestSchema,
  }),
  z.strictObject({
    ...base,
    kind: z.literal("review"),
    item_id: id,
    event_id: id,
    revision_id: id,
    revision_digest: z.string().regex(/^[0-9a-f]{64}$/),
  }),
]);
export type ResearchActionCommand = z.input<typeof schema>;
export type ResearchActionResult =
  | { ok: true; kind: "note"; value: ResearchNoteRevision }
  | { ok: true; kind: "review"; value: ResearchReviewAcknowledgment }
  | { ok: false; code: string; message: string };
export async function submitResearchCommand(
  input: unknown,
): Promise<ResearchActionResult> {
  // Current session/scopes/origin/CSRF checks precede untrusted command parsing.
  const clients = await researchClients(true);
  const outcome = await researchResult(
    async (): Promise<ResearchActionResult> => {
      const raw = JSON.stringify(input);
      if (raw === undefined || new TextEncoder().encode(raw).byteLength > 65536)
        throw new ResearchApiError(
          "REQUEST_TOO_LARGE",
          422,
          "Research notes must fit within 64 KiB.",
        );
      const parsed = schema.safeParse(input);
      if (!parsed.success)
        throw new ResearchApiError(
          "VALIDATION_FAILED",
          422,
          "Review the note fields and exact selected revision.",
        );
      const command = parsed.data;
      const options = { idempotencyKey: command.idempotency_key };
      const api = clients.research;
      let result: Extract<ResearchActionResult, { ok: true }>;
      if (command.kind === "review") {
        const item = researchData(await api.get_research_item(command.item_id));
        assertResearchItem(item, command.account_id);
        if (
          item.source.event_id !== command.event_id ||
          item.source.revision_id !== command.revision_id ||
          item.source.content_digest !== command.revision_digest
        )
          throw new ResearchApiError(
            "REVISION_MISMATCH",
            409,
            "Reload the item before acknowledging its current revision.",
          );
        result = {
          ok: true,
          kind: "review",
          value: researchData(
            await api.review_research_event(
              command.event_id,
              {
                revision_id: command.revision_id,
                revision_digest: command.revision_digest,
              },
              options,
            ),
          ),
        };
      } else if (command.kind === "create_version") {
        const current = researchData(
          await api.get_research_note(command.note_id),
        );
        assertResearchAccount(current.account_id, command.account_id);
        result = {
          ok: true,
          kind: "note",
          value: researchData(
            await api.create_research_note_version(
              command.note_id,
              command.body,
              { ...options, ifMatch: command.if_match },
            ),
          ),
        };
      } else {
        result = {
          ok: true,
          kind: "note",
          value: researchData(
            await api.create_research_note(
              command.account_id,
              command.body,
              options,
            ),
          ),
        };
      }
      assertResearchAccount(result.value.account_id, command.account_id);
      revalidatePath("/research", "page");
      return result;
    },
  );
  return outcome.ok ? outcome.data : outcome;
}
