import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VirtualPortfolioResponse } from "@trading212/api-contracts";
import { CreatePieForm } from "../components/target-forms";
import { getDemoPortfolio } from "../lib/demo-data";

const mocks = vi.hoisted(() => ({ command: vi.fn(), push: vi.fn() }));
vi.mock("../lib/target-actions", () => ({
  submitTargetCommand: mocks.command,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
const first = getDemoPortfolio().summary.account;
const second = {
  ...first,
  id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1",
  display_name: "Second account",
};
const pie: VirtualPortfolioResponse = {
  id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc2",
  account_id: first.id,
  name: "Original Pie",
  description: "",
  reporting_currency: "EUR",
  revision: 1,
  state: "draft",
  created_at: "2026-09-07T12:00:00Z",
  updated_at: "2026-09-07T12:00:00Z",
  active_version_id: null,
};

describe("Pie creation request isolation", () => {
  beforeEach(() => vi.resetAllMocks());
  it("freezes all local inputs while the original durable command is pending", async () => {
    const user = userEvent.setup();
    let finish!: (value: {
      ok: true;
      kind: "portfolio";
      value: VirtualPortfolioResponse;
    }) => void;
    mocks.command.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    render(
      <CreatePieForm accounts={[first, second]} initialAccountId={first.id} />,
    );
    await user.type(screen.getByRole("textbox", { name: "Name" }), pie.name);
    await user.click(screen.getByRole("button", { name: "Create Pie" }));
    for (const name of ["Name", "Description", "Reporting currency"]) {
      expect(screen.getByRole("textbox", { name })).toBeDisabled();
    }
    const account = screen.getByRole("combobox", {
      name: "Account",
    });
    expect(account).toBeDisabled();
    await user.selectOptions(account, second.id);
    expect(account).toHaveValue(first.id);
    expect(mocks.command.mock.calls[0][0].body.account_id).toBe(first.id);
    await act(async () => finish({ ok: true, kind: "portfolio", value: pie }));
    expect(mocks.push).toHaveBeenCalledWith(
      "/pies/" + pie.id + "?account=" + first.id,
    );
  });

  it("permits creating a private template when no broker account exists", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: true,
      kind: "portfolio",
      value: { ...pie, account_id: null },
    });
    render(<CreatePieForm accounts={[]} initialAccountId={null} />);
    await user.type(
      screen.getByRole("textbox", { name: "Name" }),
      "Private template",
    );
    await user.click(screen.getByRole("button", { name: "Create Pie" }));
    expect(mocks.command.mock.calls[0][0].body.account_id).toBeNull();
    expect(mocks.push).toHaveBeenCalledWith(
      "/pies/" + pie.id + "?account=template",
    );
  });

  it("does not navigate when creation finishes after the account view is removed", async () => {
    const user = userEvent.setup();
    let finish!: (value: {
      ok: true;
      kind: "portfolio";
      value: VirtualPortfolioResponse;
    }) => void;
    mocks.command.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const view = render(
      <CreatePieForm accounts={[first, second]} initialAccountId={first.id} />,
    );
    await user.type(screen.getByRole("textbox", { name: "Name" }), pie.name);
    await user.click(screen.getByRole("button", { name: "Create Pie" }));
    view.unmount();
    await act(async () => finish({ ok: true, kind: "portfolio", value: pie }));
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
