import { refreshRunSchema } from "@trading212/api-contracts";
import { z } from "zod";

export const synchronizationRunSchema = refreshRunSchema.extend({
  status: z.enum([
    "queued",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
  ]),
});

export type SynchronizationRun = z.infer<typeof synchronizationRunSchema>;
