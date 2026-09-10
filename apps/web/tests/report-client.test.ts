// @vitest-environment node
import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import {
  ReportApiClient,
  ReportApiError,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";

const account = "00000000-0000-4000-8000-000000000001";
const parent = "00000000-0000-4000-8000-000000000002";
const artifact = "00000000-0000-4000-8000-000000000003";
const token = "ephemeral-private-grant-canary-" + "a".repeat(32);
const privateHeaders = {
  "cache-control": "private, no-store",
  "x-content-type-options": "nosniff",
};
function metadata(bytes: Uint8Array): ReportArtifactMetadata {
  return {
    artifact_id: artifact,
    format: "json",
    mime_type: "application/json",
    byte_length: bytes.length,
    content_digest: createHash("sha256").update(bytes).digest("hex"),
    expires_at: "2026-09-14T12:00:00Z",
  };
}
function artifactResponse(
  bytes: Uint8Array<ArrayBuffer>,
  item: ReportArtifactMetadata,
  overrides: HeadersInit = {},
): Response {
  return new Response(bytes, {
    headers: {
      ...privateHeaders,
      "content-type": item.mime_type,
      "content-length": String(item.byte_length),
      "x-artifact-sha256": item.content_digest,
      "content-disposition": `attachment; filename="portfolio-artifact-${artifact}.json"`,
      ...overrides,
    },
  });
}
function client(fetchImpl: typeof fetch, headers?: () => HeadersInit) {
  return new ReportApiClient({
    baseUrl: "https://portfolio.example",
    fetchImpl,
    headers,
  });
}

describe("private report transport", () => {
  it.each([
    ["INVALID_STATE_TRANSITION", 409],
    ["RATE_LIMITED", 429],
  ] as const)(
    "preserves safe %s errors without claiming idempotency reuse",
    async (code, status) => {
      const fetchImpl = vi.fn(async () =>
        Response.json(
          {
            error: { code, message: token, retryable: code === "RATE_LIMITED" },
          },
          { status, headers: privateHeaders },
        ),
      );
      const error = await client(fetchImpl)
        .create_report_download_grant(
          parent,
          artifact,
          { account_id: account },
          {},
        )
        .catch((failure: unknown) => failure);
      expect(error).toBeInstanceOf(ReportApiError);
      expect(error).toMatchObject({ code, status });
      expect(String(error)).not.toContain(token);
      expect(String(error)).not.toContain("idempotency");
    },
  );
  it("downloads a verified artifact larger than the ordinary JSON bound without exposing the grant in its URL", async () => {
    const bytes = new Uint8Array(2 * 1024 * 1024 + 1).fill(32);
    const item = metadata(bytes);
    const fetchImpl = vi.fn(async () => artifactResponse(bytes, item));
    const result = await client(fetchImpl, () => ({
      Authorization: "Bearer session-canary",
      "If-None-Match": "stale",
      "X-Idempotency-Key": "wrong-operation",
    })).download_report_artifact(
      parent,
      artifact,
      { account_id: account },
      { grantToken: token, metadata: item },
    );
    expect(result.content).toEqual(bytes);
    expect(result.filename).toBe(`portfolio-artifact-${artifact}.json`);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.pathname).toBe(
      `/api/v1/reports/${parent}/artifacts/${artifact}/content`,
    );
    expect([...url.searchParams]).toEqual([["account_id", account]]);
    expect(url.href).not.toContain(token);
    expect(init).toMatchObject({
      method: "GET",
      cache: "no-store",
      redirect: "error",
    });
    expect(new Headers(init.headers).get("x-artifact-grant")).toBe(token);
    expect(new Headers(init.headers).has("if-none-match")).toBe(false);
    expect(new Headers(init.headers).has("x-idempotency-key")).toBe(false);
  });
  it.each([
    ["cache-control", "private, max-age=1"],
    ["x-content-type-options", ""],
    ["content-type", "text/html"],
    ["content-length", "99"],
    ["x-artifact-sha256", "e".repeat(64)],
    ["location", "https://other.example/"],
    ["content-disposition", 'attachment; filename="portfolio.html"'],
  ])("rejects a mismatched %s before presenting bytes", async (key, value) => {
    const bytes = new TextEncoder().encode("{}");
    const item = metadata(bytes);
    const fetchImpl = vi.fn(async () =>
      artifactResponse(bytes, item, { [key]: value }),
    );
    await expect(
      client(fetchImpl).download_export_artifact(
        parent,
        artifact,
        { account_id: account },
        { grantToken: token, metadata: item },
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("checks actual bytes and hash despite a matching advertised length and digest", async () => {
    const bytes = new TextEncoder().encode("{}");
    const item = metadata(bytes);
    for (const changed of [
      new TextEncoder().encode("[]"),
      new TextEncoder().encode("{} "),
    ]) {
      await expect(
        client(async () =>
          artifactResponse(changed, item),
        ).download_report_artifact(
          parent,
          artifact,
          { account_id: account },
          { grantToken: token, metadata: item },
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    }
  });
  it("cancels an oversized stream with forged small headers", async () => {
    const item = metadata(new TextEncoder().encode("{}"));
    const cancel = vi.fn();
    const response = artifactResponse(new TextEncoder().encode("{}"), item);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(10 * 1024 * 1024 + 1));
      },
      cancel,
    });
    await expect(
      client(
        async () => new Response(body, { headers: response.headers }),
      ).download_report_artifact(
        parent,
        artifact,
        { account_id: account },
        { grantToken: token, metadata: item },
      ),
    ).rejects.toMatchObject({ code: "RESULT_TOO_LARGE" });
    expect(cancel).toHaveBeenCalledOnce();
  });
  it("cancels rejected bodies and redacts stream failures", async () => {
    const item = metadata(new TextEncoder().encode("{}"));
    const cancel = vi.fn();
    const rejected = new Response(new ReadableStream<Uint8Array>({ cancel }), {
      headers: { ...privateHeaders, "content-type": "text/html" },
    });
    await expect(
      client(async () => rejected).download_report_artifact(
        parent,
        artifact,
        { account_id: account },
        { grantToken: token, metadata: item },
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    expect(cancel).toHaveBeenCalledOnce();
    const headers = artifactResponse(
      new TextEncoder().encode("{}"),
      item,
    ).headers;
    const failed = () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.error(new Error(token));
          },
        }),
        { headers },
      );
    for (const download of [true, false]) {
      const adapter = client(async () => failed());
      const error = await (
        download
          ? adapter.download_report_artifact(
              parent,
              artifact,
              { account_id: account },
              { grantToken: token, metadata: item },
            )
          : adapter.list_reports({ account_id: account })
      ).catch((value: unknown) => value);
      expect(error).toBeInstanceOf(ReportApiError);
      expect(String(error)).not.toContain(token);
    }
  });
  it("rejects invalid metadata and unknown selectors before dispatch", async () => {
    const fetchImpl = vi.fn();
    const item = metadata(new TextEncoder().encode("{}"));
    for (const invalid of [
      { ...item, byte_length: 10 * 1024 * 1024 + 1 },
      { ...item, mime_type: "application/pdf" },
      { ...item, artifact_id: parent },
    ]) {
      await expect(
        client(fetchImpl).download_report_artifact(
          parent,
          artifact,
          { account_id: account },
          { grantToken: token, metadata: invalid as ReportArtifactMetadata },
        ),
      ).rejects.toBeInstanceOf(ReportApiError);
    }
    await expect(
      client(fetchImpl).list_reports({
        account_id: account,
        private_canary: token,
      } as never),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("never reflects network, body or stream failures containing held authentication", async () => {
    const item = metadata(new TextEncoder().encode("{}"));
    for (const fetchImpl of [
      async () => {
        throw new Error(token);
      },
      async () =>
        Response.json(
          { error: { code: "ACCESS_DENIED", message: token } },
          { status: 403 },
        ),
    ]) {
      const error = await client(fetchImpl)
        .download_report_artifact(
          parent,
          artifact,
          { account_id: account },
          { grantToken: token, metadata: item },
        )
        .catch((value: unknown) => value);
      expect(error).toBeInstanceOf(ReportApiError);
      expect(String(error)).not.toContain(token);
    }
  });
  it("issues fresh grant POSTs without idempotency or raw grant reuse in ordinary requests", async () => {
    const fetchImpl = vi.fn(async () =>
      Response.json(
        { artifact_id: artifact, token, expires_at: "2026-09-07T12:05:00Z" },
        { status: 201, headers: privateHeaders },
      ),
    );
    await client(fetchImpl, () => ({
      "X-Artifact-Grant": token,
    })).create_report_download_grant(
      parent,
      artifact,
      { account_id: account },
      {},
    );
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.href).not.toContain(token);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).has("x-artifact-grant")).toBe(false);
    expect(new Headers(init.headers).has("x-idempotency-key")).toBe(false);
    expect(init.body).toBe("{}");
  });
  it("bounds ordinary JSON and rejects redirects or unsolicited 304 replies", async () => {
    for (const response of [
      new Response(null, { status: 302, headers: { location: "/login" } }),
      new Response(null, { status: 304, headers: privateHeaders }),
      new Response(" ".repeat(2 * 1024 * 1024 + 1), {
        headers: { ...privateHeaders, "content-type": "application/json" },
      }),
    ]) {
      await expect(
        client(async () => response).list_reports({ account_id: account }),
      ).rejects.toBeInstanceOf(ReportApiError);
    }
    const result = await client(
      async () => new Response(null, { status: 304, headers: privateHeaders }),
    ).list_reports({ account_id: account }, { ifNoneMatch: '"authorized"' });
    expect(result.notModified).toBe(true);
  });
});
