-- Adds the steer_message column the steering feature reads/writes (see packages/core-types's
-- Checkpoint interface and CheckpointStore.requestSteer/clearSteerMessage).
--
-- Apply this against any Postgres instance that already has a `checkpoints` table from before
-- this change. A brand-new instance bootstrapped via apps/web/e2e/global-setup.ts, or any test
-- suite's own DDL, already creates the column and does not need this file.
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS steer_message TEXT;
