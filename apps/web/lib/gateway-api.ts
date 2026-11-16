export const GATEWAY_URL =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://127.0.0.1:3425";

export interface GatewayHealth {
  status: string;
  service: string;
}

export interface GatewayUsageSummary {
  requests: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  accounts: Array<{
    provider: string;
    account_name: string;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    requests: number;
  }>;
}

export interface GatewayRequest {
  id: string;
  created_at: string;
  finished_at: string | null;
  model_requested: string;
  model_resolved: string | null;
  provider: string | null;
  account_name: string | null;
  stream: boolean;
  client: string | null;
  status: string;
  http_status: number | null;
  duration_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  error: string | null;
  routing_trace: Record<string, unknown> | null;
}

async function gatewayJson<T>(path: string): Promise<T> {
  const response = await fetch(`${GATEWAY_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Gateway ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function fetchGatewayHealth(): Promise<GatewayHealth> {
  return gatewayJson("/health");
}

export async function fetchGatewayUsage(): Promise<GatewayUsageSummary> {
  return gatewayJson("/v1/magpie/usage");
}

export async function listGatewayRequests(limit = 50): Promise<GatewayRequest[]> {
  return gatewayJson<{ requests: GatewayRequest[] }>(
    `/v1/magpie/requests?limit=${Math.max(1, Math.min(limit, 200))}`
  ).then((data) => data.requests);
}

export function gatewayEndpoint(path: string): string {
  return `${GATEWAY_URL.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}
