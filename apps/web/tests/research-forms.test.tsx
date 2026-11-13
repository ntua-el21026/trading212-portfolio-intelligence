import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ResearchNoteForm,
  ResearchReviewControl,
} from "../components/research-forms";
import { readResearchQuery } from "../lib/research-query";
import { account, id, at, item, note } from "./research-ui-fixtures";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/research-actions", () => ({
  submitResearchCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mocks.push,
    replace: mocks.replace,
    refresh: mocks.refresh,
  }),
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const query = readResearchQuery({ account, view: "notes" }, new Date(at));
beforeEach(() => {
  vi.clearAllMocks();
  mocks.navigation.current = 0;
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "RESEARCH_UNAVAILABLE",
    message: "Retry later",
  });
});
describe("owner prose and exact revision commands", () => {
  it("starts blank instead of copying provider assertions and keeps citation identity explicit", async () => {
    render(
      <ResearchNoteForm
        accountId={account}
        query={query}
        item={item}
        canWrite
      />,
    );
    expect(screen.getByLabelText("Note", { exact: true })).toHaveValue("");
    expect(screen.getByLabelText("Thesis", { exact: true })).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "My assessment" },
    });
    fireEvent.change(screen.getByLabelText("Thesis", { exact: true }), {
      target: { value: "Independent <script>prose</script>" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Save owner note" }));
    await screen.findByRole("alert");
    const command = mocks.submit.mock.calls[0][0];
    expect(command.body.content.thesis).toBe(
      "Independent <script>prose</script>",
    );
    expect(command.body.content.note).toBe("");
    expect(command.body.entity_id).toBe(item.source.entity_id);
    expect(command.body.content.citations).toEqual([
      {
        citation_id: item.source.citations[0].citation_id,
        citation_digest: item.source.citations[0].content_digest,
        source_version_id: item.source.citations[0].source.version_id,
        source_version_digest: item.source.citations[0].source.content_digest,
      },
    ]);
  });
  it("retains retry identity and original revision until a deliberate edit", async () => {
    const readyRevisionButton = () =>
      waitFor(() => {
        const button = screen.getByRole("button", {
          name: "Save new revision",
        });
        expect(button).toBeEnabled();
        return button;
      });
    render(
      <ResearchNoteForm
        accountId={account}
        query={query}
        existing={note}
        canWrite
      />,
    );
    const save = screen.getByRole("button", { name: "Save new revision" });
    fireEvent.click(save);
    await screen.findByRole("alert");
    fireEvent.click(await readyRevisionButton());
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[1][0]).toEqual(
      mocks.submit.mock.calls[0][0],
    );
    expect(mocks.submit.mock.calls[0][0].if_match).toBe(`"${id}:1"`);
    await readyRevisionButton();
    fireEvent.change(screen.getByLabelText("Risks", { exact: true }), {
      target: { value: "Revised premise" },
    });
    fireEvent.click(save);
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      mocks.submit.mock.calls[0][0].idempotency_key,
    );
    await readyRevisionButton();
  });
  it("discards delayed success after account/navigation changes", async () => {
    let finish!: (value: unknown) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ResearchNoteForm
        accountId={account}
        query={query}
        existing={note}
        canWrite
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(1));
    mocks.navigation.current += 1;
    await act(async () => {
      finish({ ok: true, kind: "note", value: note });
    });
    expect(mocks.push).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
  it("disables known missing write grants and rejects title-only content", async () => {
    const { rerender } = render(
      <ResearchNoteForm
        accountId={account}
        query={query}
        item={item}
        canWrite={false}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Save owner note" }),
    ).toBeDisabled();
    rerender(
      <ResearchNoteForm
        accountId={account}
        query={query}
        item={item}
        canWrite
      />,
    );
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Only a title" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save owner note" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Add a note");
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("reviews the selected event revision and clears an invalidated page cursor on success", async () => {
    mocks.submit.mockResolvedValue({
      ok: true,
      kind: "review",
      value: { account_id: account },
    });
    const current = readResearchQuery(
      { account, xray: id, cutoff: at, cursor: "old_cursor" },
      new Date(at),
    );
    render(<ResearchReviewControl item={item} query={current} canWrite />);
    fireEvent.click(
      screen.getByRole("button", { name: "Mark this revision reviewed" }),
    );
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledTimes(1));
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      item_id: item.item_id,
      event_id: item.source.event_id,
      revision_id: item.source.revision_id,
      revision_digest: item.source.content_digest,
    });
    expect(
      new URL(
        mocks.replace.mock.calls[0][0],
        "https://local.test",
      ).searchParams.has("cursor"),
    ).toBe(false);
  });
});
