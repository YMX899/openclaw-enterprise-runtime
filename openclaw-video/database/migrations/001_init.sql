CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS bridge_users (
  principal_id text PRIMARY KEY,
  tenant_hash text NOT NULL,
  account_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bridge_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_principal_id text NOT NULL REFERENCES bridge_users(principal_id),
  title text NOT NULL DEFAULT 'OpenClaw session',
  openclaw_routing_user text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bridge_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES bridge_sessions(id) ON DELETE CASCADE,
  owner_principal_id text NOT NULL REFERENCES bridge_users(principal_id),
  role text NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
  content text NOT NULL,
  video_url text,
  job_id uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS video_jobs (
  job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_principal_id text NOT NULL REFERENCES bridge_users(principal_id),
  bridge_session_id uuid NOT NULL REFERENCES bridge_sessions(id) ON DELETE CASCADE,
  video_url_canonical text NOT NULL,
  idempotency_key text,
  status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled')),
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0,
  error_code text,
  result_schema_version text,
  result_location text,
  worker_id text,
  heartbeat_at timestamptz,
  lease_expires_at timestamptz,
  job_spec jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS video_jobs_claim_idx
ON video_jobs(status, created_at)
WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS video_jobs_lease_expiry_idx
ON video_jobs(status, lease_expires_at)
WHERE status = 'running';

CREATE UNIQUE INDEX IF NOT EXISTS video_jobs_idempotency_idx
ON video_jobs(owner_principal_id, bridge_session_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS video_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL UNIQUE REFERENCES video_jobs(job_id) ON DELETE CASCADE,
  owner_principal_id text NOT NULL REFERENCES bridge_users(principal_id),
  schema_version text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_memory (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_principal_id text NOT NULL REFERENCES bridge_users(principal_id),
  memory_type text NOT NULL,
  content text NOT NULL,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_gateway_mapping (
  tenant_hash text PRIMARY KEY,
  gateway_url text NOT NULL,
  gateway_secret_ref text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

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
