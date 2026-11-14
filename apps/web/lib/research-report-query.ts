import { z } from "zod";
import type { ResearchItemView } from "@trading212/api-contracts";

const uuid = z
  .string()
  .uuid()
  .transform((value) => value.toLowerCase());
const digest = z.string().regex(/^[a-f0-9]{64}$/);

export const researchReportPinsSchema = z.strictObject({
  family: z.literal("research"),
  item_id: uuid,
  note_revision_ids: z
    .array(uuid)
    .max(64)
    .refine((values) => new Set(values).size === values.length)
    .transform((values) => [...values].sort()),
  review_acknowledgment_id: uuid.optional(),
});

export type ResearchReportPins = z.infer<typeof researchReportPinsSchema>;
export type ResearchReportSource = {
  accountId: string;
  itemId: string;
  eventRevisionId: string;
  eventDigest: string;
  xrayResultDigest: string;
  snapshotId: string;
  currency: string;
  valuationAt: string;
  xraySourceCutoff: string;
  sourceCutoff: string;
  name: string;
};

export function researchReportSource(
  item: ResearchItemView,
  accountId: string,
): ResearchReportSource | null {
  const pin = item.portfolio.pin;
  if (
    !uuid.safeParse(item.item_id).success ||
    pin.account_id !== accountId ||
    item.source.owner_id !== pin.owner_id ||
    item.source.entity_id !== item.portfolio.entity_id ||
    !digest.safeParse(item.source.content_digest).success ||
    !digest.safeParse(pin.result_digest).success
  )
    return null;
  const facts = item.source.facts;
  return {
    accountId,
    itemId: item.item_id,
    eventRevisionId: item.source.revision_id,
    eventDigest: item.source.content_digest,
    xrayResultDigest: pin.result_digest,
    snapshotId: pin.snapshot_id,
    currency: pin.reporting_currency,
    valuationAt: pin.valuation_at,
    xraySourceCutoff: pin.source_cutoff_at,
    sourceCutoff: item.source_cutoff_at,
    name: facts.kind === "news" ? facts.title : facts.company_name,
  };
}

export function researchReportHref(
  source: ResearchReportSource,
  pins?: ResearchReportPins,
  report?: string,
): string {
  const search = new URLSearchParams({
    profile: "report_sections_v3",
    family: "research",
    account: source.accountId,
    item: source.itemId,
  });
  if (pins) {
    const selected = researchReportPinsSchema.parse(pins);
    if (selected.item_id !== source.itemId)
      throw new Error("The research item differs.");
    if (selected.note_revision_ids.length)
      search.set("note_revisions", selected.note_revision_ids.join(","));
    if (selected.review_acknowledgment_id)
      search.set("review", selected.review_acknowledgment_id);
  }
  if (report) search.set("report", uuid.parse(report));
  return `/reports/premium?${search}`;
}
