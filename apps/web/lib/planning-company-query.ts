import { z } from "zod";

const schema = z.strictObject({
  company: z.enum(["include"]).optional(),
  xray_run: z.string().uuid().optional(),
});
export function readPlanningCompanyQuery(
  search: Readonly<Record<string, string | string[] | undefined>>,
) {
  const value = schema.parse({
    company: search.company,
    xray_run: search.xray_run,
  });
  if (value.xray_run && value.company !== "include")
    throw new Error("A company run requires an explicit company selection.");
  return { included: value.company === "include", runId: value.xray_run };
}
