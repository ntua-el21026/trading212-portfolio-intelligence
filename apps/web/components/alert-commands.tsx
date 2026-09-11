"use client";

import { useNavigationVersionRef } from "./navigation-intent";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useTransition,
  type FormEvent,
  type ReactNode,
  type TransitionStartFunction,
} from "react";
import { useRouter } from "next/navigation";
import { Button, Notice } from "@trading212/ui";
import type {
  AlertEventDetail,
  AlertRuleDetail,
  AlertRuleVersion,
} from "@trading212/api-contracts";
import {
  submitAlertCommand,
  type AlertActionResult,
} from "../lib/alert-actions";
import styles from "./alert-view.module.css";

const AlertTransition = createContext<
  [boolean, TransitionStartFunction] | null
>(null);

export function AlertCommandScope({
  children,
}: Readonly<{ children: ReactNode }>) {
  const transition = useTransition();
  return <AlertTransition value={transition}>{children}</AlertTransition>;
}

export function useAlertTransition() {
  const local = useTransition();
  return useContext(AlertTransition) ?? local;
}

function useAlertCommand() {
  const router = useRouter();
  const navigationRef = useNavigationVersionRef();
  const [pending, startChange] = useAlertTransition();
  const [feedback, setFeedback] = useState<AlertActionResult | null>(null);
  const mounted = useRef(true);
  const retry = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  function execute(command: Record<string, unknown>) {
    const generation = navigationRef.current;
    if (pending) return;
    const signature = JSON.stringify(command);
    if (retry.current?.signature !== signature)
      retry.current = { signature, key: crypto.randomUUID() };
    const key = retry.current.key;
    startChange(async () => {
      const result = await submitAlertCommand({
        ...command,
        idempotency_key: key,
      });
      if (!mounted.current || navigationRef.current !== generation) return;
      setFeedback(result);
      if (result.ok) startChange(() => router.refresh());
    });
  }
  return { pending, feedback, execute };
}

function Feedback({ result }: Readonly<{ result: AlertActionResult | null }>) {
  return result ? (
    <Notice
      title={result.ok ? "Alert change saved" : result.code}
      tone={result.ok ? "info" : "danger"}
    >
      {result.ok
        ? "The current stored state has been refreshed."
        : result.message}
    </Notice>
  ) : null;
}

export function AlertRuleCommands({
  rule,
  canWrite,
}: Readonly<{ rule: AlertRuleDetail; canWrite: boolean }>) {
  const { pending, feedback, execute } = useAlertCommand();
  const base = { rule_id: rule.id, if_match: `"${rule.id}:${rule.revision}"` };
  return (
    <div>
      <div className={styles.actions}>
        <Button
          type="button"
          disabled={
            !canWrite ||
            pending ||
            rule.lifecycle === "archived" ||
            (rule.lifecycle === "active" &&
              rule.active_version?.id === rule.latest_version.id)
          }
          onClick={() =>
            void execute({
              ...base,
              kind: "activate",
              body: { version_id: rule.latest_version.id },
            })
          }
        >
          Activate version {rule.latest_version.version_number}
        </Button>
        <Button
          type="button"
          disabled={!canWrite || pending || rule.lifecycle !== "active"}
          onClick={() => void execute({ ...base, kind: "pause" })}
        >
          Pause rule
        </Button>
        <Button
          type="button"
          disabled={!canWrite || pending || rule.lifecycle === "archived"}
          onClick={() => void execute({ ...base, kind: "archive" })}
        >
          Archive rule
        </Button>
      </div>
      <p>
        Activation replaces the active version explicitly. Archiving ends future
        evaluation; retained history remains inspectable.
      </p>
      <Feedback result={feedback} />
    </div>
  );
}

export function AlertVersionActivation({
  rule,
  version,
  canWrite,
}: Readonly<{
  rule: AlertRuleDetail;
  version: AlertRuleVersion;
  canWrite: boolean;
}>) {
  const { pending, feedback, execute } = useAlertCommand();
  return (
    <div>
      <Button
        type="button"
        disabled={
          !canWrite ||
          pending ||
          rule.lifecycle === "archived" ||
          (rule.lifecycle === "active" &&
            rule.active_version?.id === version.id)
        }
        onClick={() =>
          void execute({
            kind: "activate",
            rule_id: rule.id,
            if_match: `"${rule.id}:${rule.revision}"`,
            body: { version_id: version.id },
          })
        }
      >
        Activate saved version {version.version_number}
      </Button>
      <Feedback result={feedback} />
    </div>
  );
}

export function AlertEventCommands({
  event,
  canWrite,
}: Readonly<{ event: AlertEventDetail; canWrite: boolean }>) {
  const { pending, feedback, execute } = useAlertCommand();
  const [note, setNote] = useState("");
  function submit(input: FormEvent<HTMLFormElement>) {
    input.preventDefault();
    const kind = new FormData(
      input.currentTarget,
      (input.nativeEvent as SubmitEvent).submitter,
    ).get("action");
    if (kind !== "acknowledge" && kind !== "resolve") return;
    void execute({
      kind,
      event_id: event.id,
      if_match: `"${event.id}:${event.revision}"`,
      body: { note: note || null },
    });
  }
  return (
    <form
      onSubmit={submit}
      className={styles.form}
      aria-label="Alert event actions"
    >
      <fieldset className={styles.fields} disabled={!canWrite || pending}>
        <legend>Acknowledgment and resolution</legend>
        <p className={styles.wide}>
          Acknowledgment records that you reviewed this event. It does not
          resolve the condition. Manual resolution does not change the recorded
          evaluation.
        </p>
        <label className={styles.wide}>
          Review note (optional)
          <textarea
            value={note}
            onChange={(input) => setNote(input.target.value)}
            maxLength={1000}
          />
        </label>
        <div className={styles.actions}>
          <Button
            type="submit"
            name="action"
            value="acknowledge"
            disabled={event.acknowledgment != null}
          >
            Acknowledge event
          </Button>
          <Button
            type="submit"
            name="action"
            value="resolve"
            disabled={event.episode_state === "resolved"}
          >
            Resolve event
          </Button>
        </div>
      </fieldset>
      <div className={styles.wide}>
        <Feedback result={feedback} />
      </div>
    </form>
  );
}
