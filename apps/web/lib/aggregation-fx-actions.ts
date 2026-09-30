"use server";
import { z } from "zod";
import {
  AggregateApiError,
  type FxObservationReferencePage,
} from "@trading212/api-contracts";
import {
  aggregationClients,
  aggregationData,
  aggregationResult,
} from "./aggregation-adapter";
import { sourceData } from "./source-adapter";

const fields = {
  selection_id: z.string().uuid(),
  revision: z.number().int().positive(),
  account_id: z.string().uuid(),
  currency: z.string().regex(/^[A-Z]{3}$/),
  direction: z.enum(["direct", "inverse"]),
  cursor: z
    .string()
    .min(1)
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/)
    .nullable(),
};
const query = z.discriminatedUnion("kind", [
  z.strictObject({ ...fields, kind: z.literal("snapshots") }),
  z.strictObject({
    ...fields,
    kind: z.literal("observations"),
    snapshot_id: z.string().uuid(),
  }),
]);
export type AggregateFxQuery = z.input<typeof query>;
export type AggregateFxSnapshotChoice = {
  snapshot_id: string;
  provider: string;
  first_observed_at: string;
  effective_at: string;
  available_count: number;
  availability: string;
};
export type AggregateFxChoices =
  | {
      ok: true;
      kind: "snapshots";
      account_id: string;
      base: string;
      quote: string;
      items: AggregateFxSnapshotChoice[];
      next_cursor: string | null;
    }
  | { ok: true; kind: "observations"; page: FxObservationReferencePage }
  | { ok: false; code: string; message: string };

function timestampOrder(value: string): bigint {
  // Compare only timestamps, retaining PostgreSQL microseconds beyond Date's milliseconds.
  const parts =
    /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!parts)
    throw new AggregateApiError(
      "INVALID_RESPONSE",
      502,
      "Invalid source clock.",
    );
  const milliseconds = Date.parse(`${parts[1]}${parts[3]}`);
  if (!Number.isSafeInteger(milliseconds))
    throw new AggregateApiError(
      "INVALID_RESPONSE",
      502,
      "Invalid source clock.",
    );
  return (
    BigInt(milliseconds) * 1000000n + BigInt((parts[2] ?? "").padEnd(9, "0"))
  );
}

export async function loadAggregateFxChoices(
  input: unknown,
): Promise<AggregateFxChoices> {
  const clients = await aggregationClients(true);
  const parsed = query.safeParse(input);
  if (!parsed.success)
    return {
      ok: false,
      code: "VALIDATION_FAILED",
      message: "Choose an included account, currency and saved FX source.",
    };
  const request = parsed.data;
  const result = await aggregationResult(
    async (): Promise<AggregateFxChoices> => {
      async function authorizedSelection() {
        const selection = aggregationData(
          await clients.aggregates.get_aggregate_selection(
            request.selection_id,
          ),
        );
        if (
          selection.selection_id !== request.selection_id ||
          selection.revision !== request.revision
        )
          throw new AggregateApiError(
            "REVISION_MISMATCH",
            409,
            "Selection revision changed.",
          );
        const member = selection.content.members.find(
          (item) => item.account_id === request.account_id,
        );
        if (
          !member ||
          selection.content.reporting_currency === request.currency
        )
          throw new AggregateApiError(
            "ACCESS_DENIED",
            403,
            "Invalid aggregate currency or member.",
          );
        return { selection, member };
      }
      const { selection, member } = await authorizedSelection();
      const base =
        request.direction === "direct"
          ? request.currency
          : selection.content.reporting_currency;
      const quote =
        request.direction === "direct"
          ? selection.content.reporting_currency
          : request.currency;
      const source_cutoff_at = selection.content.source_cutoff_at;
      let choices: AggregateFxChoices;
      if (request.kind === "snapshots") {
        const status = sourceData(
          await clients.sources.get_fx_source_status(request.account_id, {
            base,
            quote,
            source_cutoff_at,
            limit: 25,
            cursor: request.cursor,
          }),
        );
        if (
          status.account_id !== request.account_id ||
          status.pairs.items.some(
            (pair) => pair.base !== base || pair.quote !== quote,
          )
        )
          throw new AggregateApiError(
            "INVALID_RESPONSE",
            502,
            "FX selection context changed.",
          );
        choices = {
          ok: true,
          kind: "snapshots",
          account_id: request.account_id,
          base,
          quote,
          items: status.pairs.items.flatMap((pair) =>
            pair.latest_snapshot
              ? [
                  {
                    snapshot_id: pair.latest_snapshot.id,
                    provider:
                      status.providers.find(
                        (provider) => provider.id === pair.provider_id,
                      )?.name ?? pair.provider_id,
                    first_observed_at: pair.latest_snapshot.first_observed_at,
                    effective_at: pair.latest_snapshot.effective_at,
                    available_count: pair.latest_snapshot.available_count,
                    availability: pair.availability,
                  },
                ]
              : [],
          ),
          next_cursor: status.pairs.next_cursor,
        };
      } else {
        const snapshot = await clients.portfolio.getSnapshot(
          request.account_id,
          member.portfolio_snapshot_id,
        );
        if (snapshot.id !== member.portfolio_snapshot_id)
          throw new AggregateApiError(
            "INVALID_RESPONSE",
            502,
            "Saved snapshot changed.",
          );
        const effective_at_lte =
          timestampOrder(snapshot.valuation_at) <
          timestampOrder(source_cutoff_at)
            ? snapshot.valuation_at
            : source_cutoff_at;
        const page = sourceData(
          await clients.sources.list_fx_observation_references(
            request.snapshot_id,
            {
              account_id: request.account_id,
              base,
              quote,
              source_cutoff_at,
              effective_at_lte,
              limit: 25,
              cursor: request.cursor,
            },
          ),
        );
        if (
          page.account_id !== request.account_id ||
          page.snapshot_id !== request.snapshot_id ||
          page.base !== base ||
          page.quote !== quote ||
          timestampOrder(page.source_cutoff_at) !==
            timestampOrder(source_cutoff_at) ||
          timestampOrder(page.effective_at_lte) !==
            timestampOrder(effective_at_lte)
        )
          throw new AggregateApiError(
            "INVALID_RESPONSE",
            502,
            "FX selection context changed.",
          );
        choices = { ok: true, kind: "observations", page };
      }
      // A grant on any other member can change while the bounded source read is in flight.
      await authorizedSelection();
      return choices;
    },
  );
  return result.ok ? result.data : result;
}
