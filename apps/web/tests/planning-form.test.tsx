import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreateContributionPlanRequest } from "@trading212/api-contracts";

import { PlanningForm } from "../components/planning-form";
import type { PlanningTargetOption } from "../lib/planning-types";

const mocks = vi.hoisted(() => ({
  command: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/planning-actions", () => ({
  submitPlanningCommand: mocks.command,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));

const accountId = "10000000-0000-4000-8000-000000000001";
const pieId = "10000000-0000-4000-8000-000000000002";
const versionId = "10000000-0000-4000-8000-000000000003";
const snapshotId = "10000000-0000-4000-8000-000000000004";
const nodeId = "10000000-0000-4000-8000-000000000005";
const holdingId = "10000000-0000-4000-8000-000000000006";
const groupId = "10000000-0000-4000-8000-000000000007";
const targets: PlanningTargetOption[] = [
  {
    id: groupId,
    key: "equity",
    holding_id: null,
    node: { key: "equity", kind: "group", name: "Equity", weight: "1" },
  },
  {
    id: nodeId,
    key: "holding-a",
    holding_id: holdingId,
    node: {
      key: "holding-a",
      parent_key: "equity",
      kind: "holding",
      name: "Holding A",
      weight: "1",
      holding: { state: "resolved" },
    },
  },
];
const initial: CreateContributionPlanRequest = {
  account_id: accountId,
  virtual_portfolio_id: pieId,
  target_version_id: versionId,
  snapshot_id: snapshotId,
  contribution: { amount: "20", currency: "EUR" },
  mode: "global",
  allocation_constraints: [],
  holding_constraints: [],
  eligible_holding_ids: null,
  excluded_holding_ids: [],
  restricted_group_ids: [],
  listing_preferences: [],
};

describe("contribution request editing", () => {
  beforeEach(() => {
    mocks.command.mockReset();
    mocks.push.mockReset();
    mocks.refresh.mockReset();
  });

  it("preserves exact contribution and reuses retry identity without reflecting an upstream exception", async () => {
    const user = userEvent.setup();
    mocks.command.mockRejectedValue(new Error("private-planning-value-canary"));
    render(<PlanningForm initial={initial} targets={targets} />);
    const amount = screen.getByRole("textbox", { name: "Contribution (EUR)" });
    await user.clear(amount);
    await user.type(amount, "20.123456789012345678");
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your inputs are preserved",
    );
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    expect(mocks.command).toHaveBeenCalledTimes(2);
    expect(mocks.command.mock.calls[0][0].idempotency_key).toBe(
      mocks.command.mock.calls[1][0].idempotency_key,
    );
    expect(mocks.command.mock.calls[1][0].body.contribution.amount).toBe(
      "20.123456789012345678",
    );
    expect(amount).toHaveValue("20.123456789012345678");
    expect(document.documentElement.outerHTML).not.toContain(
      "private-planning-value-canary",
    );
    expect(mocks.refresh).not.toHaveBeenCalled();
    await user.type(amount, "0");
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    expect(mocks.command.mock.calls[2][0].idempotency_key).not.toBe(
      mocks.command.mock.calls[0][0].idempotency_key,
    );
  });

  it("uses holding identities for selection and node identities for constraints and restrictions", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "VALIDATION_FAILED",
      message: "Review request.",
    });
    render(<PlanningForm initial={initial} targets={targets} />);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Optimization mode" }),
      "restricted",
    );
    await user.click(screen.getByRole("checkbox", { name: "Equity" }));
    await user.click(
      screen.getByText("Eligible holdings, exclusions and listing preferences"),
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Choose an explicit set of eligible holdings",
      }),
    );
    await user.click(screen.getByText("Allocation and hierarchy constraints"));
    await user.click(
      screen.getByRole("button", { name: "Add allocation constraint" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    const body = mocks.command.mock.calls[0][0].body;
    expect(body.eligible_holding_ids).toEqual([holdingId]);
    expect(body.restricted_group_ids).toEqual([groupId]);
    expect(body.allocation_constraints[0].node_id).toBe(nodeId);
  });

  it("preserves all MCP holding overrides and uses the immutable request precondition on revision", async () => {
    const user = userEvent.setup();
    const etag = `"${pieId}:4"`;
    mocks.command.mockResolvedValue({
      ok: false,
      code: "REVISION_MISMATCH",
      message: "Reload the current revision.",
    });
    const holdingConstraints = [
      {
        holding_id: holdingId,
        minimum_amount: "0.012345678901234567",
        value_increment: "0.000000000000000001",
        maximum_post_weight: "0.4",
      },
    ];
    render(
      <PlanningForm
        initial={{ ...initial, holding_constraints: holdingConstraints }}
        targets={targets}
        revision={{ planId: pieId, etag }}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Calculate new revision" }),
    );
    expect(
      await screen.findByText("This plan changed in another session"),
    ).toBeVisible();
    expect(mocks.command.mock.calls[0][0]).toMatchObject({
      kind: "revise",
      plan_id: pieId,
      if_match: etag,
      body: { holding_constraints: holdingConstraints },
    });
    expect(
      screen.getByRole("textbox", {
        name: "Minimum funded amount for override 1",
      }),
    ).toHaveValue(holdingConstraints[0].minimum_amount);
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it("keeps exclusions when enabling explicit eligibility", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "VALIDATION_FAILED",
      message: "Review request.",
    });
    render(
      <PlanningForm
        initial={{ ...initial, excluded_holding_ids: [holdingId] }}
        targets={targets}
      />,
    );
    await user.click(
      screen.getByText("Eligible holdings, exclusions and listing preferences"),
    );
    await user.click(
      screen.getByRole("checkbox", {
        name: "Choose an explicit set of eligible holdings",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    expect(mocks.command.mock.calls[0][0].body).toMatchObject({
      eligible_holding_ids: [],
      excluded_holding_ids: [holdingId],
    });
  });

  it("submits the displayed eligibility default after changing constraint type", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "VALIDATION_FAILED",
      message: "Review request.",
    });
    render(<PlanningForm initial={initial} targets={targets} />);
    await user.click(screen.getByText("Allocation and hierarchy constraints"));
    await user.click(
      screen.getByRole("button", { name: "Add allocation constraint" }),
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Constraint type" }),
      "eligible",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Target scope" }),
      nodeId,
    );
    expect(screen.getByRole("combobox", { name: "Eligibility" })).toHaveValue(
      "yes",
    );
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    expect(
      mocks.command.mock.calls[0][0].body.allocation_constraints[0],
    ).toMatchObject({ node_id: nodeId, kind: "eligible", enabled: true });
  });

  it("prevents a second submission while the durable request is pending", async () => {
    const user = userEvent.setup();
    mocks.command.mockReturnValue(new Promise(() => {}));
    render(<PlanningForm initial={initial} targets={targets} />);
    await user.click(
      screen.getByRole("button", { name: "Calculate contribution plan" }),
    );
    expect(
      screen.getByRole("button", { name: "Queuing plan…" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("textbox", { name: "Contribution (EUR)" }),
    ).toBeDisabled();
    expect(mocks.command).toHaveBeenCalledTimes(1);
  });
});
