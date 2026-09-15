import { z } from "zod";

import {
  ReportApiError,
  ReportTransport,
  type ReportApiResponse,
  type ReportArtifactResponse,
  type ReportClientOptions,
  type ReportCommandOptions,
  type ReportDownloadOptions,
  type ReportReadOptions,
} from "./report-transport";
import type { ReportArtifactMetadata } from "./reports.generated";

export type PremiumReportProfile =
  "report_sections_v2" | "report_sections_v3" | "report_sections_v4";
export type PremiumReportClientOptions<
  P extends PremiumReportProfile = "report_sections_v2",
> = ReportClientOptions & { profile?: P } & (P extends "report_sections_v2"
    ? unknown
    : { profile: P });
export type PremiumReportQuery<P extends PremiumReportProfile, Q> = Omit<
  Q,
  "profile"
> & { profile?: P };
export type PremiumReportValue<
  P extends PremiumReportProfile,
  V2,
  V3,
  V4 = never,
> = P extends "report_sections_v4"
  ? V4
  : P extends "report_sections_v3"
    ? V3
    : V2;

export function premiumReportProfile(value: unknown): PremiumReportProfile {
  if (value === undefined || value === "report_sections_v2")
    return "report_sections_v2";
  if (value === "report_sections_v3") return "report_sections_v3";
  if (value === "report_sections_v4") return "report_sections_v4";
  throw invalidProfile();
}

function invalidProfile(): ReportApiError {
  return new ReportApiError(
    "VALIDATION_FAILED",
    422,
    "The explicit report profile is invalid.",
  );
}

/** Constructor-pinned schemas never infer a report profile from response shape. */
export function premiumReportSchema<
  P extends PremiumReportProfile,
  V2,
  V3,
  V4 = never,
>(
  profile: P,
  previous: z.ZodType<V2>,
  current: z.ZodType<V3>,
  projection?: z.ZodType<V4>,
): z.ZodType<PremiumReportValue<P, V2, V3, V4>> {
  if (profile === "report_sections_v4" && !projection) throw invalidProfile();
  return (
    profile === "report_sections_v4"
      ? projection
      : profile === "report_sections_v3"
        ? current
        : previous
  ) as z.ZodType<PremiumReportValue<P, V2, V3, V4>>;
}

function scopedQuery(
  profile: PremiumReportProfile,
  query: Record<string, unknown> | undefined,
): Record<string, unknown> | undefined {
  if (query === undefined) return undefined;
  if (
    Object.hasOwn(query, "profile") &&
    query.profile !== undefined &&
    query.profile !== profile
  )
    throw invalidProfile();
  const { profile: _profile, ...remaining } = query;
  void _profile;
  return remaining;
}

/** Reuses all verified bounded report/grant/download logic; V1 transport is untouched. */
export class PremiumReportTransport extends ReportTransport {
  readonly #profile: PremiumReportProfile;

  constructor(
    options: ReportClientOptions,
    selected: PremiumReportProfile = "report_sections_v2",
  ) {
    const profile = premiumReportProfile(selected);
    super(
      {
        ...options,
        fetchImpl: async (input, init) => {
          const url = new URL(
            input instanceof Request ? input.url : String(input),
          );
          const supplied = url.searchParams.getAll("profile");
          if (
            supplied.length > 1 ||
            (supplied.length === 1 && supplied[0] !== profile)
          )
            throw invalidProfile();
          if (profile !== "report_sections_v2")
            url.searchParams.set("profile", profile);
          else url.searchParams.delete("profile");
          return (options.fetchImpl ?? fetch)(url, init);
        },
      },
      2,
    );
    this.#profile = profile;
  }

  override async request<T>(
    method: string,
    path: string,
    schema: z.ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: ReportReadOptions | ReportCommandOptions,
  ): Promise<ReportApiResponse<T>> {
    const scoped = scopedQuery(this.#profile, query);
    if (method === "POST" && path === "/api/v2/report-jobs") {
      if (typeof body !== "object" || body === null) throw invalidProfile();
      const supplied =
        "profile_version" in body ? body.profile_version : undefined;
      if (
        (this.#profile === "report_sections_v2" && supplied !== undefined) ||
        (this.#profile !== "report_sections_v2" && supplied !== this.#profile)
      )
        throw invalidProfile();
      if (this.#profile === "report_sections_v4") {
        if (!("premium_run" in body) || !("sections" in body))
          throw invalidProfile();
        const pin = body.premium_run;
        if (
          typeof pin !== "object" ||
          pin === null ||
          !("family" in pin) ||
          pin.family !== "projection" ||
          !Array.isArray(body.sections)
        )
          throw invalidProfile();
        const selected = body.sections.filter(
          (item: unknown) =>
            item === "risk" ||
            item === "scenario" ||
            item === "projection" ||
            item === "goal" ||
            item === "research",
        );
        if (
          selected.filter((item: unknown) => item === "projection").length !==
            1 ||
          selected.filter((item: unknown) => item === "goal").length > 1 ||
          selected.some(
            (item: unknown) => item !== "projection" && item !== "goal",
          )
        )
          throw invalidProfile();
      }
      if (this.#profile === "report_sections_v3") {
        if (!("premium_run" in body) || !("sections" in body))
          throw invalidProfile();
        const pin = body.premium_run;
        if (typeof pin !== "object" || pin === null || !("family" in pin))
          throw invalidProfile();
        if (pin.family !== "risk" && pin.family !== "scenario")
          throw invalidProfile();
        if (!Array.isArray(body.sections)) throw invalidProfile();
        const premiumSections = body.sections.filter(
          (item: unknown) =>
            item === "risk" ||
            item === "scenario" ||
            item === "projection" ||
            item === "goal" ||
            item === "research",
        );
        if (premiumSections.length !== 1 || premiumSections[0] !== pin.family)
          throw invalidProfile();
      }
    }
    return super.request(method, path, schema, scoped, body, options);
  }

  override async download(
    family: "reports" | "exports",
    parentId: string,
    artifactId: string,
    query: { account_id: string; profile?: PremiumReportProfile },
    options: ReportDownloadOptions,
    metadataSchema: z.ZodType<ReportArtifactMetadata>,
  ): Promise<ReportArtifactResponse> {
    const scoped = scopedQuery(this.#profile, query);
    const account = z
      .strictObject({ account_id: z.string().uuid() })
      .safeParse(scoped);
    if (!account.success) throw invalidProfile();
    return super.download(
      family,
      parentId,
      artifactId,
      account.data,
      options,
      metadataSchema,
    );
  }
}
