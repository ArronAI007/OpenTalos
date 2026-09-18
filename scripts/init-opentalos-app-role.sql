-- Runs automatically on first container startup (Postgres image convention:
-- /docker-entrypoint-initdb.d/*.sql). Creates the opentalos_app role ahead of any table existing
-- yet — the actual RLS policies/grants on checkpoints/trace_events are applied by
-- scripts/migrations/2026-09-18-add-checkpoints-trace-events-rls.sql once those tables exist.
CREATE ROLE opentalos_app WITH LOGIN PASSWORD 'opentalos_app';
