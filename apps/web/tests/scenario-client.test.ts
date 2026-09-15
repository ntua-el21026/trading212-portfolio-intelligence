import { describe, expect, it, vi } from "vitest";
import {
  ScenarioApiClient,
  ScenarioApiError,
  CreateScenarioRunRequestSchema,
} from "@trading212/api-contracts";

const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const definition = "45f8f732-2e9d-4ca2-a811-21671202a683";
const version = "b8532ba7-36e4-43ef-aee4-a4e67c75ef9d";
const run = "e42d5fa3-cd19-44ea-890a-e892845b685a";
const secondRun = "d230d897-1f6b-4b09-b1bc-dc3f011097e2";
const content = {
  name: "Scenario",
  mode: "first_order" as const,
  shocks: [
    {
      kind: "fx" as const,
      selector: { kind: "economic_currency" as const, currency: "EUR" },
      size: "-0.012345678901234567",
    },
  ],
};
const saved = {
  id: definition,
  account_id: account,
  name: "Scenario",
  revision: 1,
  archived: false,
  current_version_id: version,
  created_at: "2026-09-15T12:00:00Z",
  updated_at: "2026-09-15T12:00:00Z",
};

function client(fetchImpl: typeof fetch) {
  return new ScenarioApiClient({
    baseUrl: "https://portfolio.example",
    fetchImpl,
  });
}

describe("generated closed scenario client", () => {
  it("exposes eleven fixed operations and preserves ordered comparison pins", async () => {
    const requests: URL[] = [];
    const api = client(async (url, init) => {
      requests.push(new URL(String(url)));
      expect(init?.cache).toBe("no-store");
      expect(init?.redirect).toBe("error");
      return new Response(null, { status: 304 });
    });
    expect(
      Object.getOwnPropertyNames(ScenarioApiClient.prototype).sort(),
    ).toEqual(
      [
        "constructor",
        "list_scenarios",
        "create_scenario",
        "get_scenario",
        "list_scenario_versions",
        "create_scenario_version",
        "get_scenario_version",
        "list_scenario_runs",
        "create_scenario_run",
        "get_scenario_run",
        "compare_scenarios",
        "cancel_scenario_run",
      ].sort(),
    );
    await api.list_scenarios(account, { limit: 25 });
    await api.get_scenario(definition);
    await api.list_scenario_versions(definition, { limit: 25 });
    await api.get_scenario_version(version);
    await api.list_scenario_runs(account, { limit: 25 });
    await api.get_scenario_run(run, {
      component_limit: 1,
      component_cursor: "saved-page",
    });
    await api.compare_scenarios(account, {
      run_ids: [secondRun, run],
      component_limit: 2,
    });
    expect(requests.map((url) => url.pathname)).toEqual([
      `/api/v1/accounts/${account}/scenarios`,
      `/api/v1/scenarios/${definition}`,
      `/api/v1/scenarios/${definition}/versions`,
      `/api/v1/scenario-versions/${version}`,
      `/api/v1/accounts/${account}/scenario-runs`,
      `/api/v1/scenario-runs/${run}`,
      `/api/v1/accounts/${account}/scenario-comparison`,
    ]);
    expect(requests[5].searchParams.get("component_limit")).toBe("1");
    expect(requests[5].searchParams.get("component_cursor")).toBe("saved-page");
    expect(requests[6].searchParams.getAll("run_ids")).toEqual([
      secondRun,
      run,
    ]);
    expect(requests[6].searchParams.get("component_limit")).toBe("2");
  });

  it("preserves exact shocks and command identity without broker dispatch", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (url, init) => {
      expect(String(url)).toBe(
        `https://portfolio.example/api/v1/accounts/${account}/scenarios`,
      );
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("X-Idempotency-Key")).toBe(
        "scenario.create.one",
      );
      expect(JSON.parse(String(init?.body)).content.shocks[0].size).toBe(
        content.shocks[0].size,
      );
      return new Response(JSON.stringify(saved), {
        status: 201,
        headers: { ETag: `"${definition}:1"` },
      });
    });
    const response = await client(fetchImpl).create_scenario(
      account,
      { content },
      { idempotencyKey: "scenario.create.one" },
    );
    expect(response).toMatchObject({
      data: saved,
      notModified: false,
      etag: `"${definition}:1"`,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed identity, paging, source arrays and financial numbers", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = client(fetchImpl);
    const invalid = [
      api.get_scenario_run("../private-canary", {}),
      api.get_scenario_run(run, { component_limit: 101 }),
      api.get_scenario_run(run, { component_cursor: "x".repeat(2049) }),
      api.compare_scenarios(account, { run_ids: [run] }),
      api.create_scenario(
        account,
        { content },
        { idempotencyKey: "private-canary/invalid" },
      ),
      api.create_scenario(
        account,
        {
          content: {
            ...content,
            shocks: [
              {
                ...content.shocks[0],
                // @ts-expect-error Binary financial numbers also fail after type erasure.
                size: 0.1,
              },
            ],
          },
        },
        { idempotencyKey: "one" },
      ),
      // @ts-expect-error Unknown fields remain forbidden at runtime.
      api.list_scenarios(account, { "private-canary": "hidden" }),
    ];
    for (const result of invalid) {
      await expect(result).rejects.toMatchObject({
        code: "VALIDATION_FAILED",
        status: 422,
      });
      await expect(result).rejects.not.toThrow("private-canary");
    }
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(
      CreateScenarioRunRequestSchema.safeParse({ sensitivities: ["0.1"] })
        .success,
    ).toBe(false);
  });

  it("redacts untrusted server and network failure messages", async () => {
    const api = client(
      async () =>
        new Response(
          JSON.stringify({
            error: { code: "SOURCE_UNAVAILABLE", message: "private-canary" },
          }),
          { status: 503 },
        ),
    );
    await expect(api.get_scenario_run(run, {})).rejects.toMatchObject({
      code: "SOURCE_UNAVAILABLE",
      status: 503,
    });
    try {
      await api.get_scenario_run(run, {});
    } catch (error) {
      expect(error).toBeInstanceOf(ScenarioApiError);
      expect(String(error)).not.toContain("private-canary");
    }
    const offline = client(async () => {
      throw new Error("private-canary");
    });
    await expect(offline.get_scenario_run(run, {})).rejects.toMatchObject({
      code: "SCENARIO_UNAVAILABLE",
      message: "The scenario result or service is temporarily unavailable.",
    });
  });

  it("rejects a response exceeding two MiB before decoding its private body", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response("x".repeat(2 * 1024 * 1024 + 1), { status: 200 }),
    );
    await expect(
      client(fetchImpl).get_scenario_run(run, {}),
    ).rejects.toMatchObject({
      code: "RESULT_TOO_LARGE",
      status: 502,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
