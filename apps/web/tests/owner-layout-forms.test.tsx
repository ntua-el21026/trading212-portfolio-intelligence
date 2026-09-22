import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import type { OwnerLayoutContent } from "@trading212/api-contracts";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  OwnerLayoutForm,
  ArchiveOwnerLayoutButton,
} from "../components/owner-layout-forms";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  navigation: { current: 0 },
  search: "mode=edit",
}));
vi.mock("../lib/owner-layout-actions", () => ({
  submitOwnerLayoutCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
  usePathname: () => "/settings/layouts",
  useSearchParams: () => new URLSearchParams(mocks.search),
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
  default: (props: ComponentProps<"a">) => <a {...props} />,
}));
const id = "00000000-0000-4000-8000-000000000001";
const other = "00000000-0000-4000-8000-000000000002";
const initial: OwnerLayoutContent = {
  schema_version: 1,
  name: "Personal review",
  description: "",
  account_id: null,
  columns: 2,
  density: "comfortable",
  widgets: [
    { id, kind: "portfolio_summary", label: "Total", selection: null },
    {
      id: other,
      kind: "saved_view",
      label: "Sources",
      selection: { kind: "workspace", route: "sources", pane: null },
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.navigation.current = 0;
  mocks.search = "mode=edit";
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "CONFLICT",
    message: "Retry this request",
  });
});
describe("saved layout editor behavior", () => {
  it("preserves the same idempotency key across retries and creates a new key for edited content", async () => {
    render(<OwnerLayoutForm initial={initial} accounts={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0][0].idempotency_key).toBe(
      mocks.submit.mock.calls[1][0].idempotency_key,
    );
    fireEvent.change(screen.getByLabelText("Layout name"), {
      target: { value: "Edited owner title" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      mocks.submit.mock.calls[0][0].idempotency_key,
    );
    expect(screen.getByLabelText("Layout name")).toHaveValue(
      "Edited owner title",
    );
  });
  it("saves keyboard-accessible order changes against the exact expected revision", async () => {
    render(
      <OwnerLayoutForm
        initial={initial}
        accounts={[]}
        layoutId={id}
        revision={7}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Move widget 2 up" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Save as new version" }),
    );
    await screen.findByRole("alert");
    const command = mocks.submit.mock.calls[0][0];
    expect(command).toMatchObject({
      kind: "update",
      layout_id: id,
      revision: 7,
    });
    expect(
      command.body.content.widgets.map((widget: { id: string }) => widget.id),
    ).toEqual([other, id]);
    expect(
      screen.getByRole("link", { name: "Reload current revision" }),
    ).toHaveAttribute("href", `/settings/layouts?layout=${id}&mode=edit`);
  });
  it("ignores saved content from an earlier account or navigation", async () => {
    let finish!: (value: unknown) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(<OwnerLayoutForm initial={initial} accounts={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    mocks.navigation.current += 1;
    mocks.search = `account=${other}`;
    view.rerender(<OwnerLayoutForm initial={initial} accounts={[]} />);
    await act(async () =>
      finish({ ok: true, kind: "saved", value: { id, content: initial } }),
    );
    expect(mocks.push).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
  it("does not navigate after an archive response from a previous navigation", async () => {
    let finish!: (value: unknown) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<ArchiveOwnerLayoutButton layoutId={id} revision={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Archive layout" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    mocks.navigation.current += 1;
    await act(async () => finish({ ok: true, kind: "archived" }));
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
