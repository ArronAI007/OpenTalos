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

export interface UserRecord {
  id: string;
  tenantId: string;
  username: string;
  status: "active" | "banned" | "deleted";
  createdAt: string;
  updatedAt: string;
}
