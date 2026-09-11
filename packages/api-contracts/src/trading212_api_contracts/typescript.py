"""Generate closed target Zod contracts and fixed operations from the API schema."""

from __future__ import annotations

import json
import re
from typing import Any


def _name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result or result[0].isdigit():
        raise ValueError("OpenAPI schema names must be TypeScript identifiers")
    return result


def _quoted(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


class TargetClientGenerator:
    """Deliberately bounded JSON Schema subset; unsupported shapes fail generation."""

    def __init__(
        self,
        contract: dict[str, Any],
        *,
        tag: str = "targets",
        imported_schemas: frozenset[str] = frozenset(),
        imported_module: str = "./sources.generated",
    ) -> None:
        if tag not in {"targets", "planning", "sources", "historical", "xray", "reports", "alerts"}:
            raise ValueError(
                "Only fixed target, planning, source, historical and X-ray operations are supported"
            )
        self.tag = tag
        self.contract = contract
        self.definitions: dict[str, Any] = contract["components"]["schemas"]
        self.rendered: dict[str, str] = {}
        self.visiting: set[str] = set()
        if imported_module not in {"./sources.generated", "./xray.generated"}:
            raise ValueError("Only existing shared source and X-ray schema modules are supported")
        self.imported_schemas = imported_schemas
        self.imported_module = imported_module
        self.used_imports: set[str] = set()

    def reference(self, reference: str) -> str:
        prefix = "#/components/schemas/"
        if not reference.startswith(prefix):
            raise ValueError("Only local component references are supported")
        name = reference.removeprefix(prefix)
        if name in self.imported_schemas:
            self.used_imports.add(name)
            return f"{_name(name)}Schema"
        if name in self.visiting:
            raise ValueError("Recursive target contracts are not supported")
        if name not in self.rendered:
            self.visiting.add(name)
            expression = self.schema(self.definitions[name])
            self.visiting.remove(name)
            self.rendered[name] = expression
        return f"{_name(name)}Schema"

    def schema(self, schema: dict[str, Any]) -> str:
        supported = {
            "$ref",
            "type",
            "title",
            "description",
            "default",
            "examples",
            "example",
            "anyOf",
            "enum",
            "const",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "minItems",
            "maxItems",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "minLength",
            "maxLength",
            "pattern",
            "format",
        }
        if self.tag in {"sources", "xray", "reports", "alerts"}:
            supported.update({"oneOf", "discriminator"})
        if set(schema) - supported:
            raise ValueError(f"Unsupported target schema fields: {sorted(set(schema) - supported)}")
        if "$ref" in schema:
            if set(schema) - {"$ref", "title", "description", "default", "examples", "example"}:
                raise ValueError("Constraints next to a reference require an explicit schema")
            result = self.reference(schema["$ref"])
        elif "oneOf" in schema:
            discriminator = schema.get("discriminator", {})
            if set(discriminator) - {"propertyName", "mapping"}:
                raise ValueError("Unsupported response discriminator fields")
            key = discriminator.get("propertyName")
            if not isinstance(key, str) or not schema["oneOf"]:
                raise ValueError("A named closed response discriminator is required")
            mapping = {}
            for branch in schema["oneOf"]:
                if set(branch) != {"$ref"}:
                    raise ValueError("Discriminated branches require local object references")
                reference = branch["$ref"]
                definition = self.definitions.get(
                    reference.removeprefix("#/components/schemas/"), {}
                )
                selector = definition.get("properties", {}).get(key, {})
                literals = (
                    selector.get("enum", [])
                    if self.tag == "reports" and "enum" in selector
                    else [selector.get("const")]
                )
                if (
                    not literals
                    or not all(isinstance(value, str) for value in literals)
                    or any(value in mapping for value in literals)
                    or key not in definition.get("required", [])
                    or definition.get("additionalProperties") is not False
                ):
                    raise ValueError("Discriminators require distinct required string literals")
                for literal in literals:
                    mapping[literal] = reference
            if discriminator.get("mapping", mapping) != mapping:
                raise ValueError("Discriminator mapping does not match its branches")
            branches = ", ".join(self.schema(branch) for branch in schema["oneOf"])
            result = f"z.discriminatedUnion({_quoted(key)}, [{branches}])"
        elif "anyOf" in schema:
            result = f"z.union([{', '.join(self.schema(item) for item in schema['anyOf'])}])"
        elif "const" in schema:
            result = f"z.literal({_quoted(schema['const'])})"
        elif "enum" in schema:
            values = schema["enum"]
            if not values or not all(isinstance(value, str) for value in values):
                raise ValueError("Target enums must contain strings")
            result = f"z.enum({_quoted(values)})"
        elif schema.get("type") == "object":
            if schema.get("additionalProperties") is not False:
                raise ValueError("Target objects must forbid unknown fields")
            required = set(schema.get("required", []))
            fields = []
            for key, value in sorted(schema.get("properties", {}).items()):
                expression = self.schema(value)
                if key not in required:
                    expression += ".optional()"
                fields.append(f"{_quoted(key)}: {expression}")
            result = "z.strictObject({" + ", ".join(fields) + "})"
        elif schema.get("type") == "array":
            result = f"z.array({self.schema(schema['items'])})"
            for key, method in (("minItems", "min"), ("maxItems", "max")):
                if key in schema:
                    result += f".{method}({schema[key]})"
        elif schema.get("type") in {"integer", "number"}:
            result = "z.number().int()" if schema["type"] == "integer" else "z.number()"
            for key, method in (
                ("minimum", "min"),
                ("maximum", "max"),
                ("exclusiveMinimum", "gt"),
                ("exclusiveMaximum", "lt"),
            ):
                if key in schema:
                    result += f".{method}({_quoted(schema[key])})"
        elif schema.get("type") == "string":
            result = "z.string()"
            for key, method in (("minLength", "min"), ("maxLength", "max")):
                if key in schema:
                    result += f".{method}({schema[key]})"
            if "pattern" in schema:
                result += f".regex(new RegExp({_quoted(schema['pattern'])}))"
            if "format" in schema:
                match schema["format"]:
                    case "uuid":
                        result += ".uuid()"
                    case "date-time":
                        result += ".datetime({ offset: true })"
                    case "date":
                        result += ".date()"
                    case _:
                        raise ValueError("Unsupported target string format")
        elif schema.get("type") == "boolean":
            result = "z.boolean()"
        elif schema.get("type") == "null":
            result = "z.null()"
        else:
            raise ValueError(f"Unsupported target schema shape: {schema}")
        return result

    def operation(self, path: str, method: str, operation: dict[str, Any]) -> str:
        name = _name(operation["operationId"])
        parameters = operation.get("parameters", [])
        path_parameters = [item for item in parameters if item["in"] == "path"]
        query_parameters = [item for item in parameters if item["in"] == "query"]
        arguments = []
        for item in path_parameters:
            arguments.append(f"{item['name']}: string")
            expression = self.schema(item["schema"])
            path = path.replace(
                "{" + item["name"] + "}",
                "${encodeURIComponent(" + expression + ".parse(" + item["name"] + "))}",
            )
        query = "undefined"
        if query_parameters:
            query_schema = self.schema(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {item["name"]: item["schema"] for item in query_parameters},
                    "required": [item["name"] for item in query_parameters if item.get("required")],
                }
            )
            self.rendered[f"{name}Query"] = query_schema
            arguments.append(f"query: z.input<typeof {name}QuerySchema>")
            query = f"{name}QuerySchema.parse(query)"
        body = "undefined"
        if "requestBody" in operation:
            body_schema = self.schema(
                operation["requestBody"]["content"]["application/json"]["schema"]
            )
            arguments.append(f"body: z.input<typeof {body_schema}>")
            body = f"{body_schema}.parse(body)"
        if method == "get":
            arguments.append("options: TargetReadOptions = {}")
        else:
            arguments.append("options: TargetCommandOptions")
        successes = [
            response
            for code, response in operation["responses"].items()
            if code in {"200", "201", "202"}
        ]
        if len(successes) != 1:
            raise ValueError("Target operations require exactly one typed success response")
        response_schema = self.schema(successes[0]["content"]["application/json"]["schema"])
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", response_schema):
            # A closed discriminated response union needs a named schema before
            # TypeScript can refer to its inferred output type.
            response_name = f"{name}Response"
            self.rendered[response_name] = response_schema
            response_schema = f"{response_name}Schema"
        invocation = (
            f"this.#request({_quoted(method.upper())}, `{path}`, "
            f"{response_schema}, {query}, {body}, options)"
        )
        body_text = f"return {invocation};\n"
        if self.tag == "sources":
            # Source SDK errors never expose an unknown caller-supplied field name.
            body_text = (
                f"try {{ return await {invocation}; }} catch (error) {{ "
                "if (error instanceof z.ZodError) throw new SourceApiError("
                '"VALIDATION_FAILED", 422, "The reference source request is invalid."); '
                "throw error; }\n"
            )
        if self.tag == "historical":
            body_text = (
                f"try {{ return await {invocation}; }} catch (error) {{ "
                "if (error instanceof z.ZodError) throw new HistoricalApiError("
                '"VALIDATION_FAILED", 422, "The historical request is invalid."); '
                "throw error; }\n"
            )
        if self.tag == "xray":
            body_text = (
                f"try {{ return await {invocation}; }} catch (error) {{ "
                "if (error instanceof z.ZodError) throw new XrayApiError("
                '"VALIDATION_FAILED", 422, "The X-ray request is invalid."); '
                "throw error; }\n"
            )
        if self.tag == "reports":
            body_text = (
                f"try {{ return await {invocation}; }} catch (error) {{ "
                "if (error instanceof z.ZodError) throw new ReportApiError("
                '"VALIDATION_FAILED", 422, "The report request is invalid."); '
                "throw error; }\n"
            )
        return (
            f"async {name}({', '.join(arguments)}): "
            f"Promise<TargetApiResponse<z.output<typeof {response_schema}>>> {{\n"
            f"{body_text}}}"
        )

    def render(self) -> str:
        operations = []
        for path, methods in sorted(self.contract["paths"].items()):
            for method, operation in sorted(methods.items()):
                if self.tag in operation.get("tags", []):
                    if method not in {"get", "post", "patch"}:
                        raise ValueError("Unreviewed target HTTP method")
                    operations.append(self.operation(path, method, operation))
        if not operations:
            raise ValueError("No target operations found")
        schemas = "\n".join(
            f"export const {_name(name)}Schema = {expression};\n"
            f"export type {_name(name)} = z.infer<typeof {_name(name)}Schema>;"
            for name, expression in self.rendered.items()
        )
        shared_imports = ""
        if self.used_imports:
            shared_imports = (
                "import { "
                + ", ".join(f"{_name(name)}Schema" for name in sorted(self.used_imports))
                + " } from "
                + _quoted(self.imported_module)
                + ";\n"
            )
        return (
            "// Generated by scripts/generate_api_contract.py. Do not edit.\n"
            'import { z } from "zod";\n'
            f"{shared_imports}"
            "import { TargetTransport, type TargetApiResponse, type TargetReadOptions, "
            'type TargetCommandOptions, type TargetClientOptions } from "./target-transport";\n'
            f"{schemas}\n"
            "export class TargetApiClient {\n"
            "readonly #transport: TargetTransport;\n"
            "constructor(options: TargetClientOptions) { "
            "this.#transport = new TargetTransport(options); }\n"
            "#request<T>(method: string, path: string, schema: z.ZodType<T>, "
            "query: Record<string, unknown> | undefined, body: unknown, "
            "options: TargetReadOptions | TargetCommandOptions): Promise<TargetApiResponse<T>> "
            "{ return this.#transport.request(method, path, schema, query, body, options); }\n"
            + "\n".join(operations)
            + "\n}\n"
        )


def render_target_client(contract: dict[str, Any]) -> str:
    return TargetClientGenerator(contract).render()


def render_alert_client(contract: dict[str, Any]) -> str:
    """Generate exactly the thirteen admitted alert operations and closed metric union."""
    expected = {
        ("get", "/api/v1/alert-rules", "list_alert_rules"),
        ("post", "/api/v1/alert-rules", "create_alert_rule"),
        ("get", "/api/v1/alert-rules/{rule_id}", "get_alert_rule"),
        ("post", "/api/v1/alert-rules/{rule_id}/versions", "create_alert_rule_version"),
        ("post", "/api/v1/alert-rules/{rule_id}/activate", "activate_alert_rule"),
        ("post", "/api/v1/alert-rules/{rule_id}/pause", "pause_alert_rule"),
        ("post", "/api/v1/alert-rules/{rule_id}/archive", "archive_alert_rule"),
        ("get", "/api/v1/alert-events", "list_alert_events"),
        ("get", "/api/v1/alert-events/{event_id}", "get_alert_event"),
        ("post", "/api/v1/alert-events/{event_id}/acknowledgments", "acknowledge_alert_event"),
        ("post", "/api/v1/alert-events/{event_id}/resolve", "resolve_alert_event"),
        ("get", "/api/v1/accounts/{account_id}/alert-summary", "get_alert_summary"),
        ("get", "/api/v1/notification-destinations", "list_notification_destinations"),
    }
    actual = {
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "alerts" in operation.get("tags", [])
    }
    if actual != expected:
        raise ValueError("The fixed alert operation inventory differs.")
    source = TargetClientGenerator(contract, tag="sources")
    source.render()
    rendered = TargetClientGenerator(
        contract, tag="alerts", imported_schemas=frozenset(source.rendered)
    ).render()
    for name in (
        "Transport",
        "ApiClient",
        "ApiResponse",
        "ReadOptions",
        "CommandOptions",
        "ClientOptions",
    ):
        rendered = rendered.replace(f"Target{name}", f"Alert{name}")
    return rendered.replace("./target-transport", "./alert-transport")


def render_planning_client(contract: dict[str, Any]) -> str:
    """Use the same fail-closed schema subset for six fixed planning operations."""
    # Planning's optional company basis uses the exact existing X-ray models.
    # Import them instead of emitting conflicting duplicate package exports.
    source = TargetClientGenerator(contract, tag="sources")
    source.render()
    xray = TargetClientGenerator(contract, tag="xray", imported_schemas=frozenset(source.rendered))
    xray.render()
    rendered = TargetClientGenerator(
        contract,
        tag="planning",
        imported_schemas=frozenset(xray.rendered),
        imported_module="./xray.generated",
    ).render()
    for name in (
        "Transport",
        "ApiClient",
        "ApiResponse",
        "ReadOptions",
        "CommandOptions",
        "ClientOptions",
    ):
        rendered = rendered.replace(f"Target{name}", f"Planning{name}")
    return rendered.replace("./target-transport", "./planning-transport")


def render_source_client(contract: dict[str, Any]) -> str:
    """Generate the fourteen reference operations and the fixed intelligence-quality read."""
    rendered = TargetClientGenerator(contract, tag="sources").render()
    for name in (
        "Transport",
        "ApiClient",
        "ApiResponse",
        "ReadOptions",
        "CommandOptions",
        "ClientOptions",
    ):
        rendered = rendered.replace(f"Target{name}", f"Source{name}")
    return rendered.replace("./target-transport", "./source-transport").replace(
        "SourceTransport, type", "SourceTransport, SourceApiError, type"
    )


def render_historical_client(contract: dict[str, Any]) -> str:
    """Generate only the six historical reads, redacting unknown query-field names."""
    # Composite benchmark headers are shared by the existing source reads and
    # historical comparison. Import their canonical schemas without conflicting
    # duplicate package exports or changing any existing client definitions.
    source = TargetClientGenerator(contract, tag="sources")
    source.render()
    rendered = TargetClientGenerator(
        contract, tag="historical", imported_schemas=frozenset(source.rendered)
    ).render()
    for name in (
        "Transport",
        "ApiClient",
        "ApiResponse",
        "ReadOptions",
        "CommandOptions",
        "ClientOptions",
    ):
        rendered = rendered.replace(f"Target{name}", f"Historical{name}")
    return rendered.replace("./target-transport", "./historical-transport").replace(
        "HistoricalTransport, type", "HistoricalTransport, HistoricalApiError, type"
    )


def render_xray_client(contract: dict[str, Any]) -> str:
    """Generate the four closed X-ray reads using the shared license contract."""
    source = TargetClientGenerator(contract, tag="sources")
    source.render()
    rendered = TargetClientGenerator(
        contract, tag="xray", imported_schemas=frozenset(source.rendered)
    ).render()
    for name in (
        "Transport",
        "ApiClient",
        "ApiResponse",
        "ReadOptions",
        "CommandOptions",
        "ClientOptions",
    ):
        rendered = rendered.replace(f"Target{name}", f"Xray{name}")
    return rendered.replace("./target-transport", "./xray-transport").replace(
        "XrayTransport, type", "XrayTransport, XrayApiError, type"
    )


class ReportClientGenerator(TargetClientGenerator):
    """Fixed report methods with separate ephemeral grants and bounded binary downloads."""

    def __init__(self, contract: dict[str, Any]) -> None:
        super().__init__(contract, tag="reports")

    def operation(self, path: str, method: str, operation: dict[str, Any]) -> str:
        name = _name(operation["operationId"])
        if name in {"download_report_artifact", "download_export_artifact"}:
            family = "reports" if name == "download_report_artifact" else "exports"
            parent = "report_id" if family == "reports" else "export_id"
            expected = f"/api/v1/{family}/{{{parent}}}/artifacts/{{artifact_id}}/content"
            if path != expected or method != "get":
                raise ValueError("A report binary operation changed its fixed path or method")
            self.reference("#/components/schemas/ReportArtifactMetadata")
            return (
                f"async {name}({parent}: string, artifact_id: string, "
                "query: {account_id: string}, options: ReportDownloadOptions): "
                "Promise<ReportArtifactResponse> { "
                f"return this.#transport.download({_quoted(family)}, {parent}, artifact_id, "
                "query, options, ReportArtifactMetadataSchema); }"
            )
        generated = super().operation(path, method, operation)
        if name in {"create_report_download_grant", "create_export_download_grant"}:
            generated = generated.replace(
                "options: TargetCommandOptions", "options: ReportGrantOptions = {}"
            )
        return generated

    def render(self) -> str:
        rendered = super().render()
        for name in (
            "Transport",
            "ApiClient",
            "ApiResponse",
            "ReadOptions",
            "CommandOptions",
            "ClientOptions",
        ):
            rendered = rendered.replace(f"Target{name}", f"Report{name}")
        rendered = rendered.replace("./target-transport", "./report-transport")
        rendered = rendered.replace(
            "ReportTransport, type", "ReportTransport, ReportApiError, type"
        )
        rendered = rendered.replace(
            'type ReportCommandOptions, type ReportClientOptions } from "./report-transport";',
            "type ReportCommandOptions, type ReportClientOptions, type ReportGrantOptions, "
            'type ReportDownloadOptions, type ReportArtifactResponse } from "./report-transport";',
        )
        # Grant POSTs use the read-options shape only as an empty transport options bag;
        # no stable raw token replay or invented idempotency header is introduced.
        return rendered


def render_report_client(contract: dict[str, Any]) -> str:
    return ReportClientGenerator(contract).render()
