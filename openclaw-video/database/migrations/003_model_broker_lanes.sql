ALTER TABLE video_jobs
ADD COLUMN IF NOT EXISTS job_spec jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS model_api_key_cooldowns (
  provider text NOT NULL,
  key_hash text NOT NULL,
  cooldown_until timestamptz,
  rate_limit_count integer NOT NULL DEFAULT 0,
  last_selected_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, key_hash)
);

CREATE TABLE IF NOT EXISTS model_lane_leases (
  lane text NOT NULL,
  slot_index integer NOT NULL,
  lease_id uuid NOT NULL,
  worker_id text NOT NULL,
  acquired_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (lane, slot_index)
);

CREATE INDEX IF NOT EXISTS model_lane_leases_expiry_idx
ON model_lane_leases(lane, expires_at);
