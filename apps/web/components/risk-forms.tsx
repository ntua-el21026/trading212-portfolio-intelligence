"use client";

import {
  useEffect,
  useRef,
  useState,
  useTransition,
  type FormEvent,
} from "react";
import { useRouter } from "next/navigation";
import type {
  RiskDefinitionContent,
  RiskDefinitionResponse,
  RiskVersionResponse,
  RiskRunResponse,
  CreateRiskRunRequest,
  SourceSeriesStatus,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import {
  submitRiskCommand,
  type RiskActionCommand,
  type RiskActionResult,
} from "../lib/risk-actions";
import { riskHref, type RiskQuery } from "../lib/risk-query";
import { useNavigationVersionRef } from "./navigation-intent";

function useRiskCommand(
  done: (result: Extract<RiskActionResult, { ok: true }>) => void,
) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const active = useRef(true);
  const navigation = useNavigationVersionRef();
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function changed() {
    key.current = null;
    setError(null);
  }
  function submit(build: (key: string) => RiskActionCommand) {
    const stamp = navigation.current;
    key.current ??= crypto.randomUUID();
    const command = build(key.current);
    setError(null);
    start(async () => {
      try {
        const result = await submitRiskCommand(command);
        if (!active.current || navigation.current !== stamp) return;
        if (result.ok) {
          key.current = null;
          done(result);
        } else setError(result.message);
      } catch {
        if (active.current && navigation.current === stamp)
          setError(
            "The request could not be completed. Retry preserves its identity.",
          );
      }
    });
  }
  return { pending, error, changed, submit };
}

export interface RiskCalendarOption {
  id: string;
  version: string;
}

export function RiskDefinitionForm({
  accountId,
  query,
  calendars,
  definition,
  version,
  canWrite,
}: Readonly<{
  accountId: string;
  query: RiskQuery;
  calendars: readonly RiskCalendarOption[];
  definition?: RiskDefinitionResponse;
  version?: RiskVersionResponse;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const [content, setContent] = useState<RiskDefinitionContent>(
    () =>
      version?.content ?? {
        name: "Portfolio risk",
        description: "",
        calendar_id: "",
        calendar_version: "",
        frequency: "daily",
        return_kind: "simple",
        annual_risk_free: "0",
        annual_minimum_acceptable_return: "0",
        rolling_window: 20,
        confidence: "0.95",
        horizon: 1,
        regularization: "none",
        shrinkage: "0",
        method_version: "1.0.0",
      },
  );
  const action = useRiskCommand((result) => {
    if (result.kind === "definition")
      router.push(
        riskHref(query, {
          view: "definitions",
          definition: result.value.id,
          version: result.value.current_version_id,
          definitions_cursor: null,
          versions_cursor: null,
        }),
      );
    if (result.kind === "version")
      router.push(
        riskHref(query, {
          view: "definitions",
          definition: result.value.definition_id,
          version: result.value.id,
          versions_cursor: null,
        }),
      );
  });
  const choices = [...calendars];
  if (
    content.calendar_id &&
    !choices.some(
      (item) =>
        item.id === content.calendar_id &&
        item.version === content.calendar_version,
    )
  )
    choices.push({
      id: content.calendar_id,
      version: content.calendar_version,
    });
  const selectedCalendar = choices.findIndex(
    (item) =>
      item.id === content.calendar_id &&
      item.version === content.calendar_version,
  );
  function change(change: Partial<RiskDefinitionContent>) {
    action.changed();
    setContent((current) => ({ ...current, ...change }));
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    action.submit((key) =>
      definition
        ? {
            kind: "create_version",
            definition_id: definition.id,
            idempotency_key: key,
            if_match: `"${definition.id}:${definition.revision}"`,
            body: { content },
          }
        : {
            kind: "create_definition",
            account_id: accountId,
            idempotency_key: key,
            body: { content },
          },
    );
  }
  return (
    <form
      className="target-form"
      onSubmit={submit}
      aria-label={
        definition ? "New risk definition version" : "Create risk definition"
      }
    >
      <fieldset
        disabled={action.pending || !canWrite}
        className="risk-form-fields"
      >
        <legend>
          {definition
            ? `New immutable version, based on version ${version?.version_number ?? definition.revision}`
            : "Risk definition"}
        </legend>
        <label>
          <span>Name</span>
          <input
            value={content.name}
            required
            maxLength={120}
            onChange={(event) => change({ name: event.target.value })}
          />
        </label>
        <label>
          <span>Description</span>
          <textarea
            value={content.description ?? ""}
            maxLength={1024}
            onChange={(event) => change({ description: event.target.value })}
          />
        </label>
        <label>
          <span>Reporting calendar</span>
          <select
            required
            value={selectedCalendar < 0 ? "" : String(selectedCalendar)}
            onChange={(event) => {
              const choice = choices[Number(event.target.value)];
              if (choice)
                change({
                  calendar_id: choice.id,
                  calendar_version: choice.version,
                });
            }}
          >
            <option value="" disabled>
              Select a sourced calendar
            </option>
            {choices.map((choice, index) => (
              <option key={`${choice.id}:${choice.version}`} value={index}>
                {choice.id} · {choice.version}
              </option>
            ))}
          </select>
        </label>
        <p className="muted">
          The chosen calendar must match the reporting calendar in the retained
          historical capture. Source pages identify available calendars.
        </p>
        <label>
          <span>Frequency</span>
          <select
            value={content.frequency ?? "daily"}
            onChange={(event) =>
              change({ frequency: event.target.value as "daily" | "monthly" })
            }
          >
            <option value="daily">Daily</option>
            <option value="monthly">Monthly</option>
          </select>
        </label>
        <label>
          <span>Return convention</span>
          <select
            value={content.return_kind ?? "simple"}
            onChange={(event) =>
              change({ return_kind: event.target.value as "simple" | "log" })
            }
          >
            <option value="simple">Simple returns</option>
            <option value="log">Log returns</option>
          </select>
        </label>
        <p className="muted">Annual rates use fractions: 0.02 means 2%.</p>
        <label>
          <span>Annual risk-free rate</span>
          <input
            inputMode="decimal"
            value={content.annual_risk_free ?? "0"}
            required
            maxLength={40}
            onChange={(event) =>
              change({ annual_risk_free: event.target.value })
            }
          />
        </label>
        <label>
          <span>Annual minimum acceptable return</span>
          <input
            inputMode="decimal"
            value={content.annual_minimum_acceptable_return ?? "0"}
            required
            maxLength={40}
            onChange={(event) =>
              change({ annual_minimum_acceptable_return: event.target.value })
            }
          />
        </label>
        <label>
          <span>Rolling observations</span>
          <input
            type="number"
            min={20}
            max={content.frequency === "monthly" ? 120 : 252}
            step={1}
            value={content.rolling_window ?? 20}
            required
            onChange={(event) =>
              change({ rolling_window: Number(event.target.value) })
            }
          />
        </label>
        <label>
          <span>Tail confidence</span>
          <select
            value={(content.confidence ?? "0.95").replace(/0+$/, "")}
            onChange={(event) => change({ confidence: event.target.value })}
          >
            <option value="0.9">90%</option>
            <option value="0.95">95%</option>
            <option value="0.99">99%</option>
          </select>
        </label>
        <label>
          <span>Tail horizon in periods</span>
          <input
            type="number"
            min={1}
            max={content.frequency === "monthly" ? 12 : 20}
            step={1}
            value={content.horizon ?? 1}
            required
            onChange={(event) =>
              change({ horizon: Number(event.target.value) })
            }
          />
        </label>
        <label>
          <span>Covariance regularization</span>
          <select
            value={content.regularization ?? "none"}
            onChange={(event) =>
              change({
                regularization: event.target.value as
                  "none" | "diagonal_shrinkage",
                ...(event.target.value === "none" ? { shrinkage: "0" } : {}),
              })
            }
          >
            <option value="none">None</option>
            <option value="diagonal_shrinkage">
              Explicit diagonal shrinkage
            </option>
          </select>
        </label>
        <label>
          <span>Shrinkage coefficient (0–1)</span>
          <input
            inputMode="decimal"
            readOnly={content.regularization !== "diagonal_shrinkage"}
            value={content.shrinkage ?? "0"}
            required
            maxLength={40}
            onChange={(event) => change({ shrinkage: event.target.value })}
          />
        </label>
        <Button type="submit" disabled={!choices.length}>
          {action.pending
            ? "Saving definition…"
            : definition
              ? "Save new risk version"
              : "Create risk definition"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Read-only access">
          Saving risk definitions requires risk:write together with portfolio
          and analytics access.
        </Notice>
      ) : null}
      {!choices.length ? (
        <Notice title="No sourced calendar available">
          Register a licensed historical source before defining its risk
          calendar.
        </Notice>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}

export function RiskRunForm({
  accountId,
  query,
  prepared,
  sources,
  canWrite,
}: Readonly<{
  accountId: string;
  query: RiskQuery;
  prepared: Omit<CreateRiskRunRequest, "assets">;
  sources: readonly SourceSeriesStatus[];
  canWrite: boolean;
}>) {
  const router = useRouter();
  const [selected, setSelected] = useState<
    { instrument_id: string; series_id: string; label: string }[]
  >([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const action = useRiskCommand((result) => {
    if (result.kind === "run")
      router.push(
        riskHref(query, {
          view: "result",
          run: result.value.id,
          runs_cursor: null,
        }),
      );
  });
  function toggle(source: SourceSeriesStatus) {
    const row = source.series;
    if (!row.instrument_id || row.basis !== "total_return") return;
    action.changed();
    setSelectionError(null);
    if (selected.some((item) => item.series_id === row.id)) {
      setSelected((items) => items.filter((item) => item.series_id !== row.id));
      return;
    }
    if (
      selected.length >= 32 ||
      selected.some((item) => item.instrument_id === row.instrument_id)
    ) {
      setSelectionError(
        "Select at most 32 assets and one return series for each instrument.",
      );
      return;
    }
    setSelected((items) => [
      ...items,
      {
        instrument_id: row.instrument_id!,
        series_id: row.id,
        label: row.provider_key,
      },
    ]);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    action.submit((key) => ({
      kind: "create_run",
      account_id: accountId,
      idempotency_key: key,
      body: {
        ...prepared,
        assets: selected.map(({ instrument_id, series_id }) => ({
          instrument_id,
          series_id,
        })),
      },
    }));
  }
  return (
    <form
      className="target-form"
      onSubmit={submit}
      aria-label="Create risk run"
    >
      <fieldset disabled={action.pending || !canWrite}>
        <legend>Optional asset covariance universe</legend>
        <p>
          Only explicitly sourced total-return series are eligible. Leaving the
          selection empty still computes observed portfolio statistics.
          Incomplete modeled exposure remains unavailable.
        </p>
        {sources.map((source) => (
          <label key={source.series.id} className="risk-source-choice">
            <input
              type="checkbox"
              checked={selected.some(
                (row) => row.series_id === source.series.id,
              )}
              disabled={
                !source.series.instrument_id ||
                source.series.basis !== "total_return" ||
                source.availability !== "available"
              }
              onChange={() => toggle(source)}
            />
            <span>
              {source.series.provider_key} · {source.series.currency} ·{" "}
              {source.series.basis} · {source.availability}
            </span>
          </label>
        ))}
        <p>{selected.length} of 32 assets selected across source pages.</p>
        <ul>
          {selected.map((row) => (
            <li key={row.series_id}>
              {row.label}{" "}
              <Button
                variant="quiet"
                onClick={() => {
                  action.changed();
                  setSelected((items) =>
                    items.filter((item) => item.series_id !== row.series_id),
                  );
                }}
              >
                Remove {row.label}
              </Button>
            </li>
          ))}
        </ul>
        <p>
          This creates an asynchronous internal analysis from the displayed
          immutable inputs.
        </p>
        <Button type="submit">
          {action.pending ? "Submitting risk analysis…" : "Create risk run"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Read-only access">
          Creating a risk run requires risk:write.
        </Notice>
      ) : null}
      {selectionError ? <p role="alert">{selectionError}</p> : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </form>
  );
}

export function RiskJobControls({
  run,
  canWrite,
}: Readonly<{ run: RiskRunResponse; canWrite: boolean }>) {
  const router = useRouter();
  const polls = useRef(0);
  const [paused, setPaused] = useState(false);
  const live = run.state === "queued" || run.state === "running";
  const action = useRiskCommand(() => router.refresh());
  useEffect(() => {
    if (!live || paused) return;
    const timer = setInterval(() => {
      if (polls.current++ < 48) router.refresh();
      else setPaused(true);
    }, 5000);
    return () => clearInterval(timer);
  }, [live, paused, router]);
  return (
    <div className="form-actions" aria-live="polite">
      <Button
        variant="secondary"
        onClick={() => {
          polls.current = 0;
          setPaused(false);
          router.refresh();
        }}
      >
        Refresh risk status
      </Button>
      {live && canWrite ? (
        <Button
          variant="secondary"
          disabled={action.pending}
          onClick={() =>
            action.submit((key) => ({
              kind: "cancel_run",
              run_id: run.id,
              idempotency_key: key,
            }))
          }
        >
          {action.pending ? "Cancelling…" : "Cancel risk run"}
        </Button>
      ) : null}
      {paused && live ? (
        <span>
          Automatic refresh paused. Use Refresh risk status to continue.
        </span>
      ) : null}
      {action.error ? <p role="alert">{action.error}</p> : null}
    </div>
  );
}
