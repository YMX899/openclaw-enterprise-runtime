CREATE TABLE IF NOT EXISTS video_worker_registry (
  worker_id text PRIMARY KEY,
  state text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle', 'running', 'draining', 'stopped')),
  current_job_id uuid,
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  drain_requested_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS video_worker_registry_seen_idx
ON video_worker_registry(last_seen_at);
