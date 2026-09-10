import { Pool } from "pg";

const DATABASE_URL = "postgres://postgres:postgres@localhost:5433/postgres";

export default async function globalSetup(): Promise<void> {
  const pool = new Pool({ connectionString: DATABASE_URL });
  await pool.query(`
    DROP TABLE IF EXISTS trace_events;
    DROP TABLE IF EXISTS tasks;
    DROP TABLE IF EXISTS checkpoints;

    CREATE TABLE checkpoints (
      run_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      node_cursor JSONB NOT NULL, state JSONB NOT NULL, pending_yields JSONB NOT NULL, status TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE tasks (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, graph_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      kind TEXT NOT NULL, resume_value JSONB, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3, timeout_ms INTEGER NOT NULL DEFAULT 30000, priority INTEGER NOT NULL DEFAULT 0,
      available_at TIMESTAMPTZ NOT NULL DEFAULT now(), locked_at TIMESTAMPTZ, error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE TABLE trace_events (
      id SERIAL PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, session_id TEXT NOT NULL,
      type TEXT NOT NULL, payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  `);
  await pool.end();
}
