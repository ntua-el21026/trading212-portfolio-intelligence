import { describe, expect, it, vi } from "vitest";
import {
  OwnerLayoutApiClient,
  OwnerLayoutApiError,
  OwnerLayoutContentSchema,
  type OwnerLayoutContent,
  type OwnerLayoutView,
} from "@trading212/api-contracts";
const id = "00000000-0000-4000-8000-000000000001";
const version = "00000000-0000-4000-8000-000000000002";
const at = "2026-09-15T12:00:00.123456Z";
export const layoutContent: OwnerLayoutContent = {
  schema_version: 1,
  name: "Owner workspace",
  description: "<script>ordinary private text</script>",
  account_id: null,
  columns: 2,
  density: "comfortable",
  widgets: [
    {
      id,
      kind: "saved_view",
      label: "My sources",
      selection: { kind: "workspace", route: "sources", pane: null },
    },
  ],
};
export const layoutView: OwnerLayoutView = {
  id,
  revision: 1,
  state: "active",
  content: layoutContent,
  version: {
    id: version,
    number: 1,
    created_at: at,
    content_digest: "a".repeat(64),
  },
  versions: [
    { id: version, number: 1, created_at: at, content_digest: "a".repeat(64) },
  ],
};
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json", ETag: `"${id}:1"` },
  });

describe("fixed saved layout client", () => {
  it("uses exact create/update/archive routes with current command headers and no-store", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response(layoutView))
      .mockResolvedValueOnce(response({ ...layoutView, revision: 2 }))
      .mockResolvedValueOnce(
        response({ id, revision: 3, state: "archived", archived_at: at }),
      );
    const client = new OwnerLayoutApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
      headers: () => ({
        "X-CSRF-Token": "csrf",
        Authorization: "Bearer current",
      }),
    });
    const created = await client.create_owner_layout(
      { content: layoutContent },
      { idempotencyKey: "create-once" },
    );
    await client.update_owner_layout(
      id,
      { content: { ...layoutContent, name: "Revision" } },
      { idempotencyKey: "update-once", ifMatch: `"${id}:1"` },
    );
    await client.archive_owner_layout(
      id,
      {},
      { idempotencyKey: "archive-once", ifMatch: `"${id}:2"` },
    );
    expect(
      fetchImpl.mock.calls.map(([url, init]) => [String(url), init.method]),
    ).toEqual([
      ["https://local.test/api/v1/preferences/layouts", "POST"],
      [`https://local.test/api/v1/preferences/layouts/${id}`, "PATCH"],
      [`https://local.test/api/v1/preferences/layouts/${id}/archive`, "POST"],
    ]);
    for (const [, init] of fetchImpl.mock.calls) {
      expect(init.cache).toBe("no-store");
      expect(init.redirect).toBe("error");
      expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf");
      expect(new Headers(init.headers).get("Authorization")).toBe(
        "Bearer current",
      );
    }
    expect(
      new Headers(fetchImpl.mock.calls[1][1].headers).get("If-Match"),
    ).toBe(`"${id}:1"`);
    expect(created.data?.content.description).toBe(layoutContent.description);
  });
  it("pins selected versions and list cursors on the two closed reads", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(response(layoutView))
      .mockResolvedValueOnce(
        response({
          items: [],
          total: 0,
          limit: 25,
          next_cursor: null,
          read_cutoff_at: at,
        }),
      );
    const client = new OwnerLayoutApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await client.get_owner_layout(
      id,
      { version_id: version },
      { ifNoneMatch: '"saved-version"' },
    );
    await client.list_owner_layouts({
      limit: 25,
      include_archived: true,
      cursor: "signed_page",
    });
    expect(
      new URL(String(fetchImpl.mock.calls[0][0])).searchParams.get(
        "version_id",
      ),
    ).toBe(version);
    expect(
      Object.fromEntries(
        new URL(String(fetchImpl.mock.calls[1][0])).searchParams,
      ),
    ).toEqual({ limit: "25", include_archived: "true", cursor: "signed_page" });
    expect(
      new Headers(fetchImpl.mock.calls[0][1].headers).get("If-None-Match"),
    ).toBe('"saved-version"');
  });
  it("rejects unknown selectors and invalid identities before any network request", async () => {
    const fetchImpl = vi.fn();
    const client = new OwnerLayoutApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await expect(
      client.create_owner_layout(
        {
          content: { ...layoutContent, url: "https://private.invalid" },
        } as never,
        { idempotencyKey: "reject" },
      ),
    ).rejects.toBeInstanceOf(OwnerLayoutApiError);
    await expect(
      client.get_owner_layout("../../private", {}),
    ).rejects.toBeInstanceOf(OwnerLayoutApiError);
    await expect(
      client.list_owner_layouts({ cursor: "x".repeat(2049) }),
    ).rejects.toBeInstanceOf(OwnerLayoutApiError);
    expect(
      OwnerLayoutContentSchema.safeParse({
        ...layoutContent,
        schema_version: true,
      }).success,
    ).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("does not turn transport errors into private source prose or a fabricated layout", async () => {
    const fetchImpl = vi.fn().mockImplementation(
      () =>
        new Response(
          JSON.stringify({
            detail: "secret-provider-payload",
            error: {
              code: "ACCESS_DENIED",
              message: "secret-provider-payload",
            },
          }),
          { status: 403 },
        ),
    );
    const client = new OwnerLayoutApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await expect(client.get_owner_layout(id, {})).rejects.toMatchObject({
      status: 403,
    });
    const denied = await client
      .get_owner_layout(id, {})
      .catch((error: unknown) => error);
    expect(String(denied)).not.toContain("secret-provider-payload");
  });
});
