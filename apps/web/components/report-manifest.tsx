import styles from "./report-view.module.css";
import type {
  ExportJobStatus,
  ReportJobStatus,
  ReportManifest,
} from "@trading212/api-contracts";
import { Surface } from "@trading212/ui";
import { formatDateTime, titleCase } from "../lib/format";
import { ReportDownloadButton } from "./report-download";

export function ReportArtifacts({
  job,
}: Readonly<{ job: ReportJobStatus | ExportJobStatus }>) {
  if (job.state !== "succeeded") return null;
  const family = "job_id" in job ? "reports" : "exports";
  const parentId = "job_id" in job ? job.job_id : job.export_id;
  return (
    <Surface className={styles.surface} aria-label="Report artifacts">
      <h2>Private artifacts</h2>
      <ul>
        {job.artifacts.map((artifact) => (
          <li key={artifact.artifact_id} style={{ overflowWrap: "anywhere" }}>
            <h3>{artifact.format.toUpperCase()}</h3>
            <p>
              {artifact.byte_length.toLocaleString("en-GB")} bytes · expires{" "}
              {formatDateTime(artifact.expires_at)}
            </p>
            <p className="mono">SHA-256 {artifact.content_digest}</p>
            <ReportDownloadButton
              accountId={job.account_id}
              parentId={parentId}
              family={family}
              artifact={artifact}
            />
          </li>
        ))}
      </ul>
    </Surface>
  );
}

export function ReportManifestCard({
  manifest,
}: Readonly<{ manifest: ReportManifest }>) {
  return (
    <Surface className={styles.surface} aria-label="Report manifest">
      <h2>Manifest and provenance</h2>
      <p>
        {manifest.method} · version {manifest.method_version} ·{" "}
        {manifest.renderer_profile.template_version}
      </p>
      <p>
        {manifest.document.selection.reporting_currency} · valuation{" "}
        {formatDateTime(manifest.document.valuation_at)} · source cutoff{" "}
        {formatDateTime(manifest.document.selection.source_cutoff_at)}
      </p>
      <p>
        Rendering profile {manifest.renderer_profile.profile_version}.
        Accessibility profile{" "}
        {manifest.renderer_profile.accessibility_profile_version}; PDF/UA
        compliance is not claimed.
      </p>
      <details>
        <summary>Complete section and dataset coverage</summary>
        <ul>
          {manifest.document.tables.map((table) => (
            <li key={table.table} style={{ overflowWrap: "anywhere" }}>
              {titleCase(table.table)}: {table.state} · {table.row_count} rows ·{" "}
              {table.content_digest}
              {table.reason_key ? ` · reason ${table.reason_key}` : ""}
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>
          Sources ({manifest.source_references.length}) and immutable inputs
        </summary>
        <ul>
          {manifest.bindings.map((pin) => (
            <li
              key={`${pin.family}:${pin.role}:${pin.subject_id}`}
              style={{ overflowWrap: "anywhere" }}
            >
              {pin.family} / {pin.role}: {pin.subject_id} · {pin.content_digest}
            </li>
          ))}
        </ul>
        <ul>
          {manifest.source_references.map((source) => (
            <li key={source.key} style={{ overflowWrap: "anywhere" }}>
              {source.kind}: {source.subject_id} · {source.content_digest}
              {source.source_at ? ` · ${formatDateTime(source.source_at)}` : ""}
              {source.license_version_id
                ? ` · license ${source.license_version_id}`
                : ""}
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>
          Licenses and attribution ({manifest.license_references.length})
        </summary>
        <ul>
          {manifest.license_references.map((license) => (
            <li key={license.version_id} style={{ overflowWrap: "anywhere" }}>
              {license.attribution} · version {license.version_id} · report{" "}
              {license.pinned_report}, export {license.pinned_export}, store{" "}
              {license.pinned_store} · {license.license_digest}
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>
          Warnings, assumptions and limitations ({manifest.notes.length})
        </summary>
        <ul>
          {manifest.notes.map((note) => (
            <li key={note.key}>
              <strong>{titleCase(note.kind)}:</strong> {note.text}
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Renderer and font versions</summary>
        <ul>
          {manifest.renderer_profile.renderer_versions.map((renderer) => (
            <li key={renderer.format}>
              {renderer.format}: {renderer.name} {renderer.version}
            </li>
          ))}
          {manifest.renderer_profile.fonts.map((font) => (
            <li key={font.content_digest} style={{ overflowWrap: "anywhere" }}>
              {font.name} {font.version} · {font.content_digest}
            </li>
          ))}
        </ul>
      </details>
    </Surface>
  );
}
