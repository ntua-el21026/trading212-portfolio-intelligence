"use client";

import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  BenchmarkContent,
  BenchmarkDefinitionDetail,
  SourceSeries,
} from "@trading212/api-contracts";
import { Button, Notice, Surface } from "@trading212/ui";
import {
  submitBenchmarkCommand,
  type SourceActionResult,
} from "../lib/source-actions";

export function BenchmarkForm({
  sources,
  initial,
  effectiveAt,
  currency = "EUR",
  accountId,
}: Readonly<{
  sources: SourceSeries[];
  initial?: BenchmarkDefinitionDetail;
  effectiveAt: string;
  currency?: string;
  accountId?: string;
}>) {
  const router = useRouter();
  const version = initial?.selected_version;
  const preferred =
    sources.find((item) => item.basis === "total_return") ?? sources[0];
  const [name, setName] = useState(initial?.definition.name ?? "");
  const [content, setContent] = useState<BenchmarkContent>(
    version?.content ?? {
      reporting_currency: currency,
      effective_at: effectiveAt,
      return_basis: preferred?.basis ?? "total_return",
      calendar_id: preferred?.calendar_id ?? "",
      calendar_version: preferred?.calendar_version ?? "",
      rebalance_rule: "buy_and_hold",
      components: [{ source_id: preferred?.id ?? "", weight: "1" }],
    },
  );
  const [normalize, setNormalize] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<SourceActionResult | null>(null);
  const identity = useRef(new Map<string, string>());
  const selectedSources = new Map(sources.map((item) => [item.id, item]));
  const archived = initial?.definition.state === "archived";
  async function run(kind: "create" | "version" | "archive") {
    const command =
      kind === "create"
        ? { kind, body: { name, content, normalize } }
        : kind === "version"
          ? {
              kind,
              definition_id: initial!.definition.id,
              if_match: initial!.definition.revision_etag,
              body: { content, normalize },
            }
          : {
              kind,
              definition_id: initial!.definition.id,
              if_match: initial!.definition.revision_etag,
            };
    const fingerprint = JSON.stringify(command);
    const idempotencyKey =
      identity.current.get(fingerprint) ?? crypto.randomUUID();
    identity.current.set(fingerprint, idempotencyKey);
    setPending(true);
    setResult(null);
    try {
      const next = await submitBenchmarkCommand({
        ...command,
        idempotency_key: idempotencyKey,
      });
      setResult(next);
      if (next.ok) {
        identity.current.delete(fingerprint);
        const selection = new URLSearchParams();
        if (accountId) selection.set("account", accountId);
        if (next.value.selected_version)
          selection.set("version", next.value.selected_version.id);
        router.push(
          `/sources/benchmarks/${next.value.definition.id}?${selection}`,
        );
        router.refresh();
      }
    } catch {
      setResult({
        ok: false,
        code: "SOURCES_UNAVAILABLE",
        message: "The benchmark could not be saved. Your inputs are preserved.",
      });
    } finally {
      setPending(false);
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(initial ? "version" : "create");
  }
  function update<K extends keyof BenchmarkContent>(
    key: K,
    value: BenchmarkContent[K],
  ) {
    setContent((current) => ({ ...current, [key]: value }));
  }
  return (
    <Surface>
      <h2>
        {initial ? "Publish another benchmark version" : "Create a benchmark"}
      </h2>
      <p>
        Choose source series and exact fractional weights. Published versions
        keep their composition and calculation convention.
      </p>
      {archived ? (
        <Notice title="Archived benchmark">
          History remains available. This definition cannot publish further
          versions.
        </Notice>
      ) : (
        <form className="target-form benchmark-form" onSubmit={submit}>
          <fieldset disabled={pending}>
            <legend>Definition and methodology</legend>
            <label>
              <span>Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={120}
                disabled={Boolean(initial)}
              />
            </label>
            <label>
              <span>Reporting currency</span>
              <input
                value={content.reporting_currency}
                onChange={(event) =>
                  update("reporting_currency", event.target.value)
                }
                pattern="[A-Z]{3}"
                maxLength={3}
                required
                readOnly={Boolean(initial)}
              />
            </label>
            <label>
              <span>Effective time (UTC)</span>
              <input
                value={content.effective_at}
                onChange={(event) => update("effective_at", event.target.value)}
                required
                placeholder="2026-08-31T12:00:00Z"
              />
            </label>
            <label>
              <span>Return basis</span>
              <select
                value={content.return_basis}
                onChange={(event) =>
                  update(
                    "return_basis",
                    event.target.value as BenchmarkContent["return_basis"],
                  )
                }
              >
                <option value="total_return">Total return</option>
                <option value="split_adjusted">Split adjusted</option>
                <option value="raw_close">Raw close</option>
              </select>
            </label>
            <label>
              <span>Rebalancing convention</span>
              <select
                value={content.rebalance_rule}
                onChange={(event) =>
                  update(
                    "rebalance_rule",
                    event.target.value as BenchmarkContent["rebalance_rule"],
                  )
                }
              >
                <option value="buy_and_hold">Buy and hold</option>
                <option value="daily_rebalanced">Daily rebalanced</option>
              </select>
            </label>
            <label>
              <span>Calendar</span>
              <input
                value={content.calendar_id}
                onChange={(event) => update("calendar_id", event.target.value)}
                required
                maxLength={120}
              />
            </label>
            <label>
              <span>Calendar version</span>
              <input
                value={content.calendar_version}
                onChange={(event) =>
                  update("calendar_version", event.target.value)
                }
                required
                maxLength={120}
              />
            </label>
          </fieldset>
          <fieldset disabled={pending}>
            <legend>Weighted source series</legend>
            <p>
              Weights are fractions: 0.6 means 60%. The server validates their
              exact sum. Source IDs can be copied from the paginated source
              catalog.
            </p>
            {content.components.map((component, index) => (
              <div key={index} className="benchmark-component">
                <label>
                  <span>Source {index + 1}</span>
                  <select
                    aria-label={`Choose source ${index + 1}`}
                    value={
                      selectedSources.has(component.source_id)
                        ? component.source_id
                        : ""
                    }
                    onChange={(event) =>
                      update(
                        "components",
                        content.components.map((row, i) =>
                          i === index
                            ? { ...row, source_id: event.target.value }
                            : row,
                        ),
                      )
                    }
                  >
                    <option value="">Use a source ID</option>
                    {sources.map((source) => (
                      <option key={source.id} value={source.id}>
                        {source.provider_key} · {source.basis} ·{" "}
                        {source.currency}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={`Source ID ${index + 1}`}
                    value={component.source_id}
                    onChange={(event) =>
                      update(
                        "components",
                        content.components.map((row, i) =>
                          i === index
                            ? { ...row, source_id: event.target.value }
                            : row,
                        ),
                      )
                    }
                    required
                    maxLength={36}
                  />
                </label>
                <label>
                  <span>Weight {index + 1}</span>
                  <input
                    inputMode="decimal"
                    value={component.weight}
                    onChange={(event) =>
                      update(
                        "components",
                        content.components.map((row, i) =>
                          i === index
                            ? { ...row, weight: event.target.value }
                            : row,
                        ),
                      )
                    }
                    required
                    maxLength={40}
                  />
                </label>
                <Button
                  type="button"
                  disabled={content.components.length === 1}
                  onClick={() =>
                    update(
                      "components",
                      content.components.filter((_, i) => i !== index),
                    )
                  }
                >
                  Remove source {index + 1}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              disabled={content.components.length >= 256}
              onClick={() =>
                update("components", [
                  ...content.components,
                  { source_id: "", weight: "0" },
                ])
              }
            >
              Add source
            </Button>
            <label className="target-checkbox">
              <input
                type="checkbox"
                checked={normalize}
                onChange={(event) => setNormalize(event.target.checked)}
              />
              <span>
                Allow explicit normalization only within the 0.000000000001
                tolerance
              </span>
            </label>
          </fieldset>
          <Button type="submit" disabled={pending}>
            {pending
              ? "Saving…"
              : initial
                ? "Publish benchmark version"
                : "Create benchmark"}
          </Button>
          {initial ? (
            <Button
              type="button"
              disabled={pending}
              onClick={() => void run("archive")}
            >
              Archive benchmark
            </Button>
          ) : null}
        </form>
      )}
      {result && !result.ok ? (
        <Notice
          title={
            result.code === "REVISION_MISMATCH"
              ? "This benchmark changed in another session"
              : "Review your benchmark"
          }
          tone="danger"
        >
          <p>{result.message}</p>
          {result.code === "REVISION_MISMATCH" ? (
            <p>
              Copy your unsaved inputs before reloading the current version.
            </p>
          ) : null}
        </Notice>
      ) : result?.ok ? (
        <p role="status">Benchmark saved.</p>
      ) : null}
    </Surface>
  );
}
