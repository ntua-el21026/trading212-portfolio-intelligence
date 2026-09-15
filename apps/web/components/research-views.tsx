import type {
  ResearchItemView,
  ResearchNoteRevision,
  ResearchPortfolioPreview,
  ResearchXrayPin,
} from "@trading212/api-contracts";
import { Surface } from "@trading212/ui";
import Link from "./navigation-intent";
import { researchHref, type ResearchQuery } from "../lib/research-query";
import { ResearchNoteForm, ResearchReviewControl } from "./research-forms";
import styles from "./research-workspace.module.css";

export function ResearchPin({ pin }: Readonly<{ pin: ResearchXrayPin }>) {
  return (
    <details>
      <summary>Saved portfolio context</summary>
      <dl className={styles.context}>
        <dt>X-ray run</dt>
        <dd>{pin.run_id}</dd>
        <dt>Snapshot</dt>
        <dd>{pin.snapshot_id}</dd>
        <dt>Currency</dt>
        <dd>{pin.reporting_currency}</dd>
        <dt>Valuation</dt>
        <dd>{pin.valuation_at}</dd>
        <dt>X-ray source cutoff</dt>
        <dd>{pin.source_cutoff_at}</dd>
        <dt>Quality evaluated</dt>
        <dd>{pin.quality_evaluated_at}</dd>
        <dt>Method</dt>
        <dd>
          {pin.method} · {pin.method_version} · {pin.numerical_profile}
        </dd>
        <dt>Policy</dt>
        <dd>
          {pin.policy_id} · {pin.policy_version}
        </dd>
        <dt>Input digest</dt>
        <dd>{pin.input_digest}</dd>
        <dt>Result digest</dt>
        <dd>{pin.result_digest}</dd>
      </dl>
    </details>
  );
}
export function ResearchExposure({
  value,
}: Readonly<{ value: ResearchPortfolioPreview }>) {
  return (
    <div data-testid="research-portfolio-facts">
      <h3>Portfolio facts</h3>
      <p className={styles.exposure}>
        {value.effective_exposure
          ? `${value.effective_exposure.amount} ${value.effective_exposure.currency}`
          : `Unavailable · ${value.reason ?? "captured_value_unavailable"}`}
      </p>
      <p>
        Copied from saved X-ray · {value.quality} · {value.bound} ·{" "}
        {value.origin}
      </p>
      <p>
        Company coverage{" "}
        {value.company_coverage_complete ? "complete" : "incomplete"}.
        {value.positive_unresolved_below_quantum
          ? " Positive unresolved exposure is below the display quantum."
          : ""}
      </p>
      <p>Confidence: {value.confidence ?? "unavailable"}</p>
      {value.upstream_reason ? (
        <p>Source reason: {value.upstream_reason}</p>
      ) : null}
      <details>
        <summary>Exposure evidence and warnings</summary>
        <dl className={styles.context}>
          <dt>Canonical facts digest</dt>
          <dd>{value.canonical_facts_digest}</dd>
        </dl>
        <p>
          Source references: {value.source_reference_ids.length} shown;{" "}
          {value.source_references_omitted} omitted from this preview.
        </p>
        <ul>
          {value.source_reference_ids.map((id) => (
            <li key={id}>
              <code>{id}</code>
            </li>
          ))}
        </ul>
        <p>
          Metric references: {value.metric_source_reference_ids.length} shown;{" "}
          {value.metric_sources_omitted} omitted.
        </p>
        <ul>
          {value.metric_source_reference_ids.map((id) => (
            <li key={id}>
              <code>{id}</code>
            </li>
          ))}
        </ul>
        <p>
          Paths: {value.path_keys.length} shown; {value.paths_omitted} omitted.
        </p>
        <ul>
          {value.path_keys.map((path) => (
            <li key={path}>
              <code>{path}</code>
            </li>
          ))}
        </ul>
        <p>
          Warnings: {value.warnings.length} shown; {value.warnings_omitted}{" "}
          omitted.
        </p>
        <ul>
          {value.warnings.map((warning, index) => (
            <li key={index}>
              {warning.code} · {warning.reason ?? "No additional reason"}
              <p>
                Source references{" "}
                {warning.source_reference_ids.join(", ") || "none"};{" "}
                {warning.source_references_omitted} omitted from this warning
                preview. Paths {warning.path_keys.join(", ") || "none"};{" "}
                {warning.paths_omitted} omitted.
              </p>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
export function ResearchNote({
  value,
}: Readonly<{ value: ResearchNoteRevision }>) {
  return (
    <article className={styles.note} data-testid="research-owner-note">
      <h3>{value.content.title}</h3>
      <p>
        Owner revision {value.revision} · {value.created_at}
      </p>
      <dl className={styles.context}>
        {(
          [
            ["note", "Note"],
            ["thesis", "Thesis"],
            ["risks", "Risks"],
            ["catalysts", "Catalysts"],
            ["break_conditions", "Break conditions"],
          ] as const
        ).map(([field, label]) => (
          <div className={styles.definition} key={field}>
            <dt>{label}</dt>
            <dd className={styles.prose}>
              {value.content[field] || "Not supplied"}
            </dd>
          </div>
        ))}
      </dl>
      <details>
        <summary>Owner revision identity and citation references</summary>
        <dl className={styles.context}>
          <dt>Note</dt>
          <dd>{value.note_id}</dd>
          <dt>Revision</dt>
          <dd>{value.revision_id}</dd>
          <dt>Entity</dt>
          <dd>{value.entity_id}</dd>
          <dt>Actor</dt>
          <dd>{value.actor_id}</dd>
          <dt>Previous revision</dt>
          <dd>{value.previous_revision_id ?? "First revision"}</dd>
          <dt>Digest</dt>
          <dd>{value.content_digest}</dd>
        </dl>
        <ul>
          {value.content.citations?.map((pin) => (
            <li key={pin.citation_id}>
              Citation {pin.citation_id} · {pin.citation_digest}
              <br />
              Source {pin.source_version_id} · {pin.source_version_digest}
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}
export function ResearchItem({
  item,
  query,
  canWrite,
  detailed = false,
}: Readonly<{
  item: ResearchItemView;
  query: ResearchQuery;
  canWrite: boolean;
  detailed?: boolean;
}>) {
  const facts = item.source.facts;
  const title = facts.kind === "news" ? facts.title : facts.company_name;
  return (
    <Surface>
      <article data-testid="research-item">
        <h2>{title}</h2>
        <p>
          Entity <code>{item.source.entity_id}</code>
        </p>
        <p>Research source cutoff: {item.source_cutoff_at}</p>
        <div className={styles.columns}>
          <section aria-label="Source facts">
            <h3>Source facts</h3>
            <p>
              {facts.publisher} · {facts.kind}
            </p>
            <p className={styles.prose}>
              {facts.kind === "news" ? facts.summary : facts.description}
            </p>
            <p>
              Published:{" "}
              {facts.published_at ??
                "Unavailable · provider_publication_unavailable"}
            </p>
            <p>
              Source revision {item.source.revision} · retained until{" "}
              {item.source.expires_at}
            </p>
            {item.source.citations.some(
              (citation) => citation.source.synthetic,
            ) ? (
              <p>Synthetic fixture source</p>
            ) : null}
          </section>
          <ResearchExposure value={item.portfolio} />
        </div>
        {!detailed ? (
          <Link
            prefetch={false}
            href={researchHref(query, {
              view: "item",
              item: item.item_id,
              xray: item.portfolio.pin.run_id,
              cutoff: item.source_cutoff_at,
            })}
          >
            Open research item
          </Link>
        ) : null}
        <ResearchReviewControl
          key={`${item.item_id}:${item.source.revision_id}`}
          item={item}
          query={query}
          canWrite={canWrite}
        />
        {detailed ? (
          <>
            <details>
              <summary>Original source citations and permissions</summary>
              {item.source.citations.map((citation, index) => (
                <section key={citation.citation_id} className={styles.citation}>
                  <h3>Citation {index + 1}</h3>
                  <dl className={styles.context}>
                    <dt>Citation</dt>
                    <dd>{citation.citation_id}</dd>
                    <dt>Citation digest</dt>
                    <dd>{citation.content_digest}</dd>
                    <dt>Provider</dt>
                    <dd>
                      {citation.source.provider} · {citation.source.provider_id}
                    </dd>
                    <dt>Source version</dt>
                    <dd>{citation.source.version_id}</dd>
                    <dt>Source digest</dt>
                    <dd>{citation.source.content_digest}</dd>
                    <dt>Facts digest</dt>
                    <dd>{citation.facts_digest}</dd>
                    <dt>First known</dt>
                    <dd>{citation.source.first_known_at}</dd>
                    <dt>Observed</dt>
                    <dd>{citation.source.observed_at}</dd>
                    <dt>Original source cutoff</dt>
                    <dd>{citation.source.source_cutoff_at}</dd>
                    <dt>Retained</dt>
                    <dd>{citation.source.retained_at}</dd>
                    <dt>Expires</dt>
                    <dd>{citation.source.expires_at}</dd>
                    <dt>License</dt>
                    <dd>
                      {citation.source.license_version_id} ·{" "}
                      {citation.source.license.version}
                    </dd>
                    <dt>Attribution</dt>
                    <dd>{citation.source.license.attribution}</dd>
                    <dt>Store / display</dt>
                    <dd>
                      {citation.source.license.store} /{" "}
                      {citation.source.license.display}
                    </dd>
                  </dl>
                </section>
              ))}
            </details>
            <ResearchPin pin={item.portfolio.pin} />
            <section aria-label="Owner notes">
              <h3>Owner notes</h3>
              {item.owner_revisions.length ? (
                item.owner_revisions.map((note) => (
                  <div key={note.revision_id}>
                    <ResearchNote value={note} />
                    <Link
                      prefetch={false}
                      href={researchHref(query, {
                        view: "notes",
                        note: note.note_id,
                        item: null,
                      })}
                    >
                      Edit note and view history
                    </Link>
                  </div>
                ))
              ) : (
                <p>No owner notes for this entity.</p>
              )}
              {item.owner_revisions_omitted ? (
                <p>
                  {item.owner_revisions_omitted} additional owner notes are
                  outside this preview. Open Owner notes to page the full
                  collection.
                </p>
              ) : null}
              <ResearchNoteForm
                key={`${item.item_id}:new-note`}
                accountId={item.portfolio.pin.account_id}
                query={query}
                item={item}
                canWrite={canWrite}
              />
            </section>
            <p>Optional synthesis: unavailable · {item.synthesis.reason}</p>
          </>
        ) : null}
      </article>
    </Surface>
  );
}
