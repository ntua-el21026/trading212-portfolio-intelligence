import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  TargetNode,
  TargetVersionResponse,
} from "@trading212/api-contracts";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TargetEditor } from "../components/target-editor";

const mocks = vi.hoisted(() => ({ command: vi.fn(), search: vi.fn() }));
vi.mock("../lib/target-actions", () => ({
  submitTargetCommand: mocks.command,
  searchTargetInstruments: mocks.search,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

function node(
  key: string,
  name: string,
  kind: TargetNode["kind"],
  parent: string | null,
  order: number,
): TargetNode {
  return {
    key,
    name,
    kind,
    parent_key: parent,
    order,
    weight: "0.5",
    holding:
      kind === "holding"
        ? {
            state: "unresolved",
            requested_identifier: { kind: "isin", value: "US0378331005" },
            reason: "Awaiting canonical mapping.",
          }
        : null,
  };
}

const version: TargetVersionResponse = {
  id: "ab8d8050-b902-40b8-a87c-7b69b5417687",
  portfolio_id: "54a2eb45-222e-4093-a3f9-baa05f4bc0b9",
  version_number: 1,
  revision: 1,
  reporting_currency: "EUR",
  effective_at: "2026-09-07T12:00:45.123456Z",
  state: "draft",
  content: {
    nodes: [
      node("a-cash", "Cash", "cash", null, 9),
      node("b-child", "Second child", "holding", "z-group", 7),
      node("z-group", "Equity group", "group", null, 4),
      node("y-child", "First child", "holding", "z-group", 2),
    ],
    constraints: [],
    exclusions: [],
  },
  created_at: "2026-09-07T12:00:00Z",
  updated_at: "2026-09-07T12:00:00Z",
  published_at: null,
  content_digest: null,
  source_version_id: null,
  latest_validation: null,
  flattened_nodes: [],
  effective_weight_rounding_residual: null,
};

function editor(value = version) {
  return (
    <TargetEditor
      key={`${value.id}:${value.revision}`}
      version={value}
      etag={`"${value.id}:${value.revision}"`}
      instruments={[]}
      instrumentTotal={0}
      instrumentCursor={null}
    />
  );
}

function article(name: string): HTMLElement {
  const element = screen
    .getByRole("textbox", { name: `Name for ${name}` })
    .closest("article");
  if (!element) throw new Error("Missing target article.");
  return element;
}

function displayedNames(): string[] {
  return [...document.querySelectorAll(".target-node__heading strong")].map(
    (element) => element.textContent ?? "",
  );
}

describe("target hierarchy order and effective timestamp preservation", () => {
  beforeEach(() => {
    mocks.command.mockReset();
    mocks.search.mockReset();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "TARGETS_UNAVAILABLE",
      message: "Retry safely.",
      fields: [],
    });
  });

  it("preserves the exact existing UTC timestamp when only content changes", async () => {
    const user = userEvent.setup();
    render(editor());
    await user.type(
      screen.getByRole("textbox", { name: "Name for Cash" }),
      " reserve",
    );
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(mocks.command.mock.calls[0][0].body.effective_at).toBe(
      version.effective_at,
    );
  });

  it("changes the effective instant only after explicit date-field editing", async () => {
    const user = userEvent.setup();
    render(editor());
    fireEvent.change(screen.getByLabelText("Effective from (UTC)"), {
      target: { value: "2026-09-08T14:25" },
    });
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(mocks.command.mock.calls[0][0].body.effective_at).toBe(
      "2026-09-08T14:25:00Z",
    );
  });

  it("renders shuffled source nodes in hierarchy order and moves only siblings", async () => {
    const user = userEvent.setup();
    const view = render(editor());
    expect(displayedNames()).toEqual([
      "Equity group",
      "First child",
      "Second child",
      "Cash",
    ]);
    expect(
      within(article("First child")).getByRole("button", { name: "Move up" }),
    ).toBeDisabled();
    await user.click(
      within(article("Second child")).getByRole("button", { name: "Move up" }),
    );
    expect(displayedNames()).toEqual([
      "Equity group",
      "Second child",
      "First child",
      "Cash",
    ]);
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    const saved = mocks.command.mock.calls[0][0].body
      .content as typeof version.content;
    const orders = Object.fromEntries(
      saved.nodes.map((item) => [item.key, item.order]),
    );
    expect(orders).toEqual({
      "z-group": 4,
      "b-child": 2,
      "y-child": 7,
      "a-cash": 9,
    });
    const reloaded = {
      ...version,
      revision: 2,
      content: {
        ...saved,
        nodes: [...saved.nodes].sort((a, b) => (a.key < b.key ? -1 : 1)),
      },
    };
    view.rerender(editor(reloaded));
    expect(displayedNames()).toEqual([
      "Equity group",
      "Second child",
      "First child",
      "Cash",
    ]);
  });

  it("keeps unrelated ordering when removing a child and adding a root", async () => {
    const user = userEvent.setup();
    render(editor());
    await user.click(
      within(article("First child")).getByRole("button", {
        name: "Remove holding",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Add group" }));
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    const saved = mocks.command.mock.calls[0][0].body
      .content as typeof version.content;
    expect(saved.nodes.map((item) => [item.name, item.order])).toEqual([
      ["Equity group", 4],
      ["Second child", 7],
      ["Cash", 9],
      ["New group", 10],
    ]);
  });

  it("keeps cyclic and orphan draft nodes visible exactly once", () => {
    render(
      editor({
        ...version,
        content: {
          nodes: [
            node("cycle-a", "Cycle A", "group", "cycle-b", 0),
            node("cycle-b", "Cycle B", "group", "cycle-a", 0),
            node("orphan", "Orphan", "holding", "missing", 0),
          ],
        },
      }),
    );
    expect(displayedNames()).toEqual(["Cycle A", "Cycle B", "Orphan"]);
    expect(screen.getAllByRole("button", { name: "Move up" })).toHaveLength(3);
  });

  it("appends within the bounded root-order range without changing child order", async () => {
    const user = userEvent.setup();
    render(
      editor({
        ...version,
        content: {
          ...version.content,
          nodes: version.content.nodes.map((item) =>
            item.key === "a-cash" ? { ...item, order: 255 } : item,
          ),
        },
      }),
    );
    await user.click(screen.getByRole("button", { name: "Add group" }));
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    const saved = mocks.command.mock.calls[0][0].body
      .content as typeof version.content;
    expect(saved.nodes.map((item) => [item.name, item.order])).toEqual([
      ["Equity group", 0],
      ["First child", 2],
      ["Second child", 7],
      ["Cash", 1],
      ["New group", 2],
    ]);
  });
});
