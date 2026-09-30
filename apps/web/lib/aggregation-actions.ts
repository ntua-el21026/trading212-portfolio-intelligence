"use server";
import { z } from "zod";
import { revalidatePath } from "next/cache";
import {
  CreateAggregateSelectionRequestSchema,
  CreateAggregateRunRequestSchema,
  type AggregateSelectionResponse,
  type AggregateRunReceipt,
  type Snapshot,
} from "@trading212/api-contracts";
import {
  aggregationClients,
  aggregationData,
  aggregationResult,
} from "./aggregation-adapter";
const id = z.string().uuid();
const key = z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/);
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("selection"),
    idempotency_key: key,
    body: CreateAggregateSelectionRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("run"),
    idempotency_key: key,
    selection_id: id,
    revision: z.number().int().min(1).max(2147483647),
    body: CreateAggregateRunRequestSchema,
  }),
]);
export type AggregationCommand = z.input<typeof commandSchema>;
export type AggregationCommandResult =
  | { ok: true; kind: "selection"; value: AggregateSelectionResponse }
  | { ok: true; kind: "run"; value: AggregateRunReceipt }
  | { ok: false; code: string; message: string };
export async function submitAggregationCommand(
  input: unknown,
): Promise<AggregationCommandResult> {
  // Session/origin/CSRF checks precede even invalid caller data.
  const clients = await aggregationClients(true);
  const raw = JSON.stringify(input);
  if (raw === undefined || new TextEncoder().encode(raw).byteLength > 65536)
    return {
      ok: false,
      code: "REQUEST_TOO_LARGE",
      message: "The aggregate request exceeds its bounded size.",
    };
  const parsed = commandSchema.safeParse(input);
  if (!parsed.success)
    return {
      ok: false,
      code: "VALIDATION_FAILED",
      message:
        "Review the selected accounts, snapshots, currency and source cutoff.",
    };
  const command = parsed.data;
  const outcome = await aggregationResult(
    async (): Promise<AggregationCommandResult> => {
      const options = { idempotencyKey: command.idempotency_key };
      if (command.kind === "selection")
        return {
          ok: true,
          kind: "selection",
          value: aggregationData(
            await clients.aggregates.create_aggregate_selection(
              command.body,
              options,
            ),
          ),
        };
      return {
        ok: true,
        kind: "run",
        value: aggregationData(
          await clients.aggregates.create_aggregate_run(
            command.selection_id,
            command.body,
            {
              ...options,
              ifMatch: `"${command.selection_id}:${command.revision}"`,
            },
          ),
        ),
      };
    },
  );
  if (!outcome.ok) return outcome;
  revalidatePath("/aggregation");
  return outcome.data;
}
export type AggregateSnapshotChoice = Pick<
  Snapshot,
  "id" | "valuation_at" | "source_cutoff_at" | "reporting_currency"
>;
export async function loadAggregateSnapshotChoices(input: unknown): Promise<
  | {
      ok: true;
      account_id: string;
      items: AggregateSnapshotChoice[];
      next_cursor: string | null;
    }
  | { ok: false; code: string; message: string }
> {
  const clients = await aggregationClients(true);
  const parsed = z
    .strictObject({
      account_id: id,
      cursor: z
        .string()
        .min(1)
        .max(2048)
        .regex(/^[A-Za-z0-9_-]+$/)
        .nullable(),
    })
    .safeParse(input);
  if (!parsed.success)
    return {
      ok: false,
      code: "VALIDATION_FAILED",
      message: "Choose one available account.",
    };
  const result = await aggregationResult(() =>
    clients.portfolio.listSnapshots(parsed.data.account_id, {
      limit: 25,
      cursor: parsed.data.cursor,
    }),
  );
  if (!result.ok) return result;
  return {
    ok: true,
    account_id: parsed.data.account_id,
    next_cursor: result.data.next_cursor,
    items: result.data.items.map(
      ({ id, valuation_at, source_cutoff_at, reporting_currency }) => ({
        id,
        valuation_at,
        source_cutoff_at,
        reporting_currency,
      }),
    ),
  };
}
