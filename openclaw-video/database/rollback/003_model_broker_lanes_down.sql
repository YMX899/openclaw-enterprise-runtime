DROP TABLE IF EXISTS model_lane_leases;
DROP TABLE IF EXISTS model_api_key_cooldowns;
ALTER TABLE video_jobs DROP COLUMN IF EXISTS job_spec;
