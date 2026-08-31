import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { dividendSchema } from "@trading212/api-contracts";

const metric = {
  value: null,
  reporting_currency: "EUR",
  availability: "unavailable",
  calculation_version: "phase1-test/1.0.0",
  methodology: "contract fixture",
  provenance: ["contract_fixture"],
  assumptions: [],
  unavailable_reason: "Source quantity is absent.",
};

const quality = {
  state: "partial",
  as_of: "2026-08-31T12:00:00Z",
  source_timestamp: "2026-08-31T12:00:00Z",
  freshness_threshold_seconds: 900,
  warnings: ["Source quantity is absent."],
  missing_inputs: ["dividend.quantity"],
};

describe("generated OpenAPI and runtime client contract", () => {
  it("accepts the API's documented nullable dividend quantity", () => {
    const openapi = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          "../../packages/api-contracts/openapi/phase1-v1.json",
        ),
        "utf8",
      ),
    ) as {
      components: {
        schemas: {
          DividendResponse: {
            properties: { quantity: { anyOf: Array<{ type?: string }> } };
          };
        };
      };
    };
    const quantityTypes =
      openapi.components.schemas.DividendResponse.properties.quantity.anyOf.map(
        (item) => item.type,
      );
    expect(quantityTypes).toEqual(expect.arrayContaining(["string", "null"]));

    const parsed = dividendSchema.parse({
      id: "dividend-contract-fixture",
      paid_on: "2026-08-31",
      ticker: "SYN",
      net_amount: metric,
      gross_amount: metric,
      withholding_tax: metric,
      quantity: null,
      data_quality: quality,
    });
    expect(parsed.quantity).toBeNull();
  });
});
