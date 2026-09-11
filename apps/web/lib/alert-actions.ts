"use server";

import {
  ActivateAlertRuleRequestSchema,
  AlertApiError,
  AlertEventNoteRequestSchema,
  AlertRuleVersionRequestSchema,
  CreateAlertRuleRequestSchema,
  type AlertAcknowledgment,
  type AlertEventDetail,
  type AlertRuleDetail,
  type AlertRuleVersionDetail,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import { alertClients, alertData } from "./alert-adapter";

const identity = {
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
};
const revision = {
  if_match: z.string().regex(/^"[0-9a-f-]{36}:[1-9][0-9]*"$/),
};
const rule = { ...identity, ...revision, rule_id: z.string().uuid() };
const event = { ...identity, ...revision, event_id: z.string().uuid() };
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("create_rule"),
    ...identity,
    body: CreateAlertRuleRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("create_version"),
    ...rule,
    body: AlertRuleVersionRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("activate"),
    ...rule,
    body: ActivateAlertRuleRequestSchema,
  }),
  z.strictObject({ kind: z.literal("pause"), ...rule }),
  z.strictObject({ kind: z.literal("archive"), ...rule }),
  z.strictObject({
    kind: z.literal("acknowledge"),
    ...event,
    body: AlertEventNoteRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("resolve"),
    ...event,
    body: AlertEventNoteRequestSchema,
  }),
]);

export type AlertActionCommand = z.input<typeof commandSchema>;
export type AlertActionResult =
  | { ok: true; kind: "rule"; value: AlertRuleDetail }
  | { ok: true; kind: "version"; value: AlertRuleVersionDetail }
  | { ok: true; kind: "event"; value: AlertEventDetail }
  | { ok: true; kind: "acknowledgment"; value: AlertAcknowledgment }
  | { ok: false; code: string; message: string; fields: string[] };

export async function submitAlertCommand(
  input: unknown,
): Promise<AlertActionResult> {
  try {
    // Reauthenticate and verify the cookie action boundary on every invocation.
    const { alerts } = await alertClients(true);
    const text = JSON.stringify(input);
    if (
      text === undefined ||
      new TextEncoder().encode(text).byteLength > 65_536
    )
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The alert request exceeds 64 KiB.",
        fields: [],
      };
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message: "Review the alert fields.",
        fields: [
          ...new Set(parsed.error.issues.map((issue) => issue.path.join("."))),
        ].slice(0, 20),
      };
    const command = parsed.data;
    const options = {
      idempotencyKey: command.idempotency_key,
      ...("if_match" in command ? { ifMatch: command.if_match } : {}),
    };
    let result: AlertActionResult;
    switch (command.kind) {
      case "create_rule":
        result = {
          ok: true,
          kind: "rule",
          value: alertData(
            await alerts.create_alert_rule(command.body, options),
          ),
        };
        break;
      case "create_version":
        result = {
          ok: true,
          kind: "version",
          value: alertData(
            await alerts.create_alert_rule_version(
              command.rule_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "activate":
        result = {
          ok: true,
          kind: "rule",
          value: alertData(
            await alerts.activate_alert_rule(
              command.rule_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "pause":
        result = {
          ok: true,
          kind: "rule",
          value: alertData(
            await alerts.pause_alert_rule(command.rule_id, {}, options),
          ),
        };
        break;
      case "archive":
        result = {
          ok: true,
          kind: "rule",
          value: alertData(
            await alerts.archive_alert_rule(command.rule_id, {}, options),
          ),
        };
        break;
      case "acknowledge":
        result = {
          ok: true,
          kind: "acknowledgment",
          value: alertData(
            await alerts.acknowledge_alert_event(
              command.event_id,
              command.body,
              options,
            ),
          ),
        };
        break;
      case "resolve":
        result = {
          ok: true,
          kind: "event",
          value: alertData(
            await alerts.resolve_alert_event(
              command.event_id,
              command.body,
              options,
            ),
          ),
        };
        break;
    }
    revalidatePath("/alerts");
    return result;
  } catch (error) {
    return error instanceof AlertApiError
      ? { ok: false, code: error.code, message: error.message, fields: [] }
      : {
          ok: false,
          code: "ALERT_REQUEST_FAILED",
          message:
            "The alert operation could not complete. Your edits and retry identity are preserved.",
          fields: [],
        };
  }
}
