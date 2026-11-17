import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode, useState } from "react";

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
  documentNavigate: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.query),
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push }),
}));
vi.mock("../lib/account-navigation", () => ({
  navigateAccountDocument: navigation.documentNavigate,
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
    navigation.documentNavigate.mockReset();
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
    expect(navigation.documentNavigate).toHaveBeenCalledWith(
      `/holdings?account=${second.id}`,
    );
    expect(navigation.push).not.toHaveBeenCalled();
    expect(
      screen.queryByText(`Loaded account ${first.id}`),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the selected portfolio",
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

// Unit model only: genuine browser cancellation/history remains an independent gate.
describe("pending account intent and history ownership", () => {
  let originalHref: string;
  beforeEach(() => {
    originalHref = window.location.href;
    navigation.query = `account=${first.id}`;
    navigation.pathname = "/";
    navigation.push.mockReset();
    navigation.documentNavigate.mockReset();
    window.history.replaceState({ __NA: true }, "", `/?account=${first.id}`);
  });
  afterEach(() => {
    window.history.replaceState(null, "", originalHref);
  });

  function historyTarget(pathname: string, query: string) {
    // Next hooks expose the target URL after its native history traversal.
    navigation.pathname = pathname;
    navigation.query = query;
    window.history.replaceState({ __NA: true }, "", `${pathname}?${query}`);
    window.dispatchEvent(
      new PopStateEvent("popstate", { state: window.history.state }),
    );
  }

  it("restores the primary history account after pending secondary intent and masks a late secondary payload", async () => {
    const user = userEvent.setup();
    const view = render(<View />);
    await user.type(
      screen.getByRole("textbox", { name: "Account draft" }),
      "A-only draft",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Portfolio account" }),
      second.id,
    );
    expect(navigation.documentNavigate).toHaveBeenCalledExactlyOnceWith(
      `/?account=${second.id}`,
    );
    expect(
      screen.queryByText(`Loaded account ${first.id}`),
    ).not.toBeInTheDocument();
    expect(
      view.container.querySelectorAll("[data-portfolio-account]"),
    ).toHaveLength(0);
    expect(
      screen.queryByRole("textbox", { name: "Account draft" }),
    ).not.toBeInTheDocument();

    act(() => historyTarget("/holdings", `account=${first.id}`));
    view.rerender(<View />);
    expect(
      screen.getByRole("combobox", { name: "Portfolio account" }),
    ).toHaveValue(first.id);
    expect(
      view.container.querySelector("[data-portfolio-account]"),
    ).toHaveAttribute("data-portfolio-account", first.id);
    expect(screen.getByText(`Loaded account ${first.id}`)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Account draft" })).toHaveValue(
      "",
    );

    view.rerender(<View loadedAccount={second.id} />);
    expect(
      screen.getByRole("combobox", { name: "Portfolio account" }),
    ).toHaveValue(first.id);
    expect(
      view.container.querySelectorAll("[data-portfolio-account]"),
    ).toHaveLength(0);
    expect(
      screen.queryByText(`Loaded account ${second.id}`),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Account draft" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the selected portfolio",
    );

    view.rerender(<View />);
    expect(screen.getByText(`Loaded account ${first.id}`)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Account draft" })).toHaveValue(
      "",
    );
    expect(navigation.documentNavigate).toHaveBeenCalledTimes(1);
    expect(navigation.push).not.toHaveBeenCalled();
  });

  it.each([
    ["malformed", "account=invalid"],
    ["duplicate", `account=${first.id}&account=${second.id}`],
    ["foreign", "account=f791a374-cc3e-4e73-9168-a120c0d54cec"],
  ])(
    "rejects a %s history account after pending secondary intent without exposing late account payloads",
    async (_label, query) => {
      const user = userEvent.setup();
      const view = render(<View />);
      await user.selectOptions(
        screen.getByRole("combobox", { name: "Portfolio account" }),
        second.id,
      );
      act(() => historyTarget("/holdings", query));
      for (const loadedAccount of [second.id, first.id]) {
        view.rerender(<View loadedAccount={loadedAccount} />);
        expect(
          screen.getByRole("combobox", { name: "Portfolio account" }),
        ).toHaveValue("");
        expect(
          view.container.querySelectorAll("[data-portfolio-account]"),
        ).toHaveLength(0);
        expect(
          screen.queryByText(`Loaded account ${loadedAccount}`),
        ).not.toBeInTheDocument();
        expect(
          screen.queryByRole("textbox", { name: "Account draft" }),
        ).not.toBeInTheDocument();
      }
      expect(navigation.documentNavigate).toHaveBeenCalledTimes(1);
      expect(navigation.push).not.toHaveBeenCalled();
    },
  );

  it("removes its history listener when the provider unmounts, including StrictMode cleanup", () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    try {
      const view = render(
        <StrictMode>
          <View />
        </StrictMode>,
      );
      const historyRegistrations = add.mock.calls.filter(
        ([type]) => type === "popstate",
      );
      expect(historyRegistrations.length).toBeGreaterThan(0);
      view.unmount();
      for (const [, listener] of historyRegistrations) {
        expect(
          remove.mock.calls.some(
            ([type, removed]) => type === "popstate" && removed === listener,
          ),
        ).toBe(true);
      }
    } finally {
      add.mockRestore();
      remove.mockRestore();
    }
  });
});
