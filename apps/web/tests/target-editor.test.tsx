import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TargetVersionResponse } from "@trading212/api-contracts";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TargetEditor } from "../components/target-editor";

const mocks = vi.hoisted(() => ({
  command: vi.fn(),
  search: vi.fn(),
  refresh: vi.fn(),
  push: vi.fn(),
}));
vi.mock("../lib/target-actions", () => ({
  submitTargetCommand: mocks.command,
  searchTargetInstruments: mocks.search,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: mocks.refresh, push: mocks.push }),
}));

const version: TargetVersionResponse = {
  id: "c44a288c-39b2-4272-aa4a-bdc3cce135db",
  portfolio_id: "da995ccb-75df-4804-ae81-1845a6ceda7e",
  version_number: 1,
  revision: 1,
  reporting_currency: "EUR",
  effective_at: "2026-09-07T12:00:00Z",
  state: "draft",
  content: {
    nodes: [
      {
        key: "cash",
        parent_key: null,
        kind: "cash",
        name: "EUR cash",
        order: 0,
        weight: "1",
        holding: null,
      },
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

describe("target editing security and recovery", () => {
  beforeEach(() => {
    mocks.command.mockReset();
    mocks.search.mockReset();
    mocks.refresh.mockReset();
    mocks.push.mockReset();
  });

  it("preserves exact unsaved values after an unknown failure and reuses the retry identity", async () => {
    const user = userEvent.setup();
    const canary = "target-upstream-secret-canary";
    mocks.command.mockRejectedValue(new Error(canary));
    render(
      <TargetEditor
        version={version}
        etag={`"${version.id}:1"`}
        instruments={[]}
        instrumentTotal={0}
        instrumentCursor={null}
      />,
    );
    const weight = screen.getByRole("textbox", { name: "Weight for EUR cash" });
    await user.clear(weight);
    await user.type(weight, "0.123456789012345678");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(/Your edits are preserved; retry/),
    ).toBeVisible();
    expect(weight).toHaveValue("0.123456789012345678");
    expect(document.documentElement.outerHTML).not.toContain(canary);
    expect(
      screen.getByRole("button", { name: "Validate target" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Publish version" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(mocks.command).toHaveBeenCalledTimes(2);
    const first = mocks.command.mock.calls[0][0];
    const second = mocks.command.mock.calls[1][0];
    expect(first.idempotency_key).toBe(second.idempotency_key);
    expect(first.body.content.nodes[0].weight).toBe("0.123456789012345678");
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it("keeps a conflicting edit visible with an actionable revision warning", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "REVISION_MISMATCH",
      message: "The target revision has changed.",
      fields: [],
    });
    render(
      <TargetEditor
        version={version}
        etag={`"${version.id}:1"`}
        instruments={[]}
        instrumentTotal={0}
        instrumentCursor={null}
      />,
    );
    const name = screen.getByRole("textbox", { name: "Name for EUR cash" });
    await user.clear(name);
    await user.type(name, "Retained cash edit");
    await user.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText("This Pie changed in another session"),
    ).toBeVisible();
    expect(
      screen.getByRole("textbox", { name: "Name for Retained cash edit" }),
    ).toHaveValue("Retained cash edit");
    expect(
      screen.getByText(/Copy any unsaved changes before reloading/),
    ).toBeVisible();
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it("locks published financial content while retaining the internal archive action", () => {
    render(
      <TargetEditor
        version={{
          ...version,
          state: "active",
          published_at: version.created_at,
          content_digest: "a".repeat(64),
        }}
        etag={`"${version.id}:3"`}
        instruments={[]}
        instrumentTotal={0}
        instrumentCursor={null}
      />,
    );
    expect(
      screen.getByText("Published target content is locked"),
    ).toBeVisible();
    expect(
      screen.getByRole("textbox", { name: "Weight for EUR cash" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add holding" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Save draft" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Publish version" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Archive version" }),
    ).toBeEnabled();
    expect(mocks.command).not.toHaveBeenCalled();
  });

  it("retains an unsaved target while an instrument page fails to load", async () => {
    const user = userEvent.setup();
    mocks.search.mockRejectedValue(new Error("private-catalog-error-canary"));
    render(
      <TargetEditor
        version={version}
        etag={`"${version.id}:1"`}
        instruments={[]}
        instrumentTotal={101}
        instrumentCursor="opaque_cursor"
      />,
    );
    const weight = screen.getByRole("textbox", { name: "Weight for EUR cash" });
    await user.clear(weight);
    await user.type(weight, "0.5");
    await user.click(
      screen.getByText("Find instruments for holding targets", { exact: true }),
    );
    await user.click(screen.getByRole("button", { name: "Next instruments" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your target edits are preserved.",
    );
    expect(weight).toHaveValue("0.5");
    expect(document.documentElement.outerHTML).not.toContain(
      "private-catalog-error-canary",
    );
    expect(mocks.command).not.toHaveBeenCalled();
    expect(mocks.search).toHaveBeenCalledWith({
      query: "",
      cursor: "opaque_cursor",
    });
  });

  it("distinguishes retained historical validation from a valid current draft", () => {
    render(
      <TargetEditor
        version={{
          ...version,
          revision: 2,
          latest_validation: {
            id: "46f96955-7e2d-41d9-9c45-172fb986ab20",
            version_id: version.id,
            input_revision: 1,
            result_revision: 1,
            input_digest: "a".repeat(64),
            result_digest: "a".repeat(64),
            valid: true,
            normalize_requested: false,
            normalization_applied: false,
            issues: [],
            adjustments: [],
            evaluated_at: version.created_at,
            method: "target_validation_v1",
            method_version: "1.0.0",
          },
        }}
        etag={`"${version.id}:2"`}
        instruments={[]}
        instrumentTotal={0}
        instrumentCursor={null}
      />,
    );
    expect(
      screen.getByText("Historical validation", { exact: true }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Publish version" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Validate target" }),
    ).toBeEnabled();
  });
});
