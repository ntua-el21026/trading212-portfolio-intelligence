import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import {
  AccountProvider,
  AccountSelector,
  AccountView,
} from "../components/account-context";
import { getDemoPortfolio } from "../lib/demo-data";

const navigation = vi.hoisted(() => ({
  query: "",
  pathname: "/holdings",
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.query),
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push }),
}));
const first = getDemoPortfolio().summary.account;
const second = {
  ...first,
  id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1",
  display_name: "Second portfolio",
};

function Draft() {
  const [value, setValue] = useState("");
  return (
    <input
      aria-label="Account draft"
      value={value}
      onChange={(event) => setValue(event.target.value)}
    />
  );
}
function View({
  loadedAccount = first.id,
}: Readonly<{ loadedAccount?: string }>) {
  return (
    <AccountProvider accounts={[first, second]} preferred={first.id}>
      <AccountSelector />
      <AccountView accountId={loadedAccount}>
        <p>Loaded account {loadedAccount}</p>
        <Draft />
      </AccountView>
    </AccountProvider>
  );
}

describe("account presentation boundary", () => {
  beforeEach(() => {
    navigation.query = "";
    navigation.pathname = "/holdings";
    navigation.push.mockReset();
  });

  it("uses the URL account in the selector and preserves no prior-account resource in a switch", async () => {
    const user = userEvent.setup();
    navigation.pathname = "/holdings/old-position";
    navigation.query = `account=${first.id}&snapshot=old&cursor=old`;
    render(<View />);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Portfolio account" }),
      second.id,
    );
    expect(navigation.push).toHaveBeenCalledWith(
      `/holdings?account=${second.id}`,
    );
  });

  it("hides a prior server result immediately when its account differs from the current URL", () => {
    const view = render(<View />);
    expect(screen.getByText(`Loaded account ${first.id}`)).toBeVisible();
    navigation.query = `account=${second.id}`;
    view.rerender(<View />);
    expect(
      screen.queryByText(`Loaded account ${first.id}`),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the selected portfolio",
    );
    view.rerender(<View loadedAccount={second.id} />);
    expect(screen.getByText(`Loaded account ${second.id}`)).toBeVisible();
  });

  it("unmounts account-owned form state across rapid A to B to A and late B server delivery", async () => {
    const user = userEvent.setup();
    const view = render(<View />);
    await user.type(
      screen.getByRole("textbox", { name: "Account draft" }),
      "A-only draft",
    );
    navigation.query = `account=${second.id}`;
    view.rerender(<View />);
    navigation.query = `account=${first.id}`;
    view.rerender(<View loadedAccount={second.id} />);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    view.rerender(<View />);
    expect(screen.getByRole("textbox", { name: "Account draft" })).toHaveValue(
      "",
    );
  });

  it("does not expose the configured account after a duplicate explicit selection", () => {
    navigation.query = `account=${first.id}&account=${second.id}`;
    render(<View />);
    expect(
      screen.queryByText(`Loaded account ${first.id}`),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("offers a meaningful empty account selector without requiring a summary", () => {
    render(
      <AccountProvider accounts={[]}>
        <AccountSelector />
      </AccountProvider>,
    );
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(
      screen.getByRole("option", { name: "No authorized accounts" }),
    ).toBeInTheDocument();
  });

  it("opens private templates without an account and still rejects an explicit invalid account", () => {
    navigation.pathname = "/pies";
    const view = render(
      <AccountProvider accounts={[]}>
        <AccountSelector />
        <AccountView accountId={null}>
          <p>Private template list</p>
        </AccountView>
      </AccountProvider>,
    );
    expect(screen.getByText("Private template list")).toBeVisible();
    expect(
      screen.getByRole("option", { name: "Private templates" }),
    ).toBeInTheDocument();
    navigation.query = "account=invalid";
    view.rerender(
      <AccountProvider accounts={[]}>
        <AccountSelector />
        <AccountView accountId={null}>
          <p>Private template list</p>
        </AccountView>
      </AccountProvider>,
    );
    expect(screen.queryByText("Private template list")).not.toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Account unavailable" }),
    ).toBeInTheDocument();
  });
});
