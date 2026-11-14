import { expect, it } from "vitest";
import {
  ResearchReviewAcknowledgmentSchema,
  ResearchXrayPinSchema,
} from "@trading212/api-contracts";
import {
  ResearchReviewAcknowledgmentSchema as OriginalReviewSchema,
  ResearchXrayPinSchema as OriginalXraySchema,
} from "../../../packages/api-contracts/src/research.generated";
import { pin } from "./research-ui-fixtures";

it("preserves the original shared research exports and their closed shape", () => {
  expect(ResearchReviewAcknowledgmentSchema).toBe(OriginalReviewSchema);
  expect(ResearchXrayPinSchema).toBe(OriginalXraySchema);
  expect(ResearchXrayPinSchema.parse(pin)).toEqual(pin);
  expect(
    ResearchXrayPinSchema.safeParse({ ...pin, item_id: pin.run_id }).success,
  ).toBe(false);
  expect(
    ResearchXrayPinSchema.safeParse({ ...pin, run_id: "latest" }).success,
  ).toBe(false);
});
