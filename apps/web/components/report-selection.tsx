"use client";

import { useNavigationVersionRef } from "./navigation-intent";

import styles from "./report-view.module.css";
import { useEffect, useRef, useState, useTransition } from "react";
import Link from "./navigation-intent";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Notice, Surface } from "@trading212/ui";
import type { Snapshot } from "@trading212/api-contracts";

import { submitReportCommand } from "../lib/report-actions";
import {
  EXPORT_DATASETS,
  REPORT_SECTIONS,
  REPORT_TYPES,
  REQUIRED_SECTIONS,
  reportHref,
  parseReportQuery,
  reportSelectionSearchKey,
  type ReportQuery,
  type ReportSearch,
} from "../lib/report-query";
import { formatDateTime, titleCase } from "../lib/format";

export interface ReportSourceChoice {
  id: string;
  label: string;
}
export interface ReportPlanChoice extends ReportSourceChoice {
  snapshotId: string;
  targetVersionId: string;
}
export interface ReportChoices {
  targets: ReportSourceChoice[];
  plans: ReportPlanChoice[];
  benchmarks: ReportSourceChoice[];
  warnings: string[];
}
type ReportType = (typeof REPORT_TYPES)[number];
type ReportSection = (typeof REPORT_SECTIONS)[number];

function selectedSections(form: FormData): ReportSection[] {
  const type = String(form.get("report_type")) as ReportType;
  const requested = new Set([
    ...REQUIRED_SECTIONS[type],
    ...form.getAll("sections").map(String),
  ]);
  return REPORT_SECTIONS.filter((section) => requested.has(section));
}

function remember(
  form: HTMLFormElement,
  accountId: string,
  snapshotId: string,
  onRememberSelection: (url: URL) => void,
) {
  const data = new FormData(form);
  const url = new URL(window.location.href);
  url.searchParams.set("account", accountId);
  url.searchParams.set("snapshot", snapshotId);
  for (const name of [
    "kind",
    "report_type",
    "dataset",
    "start_date",
    "end_date",
    "source_cutoff_at",
    "reporting_currency",
    "field_set",
    "ttl_days",
    "target_version_id",
    "plan_revision_id",
    "benchmark_version_id",
    "constituent_snapshot_id",
    "xray_run_id",
  ]) {
    const value = String(data.get(name) ?? "");
    if (value) url.searchParams.set(name, value);
    else url.searchParams.delete(name);
  }
  const formats = data.getAll("formats").map(String);
  if (formats.length) url.searchParams.set("formats", formats.join(","));
  else url.searchParams.delete("formats");
  url.searchParams.set("sections", selectedSections(data).join(","));
  onRememberSelection(url);
}

type ReportSelectionProps = Readonly<{
  accountId: string;
  snapshot: Snapshot;
  initial: ReportQuery;
  choices: ReportChoices;
  canCreate: boolean;
  defaultCutoff?: string;
}>;

function restoredSelection(
  search: Pick<URLSearchParams, "keys" | "getAll">,
): ReportQuery | null {
  const values = Object.create(null) as ReportSearch;
  for (const key of search.keys()) {
    const all = search.getAll(key);
    values[key] = all.length === 1 ? all[0] : all;
  }
  try {
    return parseReportQuery(values);
  } catch {
    return null;
  }
}

export function ReportSelectionForm(props: ReportSelectionProps) {
  const search = useSearchParams();
  const encoded = search.toString();
  const signature = reportSelectionSearchKey(search);
  const [writing, startWriting] = useTransition();
  const [navigation, setNavigation] = useState(() => ({
    observed: encoded,
    signature,
    pending: [] as string[],
    revision: 0,
    initial: restoredSelection(search),
    defaultCutoff: props.defaultCutoff,
  }));
  let restored = navigation;
  if (encoded !== navigation.observed) {
    const local = navigation.pending.indexOf(encoded);
    const initial = local < 0 ? restoredSelection(search) : navigation.initial;
    const reset =
      local < 0 &&
      (signature !== navigation.signature ||
        initial === null ||
        navigation.initial === null);
    restored = {
      ...navigation,
      observed: encoded,
      signature,
      pending: local < 0 ? [] : navigation.pending.slice(local + 1),
      revision: navigation.revision + (reset ? 1 : 0),
      ...(reset ? { initial, defaultCutoff: props.defaultCutoff } : {}),
    };
  }
  // A local B can be superseded by navigation back to the already-observed A.
  // React may commit only A, so completion must compare the final own target.
  const lastOwn = navigation.pending.at(-1);
  if (!writing && lastOwn !== undefined) {
    if (lastOwn !== encoded && restored.revision === navigation.revision) {
      const initial = restoredSelection(search);
      if (
        reportSelectionSearchKey(new URLSearchParams(lastOwn)) !== signature ||
        initial === null
      ) {
        restored = {
          ...restored,
          initial,
          defaultCutoff: props.defaultCutoff,
          revision: navigation.revision + 1,
        };
      }
    }
    // Retire coalesced A→B→A too; old B must not mask later real navigation.
    restored = { ...restored, pending: [] };
  }
  if (restored !== navigation) setNavigation(restored);
  if (restored.initial === null)
    return (
      <Notice title="Invalid report selection" tone="danger">
        <Link href="/reports">Reset the report selection</Link>
      </Notice>
    );
  return (
    <ReportSelectionFields
      {...props}
      key={restored.revision}
      initial={restored.initial}
      defaultCutoff={restored.defaultCutoff}
      onRememberSelection={(url) => {
        const next = url.searchParams.toString();
        setNavigation((current) =>
          current.pending.at(-1) === next
            ? current
            : {
                ...current,
                // Exact own URLs retain validation context; acknowledged prefixes retire.
                pending: [...current.pending.slice(-31), next],
              },
        );
        startWriting(() => window.history.replaceState(null, "", url));
      }}
    />
  );
}

function ReportSelectionFields({
  accountId,
  snapshot,
  initial,
  choices,
  canCreate,
  defaultCutoff,
  onRememberSelection,
}: ReportSelectionProps &
  Readonly<{ onRememberSelection: (url: URL) => void }>) {
  const router = useRouter();
  const navigationRef = useNavigationVersionRef();
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const [kind, setKind] = useState(initial.kind);
  const [reportType, setReportType] = useState<ReportType>(initial.report_type);
  const [dataset, setDataset] = useState<(typeof EXPORT_DATASETS)[number]>(
    initial.dataset,
  );
  const [extras, setExtras] = useState<string[]>(
    initial.sections?.split(",") ?? [],
  );
  const [companyPin, setCompanyPin] = useState(initial.xray_run_id ?? "");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const sections = [...new Set([...REQUIRED_SECTIONS[reportType], ...extras])];
  const wantsTarget =
    kind === "report"
      ? sections.some((section) =>
          ["targets", "drift", "contribution_plan"].includes(section),
        )
      : ["targets", "plans"].includes(dataset);
  const wantsPlan =
    kind === "report"
      ? sections.includes("contribution_plan")
      : dataset === "plans";
  const wantsBenchmark = kind === "report" && sections.includes("benchmark");
  const wantsXray =
    kind === "report" ? sections.includes("xray") : dataset === "xray";

  async function submit(form: HTMLFormElement) {
    const generation = navigationRef.current;
    setPending(true);
    setFailure(null);
    try {
      const values = new FormData(form);
      remember(form, accountId, snapshot.id, onRememberSelection);
      const requestedSections = selectedSections(values);
      const selectedCompanyRun = String(values.get("xray_run_id") ?? "");
      const companyRelevant =
        kind === "report"
          ? requestedSections.includes("drift")
          : dataset === "targets" ||
            (dataset === "plans" && values.get("field_set") === "audit");
      if (selectedCompanyRun && !companyRelevant) {
        setFailure(
          "Company actual weights require a drift section, a targets export, or a plans export with audit fields. Select that output or remove the retained company calculation.",
        );
        return;
      }
      const selectedPlan = choices.plans.find(
        (plan) => plan.id === values.get("plan_revision_id"),
      );
      const base = {
        account_id: accountId,
        snapshot_id: snapshot.id,
        start_date: String(values.get("start_date")),
        end_date: String(values.get("end_date")),
        source_cutoff_at: String(values.get("source_cutoff_at")),
        reporting_currency: String(values.get("reporting_currency")),
        ttl_days: Number(values.get("ttl_days")),
        ...(wantsTarget && values.get("target_version_id")
          ? { target_version_id: String(values.get("target_version_id")) }
          : {}),
        ...(wantsPlan && values.get("plan_revision_id")
          ? { plan_revision_id: String(values.get("plan_revision_id")) }
          : {}),
        ...(wantsBenchmark && values.get("benchmark_version_id")
          ? { benchmark_version_id: String(values.get("benchmark_version_id")) }
          : {}),
        ...(selectedCompanyRun ? { xray_run_id: selectedCompanyRun } : {}),
        ...(wantsXray && values.get("constituent_snapshot_id")
          ? {
              constituent_snapshot_id: String(
                values.get("constituent_snapshot_id"),
              ),
            }
          : {}),
      };
      if (selectedPlan && selectedPlan.snapshotId !== snapshot.id)
        throw new Error(
          "Choose the valuation snapshot used by the selected finalized plan.",
        );
      const body =
        kind === "report"
          ? {
              ...base,
              report_type: reportType,
              sections: requestedSections,
              formats: values.getAll("formats").map(String),
              template_version: "report_template_v1",
            }
          : {
              ...base,
              dataset,
              field_set: String(values.get("field_set")),
              format: String(values.get("formats")),
            };
      const serialized = JSON.stringify({ kind, body });
      const digest = Array.from(
        new Uint8Array(
          await crypto.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(serialized),
          ),
        ),
        (value) => value.toString(16).padStart(2, "0"),
      ).join("");
      if (!mounted.current || navigationRef.current !== generation) return;
      const url = new URL(window.location.href);
      const key =
        url.searchParams.get("request_digest") === digest
          ? (url.searchParams.get("request_key") ?? crypto.randomUUID())
          : crypto.randomUUID();
      url.searchParams.set("request_key", key);
      url.searchParams.set("request_digest", digest);
      onRememberSelection(url);
      const result = await submitReportCommand({
        kind,
        idempotency_key: key,
        body,
      });
      if (!mounted.current || navigationRef.current !== generation) return;
      if (!result.ok) {
        setFailure(`${result.code}: ${result.message}`);
        return;
      }
      const preserved = Object.fromEntries(url.searchParams);
      router.push(
        reportHref({
          ...preserved,
          kind,
          cursor: undefined,
          report: result.kind === "report" ? result.job.job_id : undefined,
          export: result.kind === "export" ? result.job.export_id : undefined,
        }),
      );
      router.refresh();
    } catch (error) {
      if (!mounted.current || navigationRef.current !== generation) return;
      setFailure(
        error instanceof Error &&
          error.message ===
            "Choose the valuation snapshot used by the selected finalized plan."
          ? error.message
          : "The request could not complete. Your selections and retry identity are preserved.",
      );
    } finally {
      if (mounted.current) setPending(false);
    }
  }

  return (
    <Surface className={styles.surface} aria-label="Create report or export">
      <h2>Create a private report or export</h2>
      <p>
        Snapshot at {formatDateTime(snapshot.valuation_at)} ·{" "}
        {snapshot.reporting_currency}. Each artifact retains the captured
        sources, methods and quality.
      </p>
      {!canCreate ? (
        <Notice title="Creation access is unavailable">
          Your current account scopes allow browsing. Report creation needs
          reports and analytics permission plus access to the selected data.
        </Notice>
      ) : null}
      {choices.warnings.map((warning) => (
        <Notice key={warning} title="Source selection unavailable">
          {warning}
        </Notice>
      ))}
      <form
        className={`target-form ${styles.selectionForm}`}
        onChange={(event) =>
          remember(
            event.currentTarget,
            accountId,
            snapshot.id,
            onRememberSelection,
          )
        }
        onSubmit={(event) => {
          event.preventDefault();
          void submit(event.currentTarget);
        }}
      >
        <fieldset
          className={styles.selectionFields}
          disabled={pending || !canCreate}
        >
          <legend>Report selection</legend>
          <label>
            <span>Output</span>
            <select
              name="kind"
              value={kind}
              onChange={(event) =>
                setKind(event.target.value as "report" | "export")
              }
            >
              <option value="report">Portfolio report</option>
              <option value="export">Dataset export</option>
            </select>
          </label>
          <label hidden={kind !== "report"}>
            <span>Report type</span>
            <select
              name="report_type"
              value={reportType}
              onChange={(event) => {
                setReportType(event.target.value as ReportType);
                setExtras([]);
              }}
            >
              {REPORT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {titleCase(type)}
                </option>
              ))}
            </select>
          </label>
          <label hidden={kind !== "export"}>
            <span>Dataset</span>
            <select
              name="dataset"
              value={dataset}
              onChange={(event) =>
                setDataset(
                  event.target.value as (typeof EXPORT_DATASETS)[number],
                )
              }
            >
              {EXPORT_DATASETS.map((item) => (
                <option key={item} value={item}>
                  {titleCase(item)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Start date</span>
            <input
              type="date"
              name="start_date"
              defaultValue={
                initial.start_date ?? `${snapshot.valuation_at.slice(0, 7)}-01`
              }
              required
            />
          </label>
          <label>
            <span>End date</span>
            <input
              type="date"
              name="end_date"
              defaultValue={
                initial.end_date ?? snapshot.valuation_at.slice(0, 10)
              }
              required
            />
          </label>
          <p className="muted">
            Monthly, quarterly and annual reports require one complete calendar
            period. Other reports use your explicit inclusive dates.
          </p>
          <label>
            <span>Source cutoff (UTC)</span>
            <input
              name="source_cutoff_at"
              defaultValue={
                initial.source_cutoff_at ??
                defaultCutoff ??
                snapshot.source_cutoff_at
              }
              maxLength={40}
              required
            />
          </label>
          <Button
            type="button"
            variant="secondary"
            onClick={(event) => {
              const form = event.currentTarget.form;
              const input = form?.elements.namedItem("source_cutoff_at");
              if (form && input instanceof HTMLInputElement) {
                input.value = new Date().toISOString();
                remember(form, accountId, snapshot.id, onRememberSelection);
              }
            }}
          >
            Use current UTC
          </Button>
          <label>
            <span>Reporting currency</span>
            <input
              name="reporting_currency"
              defaultValue={
                initial.reporting_currency ?? snapshot.reporting_currency
              }
              pattern="[A-Z]{3}"
              maxLength={3}
              required
            />
          </label>
          <label>
            <span>Requested retention (days)</span>
            <input
              type="number"
              name="ttl_days"
              defaultValue={initial.ttl_days}
              min={1}
              max={30}
              step={1}
              required
            />
          </label>
          <p className="muted">
            Default retention is seven days. A source license can require
            earlier expiry, shown in the saved job.
          </p>
          {kind === "report" ? (
            <fieldset className={styles.formats}>
              <legend>Formats</legend>
              {["pdf", "csv", "json", "xlsx"].map((format) => (
                <label className={styles.choice} key={format}>
                  <input
                    type="checkbox"
                    name="formats"
                    value={format}
                    defaultChecked={(
                      initial.formats?.split(",") ?? ["pdf"]
                    ).includes(format)}
                  />
                  {format.toUpperCase()}
                </label>
              ))}
            </fieldset>
          ) : (
            <>
              <label>
                <span>Format</span>
                <select
                  name="formats"
                  defaultValue={
                    initial.formats
                      ?.split(",")
                      .find((format) => format !== "pdf") ?? "csv"
                  }
                >
                  {["csv", "json", "xlsx"].map((format) => (
                    <option key={format} value={format}>
                      {format.toUpperCase()}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Columns</span>
                <select name="field_set" defaultValue={initial.field_set}>
                  <option value="standard">Standard</option>
                  <option value="audit">Audit with explanatory records</option>
                </select>
              </label>
            </>
          )}
          {kind === "report" ? (
            <details>
              <summary>Sections</summary>
              <p>
                Required sections stay selected. Additional sections can require
                more sources.
              </p>
              {REPORT_SECTIONS.map((section) => (
                <label className={styles.choice} key={section}>
                  <input
                    type="checkbox"
                    name="sections"
                    value={section}
                    disabled={REQUIRED_SECTIONS[reportType].includes(section)}
                    checked={sections.includes(section)}
                    onChange={(event) =>
                      setExtras(
                        event.target.checked
                          ? [...extras, section]
                          : extras.filter((item) => item !== section),
                      )
                    }
                  />
                  {titleCase(section)}
                </label>
              ))}
            </details>
          ) : null}
          {wantsTarget ? (
            <ReportVersionField
              name="target_version_id"
              label="Published target"
              initial={initial.target_version_id}
              choices={choices.targets}
              required={!wantsPlan}
            />
          ) : null}
          {wantsPlan ? (
            <ReportVersionField
              name="plan_revision_id"
              label="Finalized contribution plan"
              initial={initial.plan_revision_id}
              choices={choices.plans}
              required
            />
          ) : null}
          {wantsBenchmark ? (
            <ReportVersionField
              name="benchmark_version_id"
              label="Benchmark version"
              initial={initial.benchmark_version_id}
              choices={choices.benchmarks}
              required
            />
          ) : null}
          {wantsTarget || wantsPlan || wantsBenchmark ? (
            <p className="muted">
              Choose a listed reference or enter an authorized saved version ID.
              A finalized plan supplies its own target when the target field is
              empty.
            </p>
          ) : null}
          {wantsTarget || Boolean(companyPin) ? (
            <details open={Boolean(initial.xray_run_id)}>
              <summary>Optional company actual weights</summary>
              <p>
                Use a retained company calculation for the same account,
                valuation snapshot and currency. Company weights describe the
                complete portfolio and may repeat beside several listings. They
                do not define company targets or post-plan weights.
              </p>
              <p>
                Reports require the drift section. Exports support targets or
                plans with the audit field set. The source cutoff must be at or
                after the retained calculation became available; the saved
                valuation and its financial source cutoff stay unchanged.
                Current source permissions and retention apply.
              </p>
              <label>
                <span>Retained company calculation</span>
                <input
                  name="xray_run_id"
                  value={companyPin}
                  onChange={(event) => setCompanyPin(event.target.value)}
                  maxLength={36}
                  pattern="[0-9a-fA-F-]{36}"
                />
              </label>
            </details>
          ) : null}
          {wantsXray ? (
            <details>
              <summary>Optional constituent snapshot expectation</summary>
              <p>
                The server selects the complete X-ray source set. An optional
                snapshot reference must belong to that selected set.
              </p>
              <label>
                <span>Expected constituent snapshot</span>
                <input
                  name="constituent_snapshot_id"
                  defaultValue={initial.constituent_snapshot_id ?? ""}
                  maxLength={36}
                  pattern="[0-9a-fA-F-]{36}"
                />
              </label>
            </details>
          ) : null}
          <Button type="submit" disabled={pending || !canCreate}>
            {pending
              ? "Saving request…"
              : kind === "report"
                ? "Generate report"
                : "Create export"}
          </Button>
        </fieldset>
        {failure ? (
          <Notice title="Request not completed" tone="danger">
            <p>{failure}</p>
          </Notice>
        ) : null}
      </form>
    </Surface>
  );
}

function ReportVersionField({
  name,
  label,
  initial,
  choices,
  required,
}: Readonly<{
  name: string;
  label: string;
  initial?: string;
  choices: ReportSourceChoice[];
  required: boolean;
}>) {
  return (
    <label>
      <span>{label}</span>
      <input
        name={name}
        list={`report-${name}-choices`}
        defaultValue={initial ?? ""}
        required={required}
        maxLength={36}
        pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
      />
      <datalist id={`report-${name}-choices`}>
        {choices.map((choice) => (
          <option key={choice.id} value={choice.id}>
            {choice.label}
          </option>
        ))}
      </datalist>
    </label>
  );
}
