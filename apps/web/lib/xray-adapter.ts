import "server-only";

import {
  XrayApiClient,
  XrayApiError,
  type XrayApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export async function xrayClients() {
  const clients = await targetClients();
  return { ...clients, xray: new XrayApiClient(clients.options) };
}

export function xrayData<T>(response: XrayApiResponse<T>): T {
  if (response.notModified)
    throw new XrayApiError(
      "INVALID_RESPONSE",
      502,
      "The X-ray response had no content.",
    );
  return response.data;
}
