"use client";

import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  Account,
  VirtualPortfolioResponse,
  TargetVersionResponse,
} from "@trading212/api-contracts";
import { Button, Notice, Surface } from "@trading212/ui";

import {
  submitTargetCommand,
  type TargetActionCommand,
  type TargetActionResult,
} from "../lib/target-actions";

type WithoutIdentity<T> = T extends unknown
  ? Omit<T, "idempotency_key">
  : never;
export type TargetCommandInput = WithoutIdentity<TargetActionCommand>;

export function useTargetCommand() {
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<TargetActionResult | null>(null);
  const identities = useRef(new Map<string, string>());
  async function run(command: TargetCommandInput) {
    const fingerprint = JSON.stringify(command);
    const idempotencyKey =
      identities.current.get(fingerprint) ?? crypto.randomUUID();
    identities.current.set(fingerprint, idempotencyKey);
    setPending(true);
    setResult(null);
    try {
      const next = await submitTargetCommand({
        ...command,
        idempotency_key: idempotencyKey,
      });
      setResult(next);
      if (next.ok) {
        identities.current.delete(fingerprint);
      }
      return next;
    } catch {
      const next: TargetActionResult = {
        ok: false,
        code: "TARGETS_UNAVAILABLE",
        message:
          "The request could not be completed. Your edits are preserved; retry when the service is available.",
        fields: [],
      };
      setResult(next);
      return next;
    } finally {
      setPending(false);
    }
  }
  return { pending, result, run };
}

export function TargetCommandFeedback({
  result,
}: Readonly<{ result: TargetActionResult | null }>) {
  if (!result) return null;
  if (!result.ok) {
    return (
      <Notice
        title={
          result.code === "REVISION_MISMATCH"
            ? "This Pie changed in another session"
            : "Review your request"
        }
        tone="danger"
      >
        <p>{result.message}</p>
        {result.fields.length > 0 ? (
          <ul>
            {result.fields.map((field) => (
              <li key={field}>{field}</li>
            ))}
          </ul>
        ) : null}
        {result.code === "REVISION_MISMATCH" ? (
          <p>Copy any unsaved changes before reloading this page.</p>
        ) : null}
      </Notice>
    );
  }
  return (
    <p role="status" className="target-feedback">
      {result.kind === "validation"
        ? "Validation finished. Review the results below."
        : "Changes saved."}
    </p>
  );
}

export function CreatePieForm({
  accounts,
  sourceVersionId,
}: Readonly<{ accounts: Account[]; sourceVersionId?: string }>) {
  const action = useTargetCommand();
  const router = useRouter();
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? "");
  const selected = accounts.find((account) => account.id === accountId);
  const [currency, setCurrency] = useState(
    accounts[0]?.reporting_currency ?? "EUR",
  );
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const result = await action.run({
      kind: "create_portfolio",
      body: {
        name: String(values.get("name") ?? ""),
        description: String(values.get("description") ?? ""),
        account_id: accountId || null,
        reporting_currency: selected?.reporting_currency ?? currency,
      },
    });
    if (result.ok && result.kind === "portfolio")
      router.push(
        `/pies/${result.value.id}${sourceVersionId ? `?clone=${sourceVersionId}` : ""}`,
      );
  }
  return (
    <Surface>
      <h2>Create a Pie</h2>
      <p className="muted">
        Define a private target for an account, or save a reusable template.
      </p>
      <form className="target-form" onSubmit={submit}>
        <label>
          Name
          <input name="name" required maxLength={120} autoComplete="off" />
        </label>
        <label>
          Account
          <select
            value={accountId}
            onChange={(event) => setAccountId(event.target.value)}
          >
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.display_name} · {account.reporting_currency}
              </option>
            ))}
            <option value="">Template · no account</option>
          </select>
        </label>
        <label>
          Reporting currency
          <input
            value={selected?.reporting_currency ?? currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            readOnly={Boolean(selected)}
            required
            pattern="[A-Z]{3}"
            maxLength={3}
          />
        </label>
        <label className="target-form__wide">
          Description
          <textarea name="description" maxLength={2000} rows={2} />
        </label>
        <div className="target-actions">
          <Button type="submit" disabled={action.pending}>
            {action.pending ? "Creating…" : "Create Pie"}
          </Button>
        </div>
      </form>
      <TargetCommandFeedback result={action.result} />
    </Surface>
  );
}

export function PieMetadataForm({
  portfolio,
  etag,
}: Readonly<{ portfolio: VirtualPortfolioResponse; etag: string }>) {
  const action = useTargetCommand();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    await action.run({
      kind: "update_portfolio",
      portfolio_id: portfolio.id,
      if_match: etag,
      body: {
        name: String(values.get("name") ?? ""),
        description: String(values.get("description") ?? ""),
      },
    });
  }
  return (
    <details className="target-details">
      <summary>Pie settings</summary>
      <form className="target-form" onSubmit={submit}>
        <label>
          Name
          <input
            name="name"
            defaultValue={portfolio.name}
            maxLength={120}
            required
          />
        </label>
        <label>
          Description
          <textarea
            name="description"
            defaultValue={portfolio.description}
            maxLength={2000}
            rows={2}
          />
        </label>
        <div className="target-actions">
          <Button
            type="submit"
            variant="secondary"
            disabled={action.pending || portfolio.state === "archived"}
          >
            Save settings
          </Button>
          <Button
            variant="danger"
            disabled={action.pending || portfolio.state === "archived"}
            onClick={() =>
              void action.run({
                kind: "archive_portfolio",
                portfolio_id: portfolio.id,
                if_match: etag,
              })
            }
          >
            Archive Pie
          </Button>
        </div>
      </form>
      <p className="muted">
        Archiving removes the active target and prevents scheduled activation.
        Published versions remain available in history.
      </p>
      <TargetCommandFeedback result={action.result} />
    </details>
  );
}

export function CreateVersionForm({
  portfolio,
  etag,
  version,
  clone,
  defaultEffectiveAt,
}: Readonly<{
  portfolio: VirtualPortfolioResponse;
  etag: string;
  version: TargetVersionResponse | null;
  clone: TargetVersionResponse | null;
  defaultEffectiveAt: string;
}>) {
  const action = useTargetCommand();
  const router = useRouter();
  const [source, setSource] = useState(clone?.id ?? version?.id ?? "");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const date = String(values.get("effective_at") ?? "");
    const result = await action.run({
      kind: "create_version",
      portfolio_id: portfolio.id,
      if_match: etag,
      body: {
        effective_at: `${date}:00Z`,
        ...(source
          ? { source_version_id: source }
          : { content: { nodes: [], constraints: [], exclusions: [] } }),
      },
    });
    if (result.ok && result.kind === "version")
      router.push(`/pies/${portfolio.id}?version=${result.value.id}`);
  }
  return (
    <form className="target-form" onSubmit={submit}>
      <label>
        Start from
        <select
          value={source}
          onChange={(event) => setSource(event.target.value)}
        >
          <option value="">Empty draft</option>
          {version ? (
            <option value={version.id}>
              Selected version {version.version_number}
            </option>
          ) : null}
          {clone && clone.id !== version?.id ? (
            <option value={clone.id}>
              Selected template · version {clone.version_number}
            </option>
          ) : null}
        </select>
      </label>
      <label>
        Effective from (UTC)
        <input
          type="datetime-local"
          name="effective_at"
          defaultValue={defaultEffectiveAt}
          required
        />
      </label>
      <div className="target-actions">
        <Button
          type="submit"
          disabled={action.pending || portfolio.state === "archived"}
        >
          {action.pending ? "Creating…" : "Create draft version"}
        </Button>
      </div>
      <TargetCommandFeedback result={action.result} />
    </form>
  );
}
