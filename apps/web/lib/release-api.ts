import { API_URL } from "@/lib/api";

export interface PendingUpdate {
  version: string;
  artifact_path: string;
  sha256: string;
  platform: string;
  arch: string;
  staged_at: string;
}

export interface ReleaseInfo {
  version: string;
  platform: string;
  arch: string;
  data_dir: string;
  configured: boolean;
  pending: PendingUpdate | null;
  error: string | null;
}

export interface UpdateCheckResult {
  available: boolean;
  current_version: string;
  manifest: {
    version: string;
    channel: string;
    published_at: string;
  };
}

export async function fetchReleaseInfo(): Promise<ReleaseInfo> {
  return request<ReleaseInfo>("/api/release/info");
}

export async function checkForUpdate(): Promise<UpdateCheckResult> {
  return request<UpdateCheckResult>("/api/release/update/check", {
    method: "POST",
  });
}

export async function downloadUpdate(): Promise<PendingUpdate> {
  return request<PendingUpdate>("/api/release/update/download", {
    method: "POST",
  });
}

export async function installStagedUpdate(): Promise<PendingUpdate> {
  return request<PendingUpdate>("/api/release/update/install", {
    method: "POST",
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((payload) => (typeof payload?.detail === "string" ? payload.detail : null))
      .catch(() => null);
    throw new Error(detail ?? `API ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}
