"use client";
import {
  useEffect,
  useRef,
  useState,
  useTransition,
  type FormEvent,
} from "react";
import { useRouter } from "next/navigation";
import { Button, Notice } from "@trading212/ui";
import {
  CreateAggregateSelectionRequestSchema,
  CreateAggregateRunRequestSchema,
  type Account,
  type AggregateMember,
  type AggregateFxBinding,
  type AggregateSelectionResponse,
} from "@trading212/api-contracts";
import {
  loadAggregateSnapshotChoices,
  type AggregateSnapshotChoice,
} from "../lib/aggregation-actions";
import { aggregationHref } from "../lib/aggregation-query";
import { formatDateTime } from "../lib/format";
import { useAggregationCommand } from "./aggregation-command";
import { AggregateFxPicker } from "./aggregation-fx-picker";
import Link, { useNavigationVersionRef } from "./navigation-intent";
import styles from "./aggregation.module.css";

function MemberPicker({
  index,
  value,
  accounts,
  change,
  remove,
}: Readonly<{
  index: number;
  value: AggregateMember;
  accounts: readonly Account[];
  change: (value: AggregateMember) => void;
  remove: () => void;
}>) {
  const [choices, setChoices] = useState<AggregateSnapshotChoice[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const request = useRef(0);
  const navigation = useNavigationVersionRef();
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      request.current += 1;
    };
  }, []);
  function load(account_id: string, next: string | null = null) {
    const stamp = ++request.current;
    const intent = navigation.current;
    if (!next) {
      setChoices([]);
      setCursor(null);
      change({ account_id, portfolio_snapshot_id: "" });
    }
    setError(null);
    if (!account_id) return;
    start(async () => {
      try {
        const result = await loadAggregateSnapshotChoices({
          account_id,
          cursor: next,
        });
        if (
          !alive.current ||
          request.current !== stamp ||
          navigation.current !== intent
        )
          return;
        if (!result.ok) {
          setError(result.message);
          return;
        }
        if (result.account_id !== account_id) {
          setError("The snapshot account did not match.");
          return;
        }
        // Each page replaces the prior options; selected metadata remains explicit.
        setChoices(result.items);
        setCursor(result.next_cursor);
      } catch {
        if (
          alive.current &&
          request.current === stamp &&
          navigation.current === intent
        )
          setError("Saved snapshots could not be loaded. Retry this account.");
      }
    });
  }
  return (
    <fieldset className={styles.stack} disabled={pending}>
      <legend>Account {index + 1}</legend>
      <div className={styles.fields}>
        <label>
          <span>Included account {index + 1}</span>
          <select
            value={value.account_id}
            required
            onChange={(event) => load(event.target.value)}
          >
            <option value="">Choose an account</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.display_name} · {account.provider} ·{" "}
                {account.reporting_currency}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Saved snapshot {index + 1}</span>
          <select
            value={value.portfolio_snapshot_id}
            required
            disabled={!choices.length}
            onChange={(event) =>
              change({ ...value, portfolio_snapshot_id: event.target.value })
            }
          >
            <option value="">Choose a saved snapshot</option>
            {value.portfolio_snapshot_id &&
            !choices.some(
              (choice) => choice.id === value.portfolio_snapshot_id,
            ) ? (
              <option value={value.portfolio_snapshot_id}>
                Selected snapshot from another page
              </option>
            ) : null}
            {choices.map((choice) => (
              <option key={choice.id} value={choice.id}>
                {formatDateTime(choice.valuation_at)} ·{" "}
                {choice.reporting_currency} · known{" "}
                {formatDateTime(choice.source_cutoff_at)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {pending ? <p role="status">Loading saved snapshots…</p> : null}
      {error ? (
        <Notice title="Snapshot selection unavailable">{error}</Notice>
      ) : null}
      {!pending && value.account_id && !choices.length && !error ? (
        <p>No saved snapshots on this page.</p>
      ) : null}
      <div className={styles.toolbar}>
        {value.account_id ? (
          <Button type="button" onClick={() => load(value.account_id)}>
            Reload snapshots
          </Button>
        ) : null}
        {cursor ? (
          <Button type="button" onClick={() => load(value.account_id, cursor)}>
            Older snapshots
          </Button>
        ) : null}
        <Button type="button" onClick={remove}>
          Remove account {index + 1}
        </Button>
      </div>
    </fieldset>
  );
}

export function AggregateSelectionForm({
  accounts,
  cutoff,
}: Readonly<{ accounts: readonly Account[]; cutoff: string }>) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState(
    accounts[0]?.reporting_currency ?? "EUR",
  );
  const [knownAt, setKnownAt] = useState(cutoff);
  const [members, setMembers] = useState<
    Array<{ key: number; value: AggregateMember }>
  >([{ key: 0, value: { account_id: "", portfolio_snapshot_id: "" } }]);
  const next = useRef(1);
  const [invalid, setInvalid] = useState<string | null>(null);
  const command = useAggregationCommand((result) => {
    if (result.kind === "selection")
      router.push(
        aggregationHref({ view: "runs", selection: result.value.selection_id }),
      );
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = CreateAggregateSelectionRequestSchema.safeParse({
      content: {
        name,
        members: members.map((member) => member.value),
        reporting_currency: currency,
        source_cutoff_at: knownAt,
        economic_identity_policy: "canonical_instrument_v1",
      },
    });
    if (
      !parsed.success ||
      new Set(members.map((member) => member.value.account_id)).size !==
        members.length
    ) {
      setInvalid(
        "Choose 1–8 distinct accounts, their saved snapshots, a name, currency and exact ISO cutoff.",
      );
      return;
    }
    setInvalid(null);
    command.submit((idempotency_key) => ({
      kind: "selection",
      idempotency_key,
      body: parsed.data,
    }));
  }
  return (
    <form
      onSubmit={submit}
      className={styles.stack}
      aria-label="Create account aggregate"
    >
      <fieldset disabled={command.pending} className={styles.stack}>
        <legend>New aggregate selection</legend>
        <div className={styles.fields}>
          <label>
            <span>Aggregate name</span>
            <input
              required
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <span>Reporting currency</span>
            <input
              required
              pattern="[A-Z]{3}"
              maxLength={3}
              value={currency}
              onChange={(event) => setCurrency(event.target.value)}
            />
          </label>
          <label>
            <span>Source cutoff (ISO timestamp)</span>
            <input
              required
              maxLength={40}
              value={knownAt}
              onChange={(event) => setKnownAt(event.target.value)}
            />
          </label>
        </div>
        <p>
          Choose the exact saved snapshot for each account. Distinct valuation
          dates and missing conversions remain visible in the result.
        </p>
        {members.map((member, index) => (
          <MemberPicker
            key={member.key}
            index={index}
            value={member.value}
            accounts={accounts}
            change={(value) =>
              setMembers((old) =>
                old.map((row) =>
                  row.key === member.key ? { ...row, value } : row,
                ),
              )
            }
            remove={() =>
              setMembers((old) => old.filter((row) => row.key !== member.key))
            }
          />
        ))}
        <Button
          type="button"
          disabled={members.length >= 8}
          onClick={() => {
            const key = next.current++;
            setMembers((old) => [
              ...old,
              { key, value: { account_id: "", portfolio_snapshot_id: "" } },
            ]);
          }}
        >
          Add account
        </Button>
        <Button type="submit" disabled={!members.length}>
          {command.pending ? "Saving selection…" : "Save aggregate selection"}
        </Button>
      </fieldset>
      {invalid || command.error ? (
        <Notice title="Selection not saved">
          {invalid ?? command.error?.message}
        </Notice>
      ) : null}
    </form>
  );
}

export function AggregateRunForm({
  selection,
  accounts,
  canReadActivity,
}: Readonly<{
  selection: AggregateSelectionResponse;
  accounts: readonly Account[];
  canReadActivity: boolean;
}>) {
  const router = useRouter();
  const [fx, setFx] = useState<
    Array<{ key: number; value: AggregateFxBinding }>
  >([]);
  const nextFx = useRef(0);
  const [includeActivity, setIncludeActivity] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [invalid, setInvalid] = useState<string | null>(null);
  const command = useAggregationCommand((result) => {
    if (result.kind === "run")
      router.push(
        aggregationHref({
          view: "result",
          selection: result.value.selection_id,
          run: result.value.run_id,
        }),
      );
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = CreateAggregateRunRequestSchema.safeParse({
      fx_bindings: fx.map((row) => row.value),
      activity_window:
        includeActivity && canReadActivity
          ? { start_at: start, end_at: end }
          : null,
    });
    if (!parsed.success) {
      setInvalid(
        "Review the exact saved FX references and optional activity window.",
      );
      return;
    }
    setInvalid(null);
    command.submit((idempotency_key) => ({
      kind: "run",
      selection_id: selection.selection_id,
      revision: selection.revision,
      idempotency_key,
      body: parsed.data,
    }));
  }
  return (
    <form
      onSubmit={submit}
      className={styles.stack}
      aria-label="Calculate account aggregate"
    >
      <fieldset disabled={command.pending} className={styles.stack}>
        <legend>Calculate this selection</legend>
        <p>
          Same-currency values need no conversion. Missing FX keeps the original
          amounts and reports incomplete totals.
        </p>
        {fx.map((row, index) => (
          <AggregateFxPicker
            key={row.key}
            index={index}
            value={row.value}
            selection={selection}
            accounts={accounts}
            change={(value) =>
              setFx((old) =>
                old.map((item) =>
                  item.key === row.key ? { ...item, value } : item,
                ),
              )
            }
            remove={() =>
              setFx((old) => old.filter((item) => item.key !== row.key))
            }
          />
        ))}
        <div className={styles.toolbar}>
          <Button
            type="button"
            disabled={fx.length >= 256}
            onClick={() => {
              const key = nextFx.current++;
              setFx((old) => [
                ...old,
                {
                  key,
                  value: {
                    account_id: "",
                    currency: "",
                    fx_observation_id: "",
                  },
                },
              ]);
            }}
          >
            Add saved FX reference
          </Button>
          <Link href="/sources" prefetch={false}>
            Review source observations
          </Link>
        </div>
        {canReadActivity ? (
          <>
            <p>
              An activity window must end within every selected snapshot’s
              source cutoff. Incomplete source coverage remains explicit.
            </p>
            <label>
              <input
                type="checkbox"
                checked={includeActivity}
                onChange={(event) => setIncludeActivity(event.target.checked)}
              />{" "}
              Include transfer evidence
            </label>
            {includeActivity ? (
              <div className={styles.fields}>
                <label>
                  <span>Activity start (ISO timestamp)</span>
                  <input
                    required
                    maxLength={40}
                    value={start}
                    onChange={(event) => setStart(event.target.value)}
                  />
                </label>
                <label>
                  <span>Activity end (ISO timestamp)</span>
                  <input
                    required
                    maxLength={40}
                    value={end}
                    onChange={(event) => setEnd(event.target.value)}
                  />
                </label>
              </div>
            ) : null}
          </>
        ) : (
          <p>Activity access is required to include transfer evidence.</p>
        )}
        <Button type="submit">
          {command.pending ? "Calculating aggregate…" : "Calculate aggregate"}
        </Button>
      </fieldset>
      {invalid || command.error ? (
        <Notice title="Calculation unavailable">
          {invalid ?? command.error?.message}
        </Notice>
      ) : null}
      {command.error?.code === "REVISION_MISMATCH" ? (
        <Button type="button" onClick={() => router.refresh()}>
          Reload current revision
        </Button>
      ) : null}
    </form>
  );
}
