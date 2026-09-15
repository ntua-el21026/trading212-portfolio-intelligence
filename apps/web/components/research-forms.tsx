"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  ResearchCitationPin,
  ResearchItemView,
  ResearchNoteContent,
  ResearchNoteRevision,
} from "@trading212/api-contracts";
import { Button, Notice } from "@trading212/ui";
import { researchHref, type ResearchQuery } from "../lib/research-query";
import { useResearchCommand } from "./research-command";
import styles from "./research-workspace.module.css";

export const researchNoteFields = [
  ["note", "Note"],
  ["thesis", "Thesis"],
  ["risks", "Risks"],
  ["catalysts", "Catalysts"],
  ["break_conditions", "Break conditions"],
] as const;

export function ResearchNoteForm({
  accountId,
  query,
  existing,
  item,
  canWrite,
}: Readonly<{
  accountId: string;
  query: ResearchQuery;
  existing?: ResearchNoteRevision;
  item?: ResearchItemView;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const [validation, setValidation] = useState<string | null>(null);
  const action = useResearchCommand((result) => {
    if (result.kind === "note")
      router.push(
        researchHref(query, {
          view: "notes",
          note: result.value.note_id,
          item: null,
          notes_cursor: null,
          versions_cursor: null,
        }),
      );
  });
  const candidates: ResearchCitationPin[] = [
    ...(existing?.content.citations ?? []),
  ];
  for (const citation of item?.source.citations ?? []) {
    if (!candidates.some((pin) => pin.citation_id === citation.citation_id))
      candidates.push({
        citation_id: citation.citation_id,
        citation_digest: citation.content_digest,
        source_version_id: citation.source.version_id,
        source_version_digest: citation.source.content_digest,
      });
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const text = (name: string) =>
      String(data.get(name) ?? "").normalize("NFC");
    const content: ResearchNoteContent = {
      title: text("title"),
      note: text("note"),
      thesis: text("thesis"),
      risks: text("risks"),
      catalysts: text("catalysts"),
      break_conditions: text("break_conditions"),
      citations: candidates.filter((pin) =>
        data.getAll("citation").includes(pin.citation_id),
      ),
    };
    if (!researchNoteFields.some(([field]) => (content[field] ?? "").trim())) {
      setValidation(
        "Add a note, thesis, risk, catalyst or break condition before saving.",
      );
      return;
    }
    setValidation(null);
    action.submit((idempotency_key) =>
      existing
        ? {
            kind: "create_version",
            account_id: accountId,
            note_id: existing.note_id,
            if_match: `"${existing.note_id}:${existing.revision}"`,
            body: { content },
            idempotency_key,
          }
        : {
            kind: "create_note",
            account_id: accountId,
            body: {
              entity_id: item?.source.entity_id ?? text("entity"),
              content,
            },
            idempotency_key,
          },
    );
  }
  return (
    <form
      onSubmit={submit}
      className={styles.form}
      aria-label={existing ? "Append owner note revision" : "Create owner note"}
      onChange={() => {
        action.changed();
        setValidation(null);
      }}
    >
      <fieldset disabled={!canWrite || action.pending}>
        <legend>
          {existing
            ? `Append revision after ${existing.revision}`
            : "Write an owner note"}
        </legend>
        <p>
          These fields are your own assessment. Saving{" "}
          {existing
            ? "appends an immutable revision"
            : "creates an account-owned note"}
          .
        </p>
        {!existing && !item ? (
          <label>
            <span>Entity ID</span>
            <input
              name="entity"
              defaultValue={query.entity ?? ""}
              required
              maxLength={36}
              autoComplete="off"
            />
          </label>
        ) : null}
        {existing || item ? (
          <p>
            Entity <code>{existing?.entity_id ?? item?.source.entity_id}</code>
          </p>
        ) : null}
        <label>
          <span>Title</span>
          <input
            name="title"
            required
            maxLength={4096}
            defaultValue={existing?.content.title ?? ""}
          />
        </label>
        {researchNoteFields.map(([field, label]) => (
          <label key={field}>
            <span>{label}</span>
            <textarea
              name={field}
              maxLength={4096}
              defaultValue={existing?.content[field] ?? ""}
            />
          </label>
        ))}
        {candidates.length ? (
          <fieldset>
            <legend>Citation references</legend>
            <p>References retain exact citation identities and digests.</p>
            {candidates.map((pin, index) => (
              <label key={pin.citation_id} className={styles.checkbox}>
                <input
                  type="checkbox"
                  name="citation"
                  value={pin.citation_id}
                  defaultChecked={
                    existing?.content.citations?.some(
                      (saved) => saved.citation_id === pin.citation_id,
                    ) ?? false
                  }
                />
                <span>
                  Citation {index + 1} · <code>{pin.citation_id}</code>
                </span>
              </label>
            ))}
          </fieldset>
        ) : null}
        <Button type="submit">
          {action.pending
            ? "Saving owner note…"
            : existing
              ? "Save new revision"
              : "Save owner note"}
        </Button>
      </fieldset>
      {!canWrite ? (
        <Notice title="Research write access required">
          Owner note changes require research:write.
        </Notice>
      ) : null}
      {validation || action.error ? (
        <p role="alert">{validation ?? action.error}</p>
      ) : null}
    </form>
  );
}

export function ResearchReviewControl({
  item,
  query,
  canWrite,
}: Readonly<{
  item: ResearchItemView;
  query: ResearchQuery;
  canWrite: boolean;
}>) {
  const router = useRouter();
  const action = useResearchCommand(() => {
    if (query.cursor) router.replace(researchHref(query, { cursor: null }));
    else router.refresh();
  });
  const reviewed =
    item.review?.revision_id === item.source.revision_id &&
    item.review.revision_digest === item.source.content_digest;
  return (
    <div className={styles.actions}>
      <p>
        {reviewed
          ? `Reviewed ${item.review!.reviewed_at}`
          : "This source revision is unreviewed."}
      </p>
      {!reviewed ? (
        <Button
          type="button"
          variant="secondary"
          disabled={!canWrite || action.pending}
          onClick={() =>
            action.submit((idempotency_key) => ({
              kind: "review",
              account_id: item.portfolio.pin.account_id,
              item_id: item.item_id,
              event_id: item.source.event_id,
              revision_id: item.source.revision_id,
              revision_digest: item.source.content_digest,
              idempotency_key,
            }))
          }
        >
          {action.pending ? "Recording review…" : "Mark this revision reviewed"}
        </Button>
      ) : null}
      {!canWrite && !reviewed ? (
        <p>Review acknowledgment requires research:write.</p>
      ) : null}
      <p>
        Review records the exact revision for this account. A material source
        correction remains unreviewed.
      </p>
      {action.error ? <p role="alert">{action.error}</p> : null}
    </div>
  );
}
