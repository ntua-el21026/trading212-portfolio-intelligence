"""Generate the six profile-pinned premium client methods over the shared transport."""

from __future__ import annotations

from typing import Any

from .typescript import ReportClientGenerator, _name, _quoted

_EXPECTED = {
    ("post", "/api/v2/report-jobs", "generate_premium_portfolio_report"),
    ("get", "/api/v2/report-jobs/{job_id}", "get_premium_report_status"),
    ("get", "/api/v2/reports", "list_premium_reports"),
    ("get", "/api/v2/reports/{report_id}", "get_premium_report_manifest"),
    (
        "post",
        "/api/v2/reports/{report_id}/artifacts/{artifact_id}/grants",
        "create_premium_report_download_grant",
    ),
    (
        "get",
        "/api/v2/reports/{report_id}/artifacts/{artifact_id}/content",
        "download_premium_report_artifact",
    ),
}


def _branches(schema: dict[str, Any]) -> set[str]:
    if set(schema) == {"$ref"}:
        return {schema["$ref"].removeprefix("#/components/schemas/")}
    if set(schema) <= {"anyOf", "title"} and "anyOf" in schema:
        branches = schema["anyOf"]
        if not branches or any(set(item) != {"$ref"} for item in branches):
            raise ValueError("Premium response unions require only exact component branches.")
        result = {item["$ref"].removeprefix("#/components/schemas/") for item in branches}
        if len(result) != len(branches):
            raise ValueError("Premium response branches are duplicated.")
        return result
    raise ValueError("Premium profile responses require the exact reviewed component branches.")


class ProfiledPremiumReportClientGenerator(ReportClientGenerator):
    def __init__(self, contract: dict[str, Any], *, imported_schemas: frozenset[str]) -> None:
        super().__init__(contract, premium=True, imported_schemas=imported_schemas)

    def _profile_query(self, operation: dict[str, Any]) -> list[dict[str, Any]]:
        query = [x for x in operation.get("parameters", []) if x["in"] == "query"]
        profile = [x for x in query if x["name"] == "profile"]
        if len(profile) != 1:
            raise ValueError("Every premium operation requires its one explicit profile query.")
        selector = profile[0]
        schema = selector["schema"]
        if (
            selector.get("required", False)
            or schema.get("enum") != ["report_sections_v2", "report_sections_v3"]
            or schema.get("default") != "report_sections_v2"
        ):
            raise ValueError("The premium profile must retain its exact profile-two default.")
        if len({x["name"] for x in query}) != len(query):
            raise ValueError("Premium query selectors are duplicated.")
        return query

    def operation(self, path: str, method: str, operation: dict[str, Any]) -> str:
        name = _name(operation["operationId"])
        query_parameters = self._profile_query(operation)
        parameters = operation.get("parameters", [])
        arguments = []
        for item in parameters:
            if item["in"] == "path":
                arguments.append(f"{item['name']}: string")
                path = path.replace(
                    "{" + item["name"] + "}",
                    "${encodeURIComponent("
                    + self.schema(item["schema"])
                    + ".parse("
                    + item["name"]
                    + "))}",
                )
        query = "undefined"
        if name != "generate_premium_portfolio_report":
            query_name = name + "Query"
            self.rendered[query_name] = self.schema(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {item["name"]: item["schema"] for item in query_parameters},
                    "required": [item["name"] for item in query_parameters if item.get("required")],
                }
            )
            arguments.append(f"query: PremiumReportQuery<P, z.input<typeof {query_name}Schema>>")
            query = f"{query_name}Schema.parse(query)"
        elif {item["name"] for item in query_parameters} != {"profile"}:
            raise ValueError(
                "Premium creation has only its profile query; account stays in the body."
            )
        if name == "download_premium_report_artifact":
            metadata = self.reference("#/components/schemas/ReportArtifactMetadata")
            arguments.append("options: ReportDownloadOptions")
            return (
                f"async {name}({', '.join(arguments)}): Promise<ReportArtifactResponse> {{\n"
                'try { return await this.#transport.download("reports", report_id, artifact_id, '
                f"{query}, options, {metadata}); }} "
                "catch (error) { if (error instanceof z.ZodError) throw new ReportApiError("
                '"VALIDATION_FAILED", 422, "The report request is invalid."); throw error; }\n}'
            )
        body = "undefined"
        if name == "generate_premium_portfolio_report":
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            if _branches(schema) != {
                "GeneratePremiumReportRequest",
                "GeneratePremiumReportRequestV3",
            }:
                raise ValueError("Premium creation must expose exactly its two typed profiles.")
            previous = self.reference("#/components/schemas/GeneratePremiumReportRequest")
            current = self.reference("#/components/schemas/GeneratePremiumReportRequestV3")
            arguments.append(
                f"body: PremiumReportValue<P, z.input<typeof {previous}>, "
                f"z.input<typeof {current}>>"
            )
            # The shared conditional helper chooses by the constructor's explicit profile.
            body = f"premiumReportSchema(this.#profile, {previous}, {current}).parse(body)"
        elif "requestBody" in operation:
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            if _branches(schema) != {"EmptyReportRequest"}:
                raise ValueError("A report grant has only the existing empty request body.")
            empty = self.reference("#/components/schemas/EmptyReportRequest")
            arguments.append(f"body: z.input<typeof {empty}>")
            body = f"{empty}.parse(body)"
        arguments.append(
            "options: ReportReadOptions = {}"
            if method == "get"
            else "options: ReportGrantOptions = {}"
            if name == "create_premium_report_download_grant"
            else "options: ReportCommandOptions"
        )
        successes = [
            value for code, value in operation["responses"].items() if code in {"200", "201", "202"}
        ]
        if len(successes) != 1:
            raise ValueError("Premium operations require one typed success response.")
        schema = successes[0]["content"]["application/json"]["schema"]
        base = {
            "generate_premium_portfolio_report": "PremiumReportJobStatus",
            "get_premium_report_status": "PremiumReportJobStatus",
            "list_premium_reports": "PremiumReportPage",
            "get_premium_report_manifest": "PremiumReportManifest",
            "create_premium_report_download_grant": "ArtifactGrant",
        }[name]
        expected = {base} if base == "ArtifactGrant" else {base, base + "V3"}
        if _branches(schema) != expected:
            raise ValueError("The premium success response differs from its closed profiles.")
        previous = self.reference("#/components/schemas/" + base)
        if base == "ArtifactGrant":
            response = previous
            output = f"z.output<typeof {previous}>"
        else:
            current = self.reference("#/components/schemas/" + base + "V3")
            response = f"premiumReportSchema(this.#profile, {previous}, {current})"
            output = (
                f"PremiumReportValue<P, z.output<typeof {previous}>, z.output<typeof {current}>>"
            )
        return (
            f"async {name}({', '.join(arguments)}): Promise<ReportApiResponse<{output}>> {{\n"
            f"try {{ return await this.#transport.request({_quoted(method.upper())}, "
            f"`{path}`, {response}, {query}, {body}, options); }} "
            "catch (error) { if (error instanceof z.ZodError) throw new ReportApiError("
            '"VALIDATION_FAILED", 422, "The report request is invalid."); throw error; }\n}'
        )

    def render(self) -> str:
        operations = []
        for path, methods in sorted(self.contract["paths"].items()):
            for method, operation in sorted(methods.items()):
                if "premium-reports" in operation.get("tags", []):
                    operations.append(self.operation(path, method, operation))
        shared = ""
        if self.used_imports:
            shared = (
                "import { "
                + ", ".join(_name(x) + "Schema" for x in sorted(self.used_imports))
                + ' } from "./reports.generated";\n'
            )
        schemas = "\n".join(
            f"export const {_name(name)}Schema = {expression};\n"
            f"export type {_name(name)} = z.infer<typeof {_name(name)}Schema>;"
            for name, expression in self.rendered.items()
        )
        return (
            "// Generated by scripts/generate_api_contract.py. Do not edit.\n"
            'import { z } from "zod";\n'
            + shared
            + "import { ReportApiError, type ReportApiResponse, type ReportReadOptions, "
            "type ReportCommandOptions, type ReportGrantOptions, type ReportDownloadOptions, "
            'type ReportArtifactResponse } from "./report-transport";\n'
            "import { PremiumReportTransport, premiumReportProfile, premiumReportSchema, "
            "type PremiumReportProfile, type PremiumReportClientOptions, type PremiumReportQuery, "
            'type PremiumReportValue } from "./premium-report-transport";\n' + schemas + "\n"
            "export class PremiumReportApiClient<P extends PremiumReportProfile = "
            '"report_sections_v2"> {\n'
            "readonly #transport: PremiumReportTransport;\nreadonly #profile: P;\n"
            "constructor(options: PremiumReportClientOptions<P>) { "
            "this.#profile = premiumReportProfile(options.profile) as P; "
            "this.#transport = new PremiumReportTransport(options, this.#profile); }\n"
            + "\n".join(operations)
            + "\n}\n"
        )


def render_profiled_premium_report_client(contract: dict[str, Any]) -> str:
    actual = {
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "premium-reports" in operation.get("tags", [])
    }
    if actual != _EXPECTED:
        raise ValueError("The fixed premium report operation inventory differs.")
    legacy = ReportClientGenerator(contract)
    legacy.render()
    return ProfiledPremiumReportClientGenerator(
        contract, imported_schemas=frozenset(legacy.rendered)
    ).render()
