import { z } from "zod";

export interface BoundedClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  headers?: () => HeadersInit | Promise<HeadersInit>;
}

export interface BoundedReadOptions {
  ifNoneMatch?: string;
}

export interface BoundedCommandOptions {
  idempotencyKey: string;
  ifMatch?: string;
}

export type BoundedApiResponse<T> =
  | { data: T; etag: string | null; notModified: false }
  | { data: null; etag: string | null; notModified: true };

export interface BoundedTransportPolicy {
  label: string;
  errors: Readonly<Record<string, string>>;
  fallbackCode: string;
  error: (code: string, status: number, message: string) => Error;
}

const errorSchema = z.object({
  error: z.object({
    code: z.string().max(80),
  }),
});

async function readBoundedJson(
  response: Response,
  policy: BoundedTransportPolicy,
): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader)
    throw policy.error(
      "INVALID_RESPONSE",
      502,
      `Empty ${policy.label} response.`,
    );
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      length += next.value.byteLength;
      if (length > 2 * 1024 * 1024) {
        await reader.cancel();
        throw policy.error(
          "RESULT_TOO_LARGE",
          502,
          `The ${policy.label} response exceeds its limit.`,
        );
      }
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    ) as unknown;
  } catch {
    throw policy.error(
      "INVALID_RESPONSE",
      502,
      `The ${policy.label} response is malformed.`,
    );
  }
}

/** Internal bounded transport; package consumers receive fixed application methods. */
export class BoundedTransport {
  constructor(
    private readonly options: BoundedClientOptions,
    private readonly policy: BoundedTransportPolicy,
  ) {}

  async request<T>(
    method: string,
    path: string,
    schema: z.ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: BoundedReadOptions | BoundedCommandOptions,
  ): Promise<BoundedApiResponse<T>> {
    const policy = this.policy;
    const url = new URL(this.options.baseUrl.replace(/\/$/, "") + path);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null)
        url.searchParams.set(key, String(value));
    }
    const headers = new Headers(await this.options.headers?.());
    headers.set("Accept", "application/json");
    if ("idempotencyKey" in options) {
      headers.set(
        "X-Idempotency-Key",
        z
          .string()
          .regex(/^[A-Za-z0-9._:-]{1,180}$/)
          .parse(options.idempotencyKey),
      );
      if (options.ifMatch !== undefined)
        headers.set("If-Match", options.ifMatch);
    } else if (options.ifNoneMatch !== undefined) {
      headers.set("If-None-Match", options.ifNoneMatch);
    }
    const serialized = body === undefined ? undefined : JSON.stringify(body);
    if (serialized !== undefined) {
      if (new TextEncoder().encode(serialized).byteLength > 65_536) {
        throw policy.error(
          "REQUEST_TOO_LARGE",
          413,
          `The ${policy.label} request exceeds 64 KiB.`,
        );
      }
      headers.set("Content-Type", "application/json");
    }
    const response = await (this.options.fetchImpl ?? fetch)(url, {
      method,
      headers,
      body: serialized,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(8_000),
    });
    const etag = response.headers.get("etag");
    if (response.status === 304) return { data: null, etag, notModified: true };
    const payload = await readBoundedJson(response, policy);
    if (!response.ok) {
      const error = errorSchema.safeParse(payload);
      const suppliedCode = error.success
        ? error.data.error.code
        : policy.fallbackCode;
      const code = Object.hasOwn(policy.errors, suppliedCode)
        ? suppliedCode
        : policy.fallbackCode;
      throw policy.error(code, response.status, policy.errors[code]);
    }
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw policy.error(
        "INVALID_RESPONSE",
        502,
        `The ${policy.label} response does not match its contract.`,
      );
    }
    return { data: parsed.data, etag, notModified: false };
  }
}
