import { describe, expect, it, vi } from "vitest";
import {
  ResearchApiClient,
  ResearchApiError,
  ResearchMoneySchema,
  type ResearchNoteRevision,
} from "@trading212/api-contracts";

const id = "00000000-0000-4000-8000-000000000001";
const account = "00000000-0000-4000-8000-000000000002";
const entity = "00000000-0000-4000-8000-000000000003";
const at = "2026-09-15T12:00:00Z";
const content = {
  title: "Owner note",
  note: "",
  thesis: "<script>inert text</script> 999999 EUR",
  risks: "Uncertain premise",
  catalysts: "Review next filing",
  break_conditions: "Premise changes",
  citations: [],
  content_type: "owner_revision" as const,
};
const note: ResearchNoteRevision = {
  note_id: id,
  revision_id: id,
  revision: 1,
  previous_revision_id: null,
  owner_id: id,
  account_id: account,
  entity_id: entity,
  actor_id: id,
  created_at: at,
  content,
  content_digest: "a".repeat(64),
  schema_version: "1.0.0",
};
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json", ETag: `"${id}:1"` },
  });

describe("fixed research generated client", () => {
  it("creates owner prose on the exact account path and preserves command authentication headers", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(note));
    const client = new ResearchApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
      headers: () => ({
        "X-CSRF-Token": "session-csrf",
        Authorization: "Bearer synthetic-test",
      }),
    });
    const result = await client.create_research_note(
      account,
      { entity_id: entity, content },
      { idempotencyKey: "note-one" },
    );
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe(
      `https://local.test/api/v1/accounts/${account}/research/notes`,
    );
    expect(init.method).toBe("POST");
    expect(init.cache).toBe("no-store");
    expect(JSON.parse(init.body)).toEqual({ entity_id: entity, content });
    const headers = new Headers(init.headers);
    expect(headers.get("X-Idempotency-Key")).toBe("note-one");
    expect(headers.get("X-CSRF-Token")).toBe("session-csrf");
    expect(result.data?.content.thesis).toBe(content.thesis);
  });
  it("binds note versions to the exact saved revision and review to exact event digests", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response(note))
      .mockResolvedValueOnce(
        response({
          acknowledgment_id: id,
          owner_id: id,
          account_id: account,
          event_id: entity,
          revision_id: id,
          revision_digest: "b".repeat(64),
          actor_id: id,
          reviewed_at: at,
        }),
      );
    const client = new ResearchApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await client.create_research_note_version(
      id,
      { content },
      { idempotencyKey: "version-one", ifMatch: `"${id}:1"` },
    );
    expect(
      new Headers(fetchImpl.mock.calls[0][1].headers).get("If-Match"),
    ).toBe(`"${id}:1"`);
    await client.review_research_event(
      entity,
      { revision_id: id, revision_digest: "b".repeat(64) },
      { idempotencyKey: "review-one" },
    );
    expect(String(fetchImpl.mock.calls[1][0])).toBe(
      `https://local.test/api/v1/research/events/${entity}/review`,
    );
    expect(JSON.parse(fetchImpl.mock.calls[1][1].body)).toEqual({
      revision_id: id,
      revision_digest: "b".repeat(64),
    });
  });
  it("preserves fixed query pins and bounded immutable note-page cursors", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        response({ items: [note], total: 1, limit: 25, next_cursor: null }),
      );
    const client = new ResearchApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await client.list_research_notes(account, {
      limit: 25,
      cursor: "signed_cursor",
    });
    const url = new URL(String(fetchImpl.mock.calls[0][0]));
    expect(url.pathname).toBe(`/api/v1/accounts/${account}/research/notes`);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      limit: "25",
      cursor: "signed_cursor",
    });
    await expect(
      client.get_research_summary(account, {
        xray_run_id: id,
        source_cutoff_at: at,
        cursor: "x".repeat(2049),
      }),
    ).rejects.toBeInstanceOf(ResearchApiError);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
  it("rejects extra request fields and binary financial numbers before they can become source facts", async () => {
    const fetchImpl = vi.fn();
    const client = new ResearchApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    const untrusted = {
      entity_id: entity,
      content,
      url: "https://private-canary.invalid",
    };
    await expect(
      client.create_research_note(account, untrusted, {
        idempotencyKey: "note-one",
      }),
    ).rejects.toBeInstanceOf(ResearchApiError);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(
      ResearchMoneySchema.parse({
        amount: "100.000000000000000001",
        currency: "EUR",
      }).amount,
    ).toBe("100.000000000000000001");
    expect(
      ResearchMoneySchema.safeParse({ amount: 100.1, currency: "EUR" }).success,
    ).toBe(false);
  });
  it("keeps 304 explicit and suppresses private network and provider error text", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(null, { status: 304, headers: { ETag: `"${id}:1"` } }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "SOURCE_UNAVAILABLE",
              message: "private-provider-canary",
            },
          }),
          { status: 503 },
        ),
      )
      .mockRejectedValue(new Error("private-network-canary"));
    const client = new ResearchApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    expect(
      await client.get_research_note(id, { ifNoneMatch: `"${id}:1"` }),
    ).toEqual({ data: null, etag: `"${id}:1"`, notModified: true });
    for (let index = 0; index < 2; index += 1) {
      try {
        await client.get_research_item(id);
        throw new Error("Expected a current-source denial");
      } catch (error) {
        expect(error).toBeInstanceOf(ResearchApiError);
        expect(String(error)).not.toContain("canary");
        expect((error as ResearchApiError).code).toBe("SOURCE_UNAVAILABLE");
      }
    }
  });
});
