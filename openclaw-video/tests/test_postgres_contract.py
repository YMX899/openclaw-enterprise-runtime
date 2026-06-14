from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "migrations" / "001_init.sql"
ROLLBACK = ROOT / "database" / "rollback" / "001_init_down.sql"
ADAPTER = ROOT / "src" / "openclaw_video" / "postgres_store.py"
WORKER_MAIN = ROOT / "src" / "openclaw_video" / "worker_main.py"


class PostgresContractTests(unittest.TestCase):
    def test_video_jobs_schema_contains_durable_queue_fields(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        for required in [
            "idempotency_key text",
            "worker_id text",
            "heartbeat_at timestamptz",
            "lease_expires_at timestamptz",
            "job_spec jsonb NOT NULL DEFAULT '{}'::jsonb",
            "video_jobs_lease_expiry_idx",
            "video_jobs_idempotency_idx",
            "model_api_key_cooldowns",
            "model_lane_leases",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, sql)

    def test_postgres_adapter_claims_jobs_with_skip_locked(self):
        source = ADAPTER.read_text(encoding="utf-8")
        for required in [
            "FOR UPDATE SKIP LOCKED",
            "active.bridge_session_id = video_jobs.bridge_session_id",
            "lease_expires_at = now() + make_interval",
            "ON CONFLICT (owner_principal_id, bridge_session_id, idempotency_key)",
            "DO UPDATE SET idempotency_key = video_jobs.idempotency_key",
            "WHERE idempotency_key IS NOT NULL",
            "model_api_key_cooldowns",
            "model_lane_leases",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_rollback_script_drops_bridge_objects_only(self):
        rollback = ROLLBACK.read_text(encoding="utf-8")
        for table in [
            "tenant_gateway_mapping",
            "model_lane_leases",
            "model_api_key_cooldowns",
            "user_memory",
            "video_results",
            "video_jobs",
            "bridge_messages",
            "bridge_sessions",
            "bridge_users",
        ]:
            with self.subTest(table=table):
                self.assertIn(f"DROP TABLE IF EXISTS {table};", rollback)
        self.assertNotIn("dify", rollback.lower())

    def test_worker_main_uses_postgres_queue_and_concurrency_one(self):
        source = WORKER_MAIN.read_text(encoding="utf-8")
        for required in [
            "PostgresJobStore",
            "WORKER_CONCURRENCY",
            'concurrency != 1',
            "recover_expired_leases",
            "MAX_DOWNLOAD_BYTES",
            "MAX_VIDEO_DURATION_SECONDS",
            "MAX_VIDEO_FRAMES",
            "VideoAnalysisWorker",
            "VIDEO_MODEL_MAX_CONCURRENT",
        ]:
            with self.subTest(required=required):
                self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
