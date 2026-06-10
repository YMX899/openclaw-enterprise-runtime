-- 002 user prefs: cross-device UI preferences (theme + per-session overrides).
-- Additive only; does not touch existing tables. Rollback = drop this table.
CREATE TABLE IF NOT EXISTS bridge_user_prefs (
  principal_id text PRIMARY KEY REFERENCES bridge_users(principal_id),
  prefs jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
