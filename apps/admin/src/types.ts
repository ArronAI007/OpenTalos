export interface TenantRecord {
  id: string;
  name: string;
  status: "active" | "disabled";
  maxConcurrency: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface ApiKeyRecord {
  id: string;
  tenantId: string;
  keyPrefix: string;
  status: "active" | "revoked";
  createdAt: string;
  lastUsedAt: string | null;
}
