import { beforeEach, describe, expect, it, vi } from "vitest";
import { account, id, other, item, note } from "./research-ui-fixtures";
type AdapterModule = typeof import("../lib/research-adapter");
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  create: vi.fn(),
  version: vi.fn(),
  getNote: vi.fn(),
  getItem: vi.fn(),
  review: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("../lib/research-adapter", async (original) => ({
  ...(await original<AdapterModule>()),
  researchClients: mocks.clients,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
import { submitResearchCommand } from "../lib/research-actions";
const response = <T>(data: T) => ({ data, notModified: false, etag: null });
const command = {
  kind: "create_note",
  account_id: account,
  body: { entity_id: other, content: note.content },
  idempotency_key: "same-attempt",
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.clients.mockResolvedValue({
    research: {
      create_research_note: mocks.create,
      create_research_note_version: mocks.version,
      get_research_note: mocks.getNote,
      get_research_item: mocks.getItem,
      review_research_event: mocks.review,
    },
  });
  mocks.create.mockResolvedValue(response(note));
  mocks.version.mockResolvedValue(response(note));
  mocks.getNote.mockResolvedValue(response(note));
  mocks.getItem.mockResolvedValue(response(item));
  mocks.review.mockResolvedValue(response({ account_id: account }));
});
describe("research action authority and revision pinning", () => {
  it("checks session/scopes/CSRF before reading body properties", async () => {
    mocks.clients.mockRejectedValue(new Error("CSRF denied"));
    const body = {
      get kind(): string {
        throw new Error("untrusted body accessed");
      },
    };
    await expect(submitResearchCommand(body)).rejects.toThrow("CSRF denied");
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("preserves note prose and retry identity without deriving finance", async () => {
    expect(await submitResearchCommand(command)).toMatchObject({ ok: true });
    await submitResearchCommand(command);
    expect(mocks.clients.mock.calls).toEqual([[true], [true]]);
    expect(mocks.create.mock.calls[0]).toEqual([
      account,
      command.body,
      { idempotencyKey: "same-attempt" },
    ]);
    expect(mocks.create.mock.calls[1]).toEqual(mocks.create.mock.calls[0]);
  });
  it("checks version account and forwards the original If-Match", async () => {
    const edit = {
      kind: "create_version",
      account_id: account,
      note_id: id,
      if_match: `"${id}:1"`,
      body: { content: note.content },
      idempotency_key: "edit",
    };
    await submitResearchCommand(edit);
    expect(mocks.version).toHaveBeenCalledWith(id, edit.body, {
      idempotencyKey: "edit",
      ifMatch: `"${id}:1"`,
    });
    mocks.getNote.mockResolvedValue(response({ ...note, account_id: other }));
    mocks.version.mockClear();
    expect(await submitResearchCommand(edit)).toMatchObject({
      ok: false,
      code: "NOT_FOUND",
    });
    expect(mocks.version).not.toHaveBeenCalled();
  });
  it("rereads the exact item before review and rejects changed digests or foreign account", async () => {
    const review = {
      kind: "review",
      account_id: account,
      item_id: id,
      event_id: id,
      revision_id: id,
      revision_digest: item.source.content_digest,
      idempotency_key: "review",
    };
    await submitResearchCommand(review);
    expect(mocks.review).toHaveBeenCalledWith(
      id,
      { revision_id: id, revision_digest: item.source.content_digest },
      { idempotencyKey: "review" },
    );
    mocks.review.mockClear();
    expect(
      await submitResearchCommand({
        ...review,
        revision_digest: "f".repeat(64),
      }),
    ).toMatchObject({ ok: false, code: "REVISION_MISMATCH" });
    mocks.getItem.mockResolvedValue(
      response({
        ...item,
        portfolio: {
          ...item.portfolio,
          pin: { ...item.portfolio.pin, account_id: other },
        },
      }),
    );
    expect(await submitResearchCommand(review)).toMatchObject({
      ok: false,
      code: "NOT_FOUND",
    });
    expect(mocks.review).not.toHaveBeenCalled();
  });
  it("bounds UTF-8 command bytes before mutation", async () => {
    expect(
      await submitResearchCommand({
        ...command,
        body: {
          entity_id: other,
          content: { title: "x", note: "😀".repeat(17000) },
        },
      }),
    ).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
