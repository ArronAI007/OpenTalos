-- Adds the users table this feature reads/writes (see packages/postgres-tenancy's UserStore).
--
-- Apply this against any Postgres instance that already has tenants/api_keys tables from before
-- this change. A brand-new instance bootstrapped via apps/web/e2e/global-setup.ts, or any test
-- suite's own DDL, already creates this table and does not need this file.
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL UNIQUE,
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_idx ON users (lower(username));
