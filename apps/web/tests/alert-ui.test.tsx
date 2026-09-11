import { webcrypto } from "node:crypto";
import { AlertRuleDefinitionSchema } from "@trading212/api-contracts";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AlertEditor } from "../components/alert-editor";
import {
  AlertDefinition,
  AlertEventPanel,
  AlertRulePanel,
} from "../components/alert-history";
import {
  AlertCommandScope,
  AlertEventCommands,
  AlertRuleCommands,
  AlertVersionActivation,
} from "../components/alert-commands";
import { AlertQueryBoundary } from "../components/alert-query-boundary";
import {
  ALERT_METRICS,
  alertDefinitionFromForm,
} from "../lib/alert-editor-model";
import { parseAlertQuery } from "../lib/alert-query";
import {
  alertAccount,
  alertDestination,
  alertEvent,
  alertNow,
  alertRule,
} from "./alert-fixtures";

const mocks = vi.hoisted(() => ({
  command: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  search: "",
}));
vi.mock("../lib/alert-actions", () => ({ submitAlertCommand: mocks.command }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

function editor(rule?: typeof alertRule) {
  return (
    <AlertEditor
      accountId={alertAccount}
      rule={rule}
      destinations={[alertDestination]}
      now={alertNow}
      canWrite
    />
  );
}

describe("alert rule editing and retained history", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.search = "";
    vi.stubGlobal("crypto", webcrypto);
  });
  afterEach(() => vi.unstubAllGlobals());
  it.each([
    ["active", "Next scheduled evaluation:"],
    ["draft", "Draft rule. Activate a saved version to schedule evaluations."],
    [
      "paused",
      "Scheduling paused. Activate a saved version to resume future evaluations.",
    ],
    ["archived", "Rule archived. No future evaluations are scheduled."],
  ] as const)(
    "describes %s scheduling without presenting a retained cursor as future work",
    (lifecycle, text) => {
      render(
        <AlertRulePanel
          rule={{ ...alertRule, lifecycle, next_scheduled_for: alertNow }}
          query={parseAlertQuery({})}
          canWrite
        />,
      );
      expect(
        screen.getByText(text, { exact: lifecycle !== "active" }),
      ).toBeVisible();
      if (lifecycle !== "active")
        expect(
          screen.queryByText(/Next scheduled evaluation:/),
        ).not.toBeInTheDocument();
    },
  );
  it("shows a flattened dividend minimum with its exact decimal and currency in aligned definition rows", () => {
    const definition = AlertRuleDefinitionSchema.parse({
      ...alertRule.latest_version.definition,
      predicate: {
        family: "dividend_received",
        metric: "positive_dividend",
        minimum_net_amount: "12.000000000000000001",
        currency: "EUR",
      },
    });
    const view = render(<AlertDefinition definition={definition} />);
    const value = screen.getByText("12.000000000000000001 EUR", {
      exact: true,
    });
    expect(value.tagName).toBe("DD");
    expect(value.previousElementSibling).toHaveTextContent(
      "Minimum Net Amount",
    );
    expect(value.parentElement?.tagName).toBe("DL");
    expect(view.container).not.toHaveTextContent("[object Object]");
  });
  it("hydrates the server selection before rejecting a raw prototype key without recovery errors", async () => {
    mocks.search = "__proto__=x";
    const content = (
      <AlertQueryBoundary fallback={<p>Invalid alert selection</p>}>
        <p>Server selection</p>
      </AlertQueryBoundary>
    );
    const container = document.createElement("div");
    container.innerHTML = renderToString(content);
    expect(container.textContent).toBe("Server selection");
    document.body.append(container);
    const recovered = vi.fn();
    let root!: ReturnType<typeof hydrateRoot>;
    await act(async () => {
      root = hydrateRoot(container, content, { onRecoverableError: recovered });
    });
    expect(container.textContent).toBe("Invalid alert selection");
    expect(recovered).not.toHaveBeenCalled();
    await act(async () => root.unmount());
    container.remove();
  });
  it("replaces server content when the actual URL contains a stripped prototype key", () => {
    const view = render(
      <AlertQueryBoundary fallback={<p>Invalid alert selection</p>}>
        <p>Authorized history</p>
      </AlertQueryBoundary>,
    );
    expect(screen.getByText("Authorized history")).toBeVisible();
    mocks.search = "__proto__=x";
    view.rerender(
      <AlertQueryBoundary fallback={<p>Invalid alert selection</p>}>
        <p>Authorized history</p>
      </AlertQueryBoundary>,
    );
    expect(screen.getByText("Invalid alert selection")).toBeVisible();
    expect(screen.queryByText("Authorized history")).not.toBeInTheDocument();
  });
  it("prevents a second event command until the refreshed revision is usable", async () => {
    const user = userEvent.setup();
    let finishRefresh!: () => void;
    mocks.refresh.mockReturnValue(
      new Promise<void>((resolve) => {
        finishRefresh = resolve;
      }),
    );
    const acknowledgment = {
      id: "00000000-0000-4000-8000-000000000099",
      event_id: alertEvent.id,
      principal_id: "00000000-0000-4000-8000-000000000098",
      acknowledged_at: alertNow,
      event_revision: 2,
      note: null,
    };
    mocks.command.mockResolvedValueOnce({
      ok: true,
      kind: "acknowledgment",
      value: acknowledgment,
    });
    const view = render(
      <AlertEventCommands key="revision-1" event={alertEvent} canWrite />,
    );
    await user.click(screen.getByRole("button", { name: "Acknowledge event" }));
    expect(mocks.refresh).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("button", { name: "Resolve event" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Resolve event" }));
    expect(mocks.command).toHaveBeenCalledOnce();
    view.rerender(
      <AlertEventCommands
        key="revision-2"
        event={{ ...alertEvent, revision: 2, acknowledgment }}
        canWrite
      />,
    );
    await act(async () => finishRefresh());
    mocks.command.mockResolvedValueOnce({
      ok: false,
      code: "RATE_LIMITED",
      message: "Retry later.",
      fields: [],
    });
    await user.click(screen.getByRole("button", { name: "Resolve event" }));
    expect(mocks.command.mock.calls[1][0]).toMatchObject({
      kind: "resolve",
      if_match: `"${alertEvent.id}:2"`,
    });
  });
  it("blocks sibling version and editor commands until the shared rule refresh completes", async () => {
    const user = userEvent.setup();
    let finishCommand!: (value: unknown) => void;
    let finishRefresh!: () => void;
    mocks.command.mockReturnValueOnce(
      new Promise((resolve) => {
        finishCommand = resolve;
      }),
    );
    mocks.refresh.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishRefresh = resolve;
      }),
    );
    const second = {
      ...alertRule.latest_version,
      id: "00000000-0000-4000-8000-000000000020",
      version_number: 2,
    };
    const active = {
      ...alertRule,
      revision: 3,
      lifecycle: "active" as const,
      latest_version: second,
      active_version: second,
    };
    const paused = { ...active, revision: 4, lifecycle: "paused" as const };
    function content(rule: typeof alertRule) {
      return (
        <AlertCommandScope>
          <AlertRuleCommands
            key={`actions:${rule.revision}`}
            rule={rule}
            canWrite
          />
          <AlertVersionActivation
            key={`saved:${rule.revision}`}
            rule={rule}
            version={alertRule.latest_version}
            canWrite
          />
          {editor(rule)}
        </AlertCommandScope>
      );
    }
    const view = render(content(active));
    await user.click(screen.getByRole("button", { name: "Pause rule" }));
    const saved = () =>
      screen.getByRole("button", { name: "Activate saved version 1" });
    expect(saved()).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Save new version" }),
    ).toBeDisabled();
    await user.click(saved());
    expect(mocks.command).toHaveBeenCalledOnce();
    await act(async () =>
      finishCommand({ ok: true, kind: "rule", value: paused }),
    );
    expect(mocks.refresh).toHaveBeenCalledOnce();
    expect(saved()).toBeDisabled();
    view.rerender(content(paused));
    expect(saved()).toBeDisabled();
    await act(async () => finishRefresh());
    expect(saved()).toBeEnabled();
    mocks.command.mockResolvedValueOnce({
      ok: false,
      code: "RATE_LIMITED",
      message: "Retry later.",
      fields: [],
    });
    await user.click(saved());
    expect(mocks.command.mock.calls[1][0]).toMatchObject({
      kind: "activate",
      if_match: `"${alertRule.id}:4"`,
      body: { version_id: alertRule.latest_version.id },
    });
  });
  it("covers every accepted metric with only relevant typed fields and exact decimals", () => {
    expect(ALERT_METRICS).toHaveLength(27);
    expect(new Set(ALERT_METRICS.map((item) => item.family)).size).toBe(15);
    for (const metric of ALERT_METRICS) {
      const data = new FormData();
      for (const [key, value] of Object.entries({
        name: "Typed rule",
        severity: "warning",
        quality_policy: "require_complete",
        schedule_kind: "interval",
        anchor_at: alertNow,
        interval_seconds: "300",
        cooldown_seconds: "0",
        comparison: metric.comparison === "boolean" ? "eq" : "gte",
        threshold:
          metric.comparison === "boolean"
            ? "true"
            : metric.comparison === "integer"
              ? "2"
              : "0.100000000000000001",
      }))
        data.set(key, value);
      metric.fields.forEach((field, index) => {
        if ("optional" in field && field.optional) return;
        data.set(
          field.key,
          field.kind === "uuid"
            ? `00000000-0000-4000-8000-${String(index + 20).padStart(12, "0")}`
            : field.kind === "boolean"
              ? "false"
              : field.kind === "integer"
                ? "initial" in field
                  ? (field.initial ?? "1")
                  : "1"
                : field.key === "currency"
                  ? "EUR"
                  : "options" in field
                    ? (field.options?.[0] ?? "")
                    : "0.1",
        );
      });
      data.set("ignored_expression", "not a predicate field");
      const definition = alertDefinitionFromForm(data, metric);
      expect(definition.predicate.metric).toBe(metric.metric);
      expect(definition.predicate).not.toHaveProperty("ignored_expression");
      if (metric.comparison === "decimal")
        expect(definition.predicate).toHaveProperty(
          "threshold",
          "0.100000000000000001",
        );
      if (metric.comparison === "event")
        expect(definition.predicate).not.toHaveProperty("threshold");
    }
  });
  it("reuses a failed immutable command identity, keeps edits and does not activate", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "REVISION_MISMATCH",
      message: "Refresh the current revision.",
      fields: [],
    });
    render(editor(alertRule));
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    expect(await screen.findByText("REVISION_MISMATCH")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    expect(mocks.command.mock.calls[0]).toEqual(mocks.command.mock.calls[1]);
    expect(mocks.command.mock.calls[0][0]).toMatchObject({
      kind: "create_version",
      rule_id: alertRule.id,
      if_match: `"${alertRule.id}:1"`,
      body: {
        definition: { predicate: { threshold: "0.100000000000000001" } },
      },
    });
    expect(screen.getByLabelText("Rule name")).toHaveValue(
      alertRule.latest_version.definition.name,
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("switches all family controls without submitting stale hidden references", async () => {
    const user = userEvent.setup();
    render(editor());
    expect(screen.getByLabelText("Published target version ID")).toBeVisible();
    await user.selectOptions(
      screen.getByLabelText("Rule family"),
      "report_outcome",
    );
    expect(
      screen.queryByLabelText("Published target version ID"),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Threshold")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Report outcome")).toBeVisible();
    expect(screen.queryByLabelText(/Webhook URL/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /Configured webhook/ }),
    ).toBeDisabled();
  });
  it("does not redirect after a pending submitted command's editor is unmounted", async () => {
    let finish!: (value: unknown) => void;
    mocks.command.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const user = userEvent.setup();
    const view = render(editor(alertRule));
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    view.unmount();
    await act(async () =>
      finish({
        ok: true,
        kind: "version",
        value: { version: alertRule.latest_version, rule_revision: 2 },
      }),
    );
    expect(mocks.push).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
  it("activates only the explicitly reviewed version with its aggregate revision", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: true,
      kind: "rule",
      value: { ...alertRule, lifecycle: "active" },
    });
    render(<AlertRuleCommands rule={alertRule} canWrite />);
    await user.click(
      screen.getByRole("button", { name: "Activate version 1" }),
    );
    expect(mocks.command.mock.calls[0][0]).toMatchObject({
      kind: "activate",
      if_match: `"${alertRule.id}:1"`,
      body: { version_id: alertRule.latest_version.id },
    });
  });
  it("pages every saved version and activates the selected historical version explicitly", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      message: "The rule changed.",
      fields: [],
    });
    const latest = {
      ...alertRule.latest_version,
      id: "00000000-0000-4000-8000-000000000020",
      version_number: 2,
    };
    render(
      <AlertRulePanel
        rule={{
          ...alertRule,
          latest_version: latest,
          version_page: {
            items: [alertRule.latest_version],
            total: 2,
            limit: 1,
            next_cursor: "versions_next",
          },
        }}
        query={parseAlertQuery({
          account: alertAccount,
          rule: alertRule.id,
          evaluation_cursor: "proof_current",
        })}
        canWrite
      />,
    );
    const link = screen.getByRole("link", { name: "Next version page" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("version_cursor=versions_next"),
    );
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("evaluation_cursor=proof_current"),
    );
    await user.click(screen.getByText(/Saved version 1 ·/));
    await user.click(
      screen.getByRole("button", { name: "Activate saved version 1" }),
    );
    expect(mocks.command.mock.calls[0][0]).toMatchObject({
      kind: "activate",
      rule_id: alertRule.id,
      if_match: `"${alertRule.id}:1"`,
      body: { version_id: alertRule.latest_version.id },
    });
  });
  it("preserves saved destinations outside the current metadata page", async () => {
    const user = userEvent.setup();
    const missing = "00000000-0000-4000-8000-000000000099";
    mocks.command.mockResolvedValue({
      ok: false,
      message: "Retry the same command.",
      fields: [],
    });
    const rule = {
      ...alertRule,
      latest_version: {
        ...alertRule.latest_version,
        definition: {
          ...alertRule.latest_version.definition,
          destination_ids: [missing],
        },
      },
    };
    render(editor(rule));
    expect(
      screen.getByRole("checkbox", {
        name: new RegExp(`Keep saved destination ${missing}`),
      }),
    ).toBeChecked();
    await user.click(screen.getByRole("button", { name: "Save new version" }));
    expect(
      mocks.command.mock.calls[0][0].body.definition.destination_ids,
    ).toEqual([missing]);
  });
  it("keeps expired proof, independent acknowledgment and unavailable delivery explicit", () => {
    render(<AlertEventPanel event={alertEvent} canWrite />);
    expect(screen.getByText("Evaluation proof unavailable")).toBeVisible();
    expect(screen.getByText(/No conclusive decision/)).toBeVisible();
    expect(
      screen.getByText(/The licensed retention deadline has passed/),
    ).toBeVisible();
    expect(screen.getByText(/Webhook · Unavailable/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Acknowledge event" }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Resolve event" })).toBeEnabled();
  });
  it("provides traversal of earlier evaluations within rule detail", () => {
    render(
      <AlertRulePanel
        rule={{
          ...alertRule,
          evaluation_page: {
            items: [alertEvent.evaluation],
            total: 2,
            limit: 1,
            next_cursor: "proof_next",
          },
        }}
        query={parseAlertQuery({
          account: alertAccount,
          rule: alertRule.id,
          family: "cash_threshold",
        })}
        canWrite={false}
      />,
    );
    const link = screen.getByRole("link", { name: "Next evaluation page" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("evaluation_cursor=proof_next"),
    );
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("family=cash_threshold"),
    );
  });
});
