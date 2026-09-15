import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { account, id, other, run } from "./projection-fixtures";
const mocks = vi.hoisted(() => ({
  access: vi.fn(),
  clients: vi.fn(),
  accounts: vi.fn(),
  getRun: vi.fn(),
  listRuns: vi.fn(),
  goal: vi.fn(),
  controls: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("../lib/auth", () => ({ requireWebAccess: mocks.access }));
vi.mock("../lib/projection-adapter", async (original) => ({
  ...(await original<typeof import("../lib/projection-adapter")>()),
  projectionClients: mocks.clients,
}));
vi.mock("../components/projection-job-controls", () => ({
  ProjectionJobControls: (props: unknown) => {
    mocks.controls(props);
    return <span>Status controls</span>;
  },
}));
vi.mock("../components/account-context", () => ({
  AccountView: ({ children }: { children: ReactNode }) => <>{children}</>,
  AccountRequired: () => <p>Choose a valid account</p>,
}));
vi.mock("../components/navigation-intent", () => ({
  default: ({
    prefetch: _prefetch,
    ...props
  }: import("react").ComponentProps<"a"> & { prefetch?: boolean }) => {
    void _prefetch;
    return <a {...props} />;
  },
}));
import { ProjectionPage } from "../components/projection-page";
const response = <T,>(data: T) => ({ data, notModified: false, etag: null });
beforeEach(() => {
  vi.clearAllMocks();
  mocks.access.mockResolvedValue({
    isDemo: false,
    principal: {
      scopes: [
        "portfolio:read",
        "analytics:read",
        "projections:write",
        "goals:write",
      ],
    },
  });
  mocks.clients.mockResolvedValue({
    portfolio: { listAccounts: mocks.accounts },
    projections: {
      get_projection_run: mocks.getRun,
      list_projection_runs: mocks.listRuns,
      get_goal_analysis: mocks.goal,
    },
  });
  mocks.accounts.mockResolvedValue([
    { id: account, reporting_currency: "EUR" },
  ]);
  mocks.getRun.mockResolvedValue(response(run));
  mocks.listRuns.mockResolvedValue(
    response({ items: [run], total: 1, next_cursor: null, limit: 25 }),
  );
});
describe("projection server workspace authorization and availability", () => {
  it("denies missing read scopes before obtaining clients or parsing cursors", async () => {
    mocks.access.mockResolvedValue({
      isDemo: false,
      principal: { scopes: ["portfolio:read"] },
    });
    render(
      await ProjectionPage({
        search: { account, run: id, point_cursor: "canary" },
      }),
    );
    expect(
      screen.getByText("Projection read access required"),
    ).toBeInTheDocument();
    expect(mocks.clients).not.toHaveBeenCalled();
    expect(mocks.getRun).not.toHaveBeenCalled();
  });
  it("does not fall back from an explicitly inaccessible account", async () => {
    render(await ProjectionPage({ search: { account: other, run: id } }));
    expect(screen.getByText("Choose a valid account")).toBeInTheDocument();
    expect(mocks.getRun).not.toHaveBeenCalled();
    expect(mocks.listRuns).not.toHaveBeenCalled();
  });
  it("forwards saved signed point selection and exposes only operational metadata to client controls", async () => {
    render(
      await ProjectionPage({
        search: { account, run: id, point_cursor: "signed_cursor" },
      }),
    );
    expect(mocks.getRun).toHaveBeenCalledWith(id, {
      point_limit: 25,
      point_cursor: "signed_cursor",
    });
    expect(mocks.controls.mock.calls[0][0]).toEqual({
      run: { id, account_id: account, state: "queued" },
      canWrite: true,
    });
    expect(
      screen.getByText(/Status refresh does not create another run/),
    ).toBeInTheDocument();
    expect(mocks.listRuns).not.toHaveBeenCalled();
  });
  it("suppresses foreign result metadata after an account mismatch", async () => {
    mocks.getRun.mockResolvedValue(
      response({ ...run, account_id: other, failure_code: "PRIVATE_CANARY" }),
    );
    render(await ProjectionPage({ search: { account, run: id } }));
    expect(
      screen.getByText("Projection workspace unavailable"),
    ).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE_CANARY")).not.toBeInTheDocument();
    expect(mocks.controls).not.toHaveBeenCalled();
  });
  it("shows expired availability without a substituted forecast or zero balance", async () => {
    mocks.getRun.mockResolvedValue(
      response({
        ...run,
        state: "expired",
        result_availability: "expired",
        completed_at: run.created_at,
      }),
    );
    render(await ProjectionPage({ search: { account, run: id } }));
    expect(
      screen.getByText(/No forecast or zero balance is substituted/),
    ).toBeInTheDocument();
    expect(screen.queryByText("0 EUR")).not.toBeInTheDocument();
  });
});
