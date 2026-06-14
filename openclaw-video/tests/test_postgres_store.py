from datetime import UTC, datetime, timedelta
import unittest

from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import JobLeaseError
from openclaw_video.postgres_store import Jsonb, PostgresJobStore, PostgresSessionStore


def job_row(**overrides):
    now = datetime(2026, 6, 6, tzinfo=UTC)
    row = {
        "job_id": "job-1",
        "owner_principal_id": "owner",
        "bridge_session_id": "session",
        "video_url_canonical": "https://v.douyin.com/abc",
        "status": "queued",
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "attempt_count": 0,
        "error_code": None,
        "result_schema_version": None,
        "result_location": None,
        "idempotency_key": None,
        "worker_id": None,
        "heartbeat_at": None,
        "lease_expires_at": None,
        "job_spec": {},
    }
    row.update(overrides)
    return row


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.queries.append((sql, params))

    def fetchone(self):
        if not self.connection.results:
            return None
        return self.connection.results.pop(0)

    def fetchall(self):
        if not self.connection.results:
            return []
        return self.connection.results.pop(0)


class FakeConnection:
    def __init__(self, results):
        self.results = list(results)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return FakeCursor(self)


class PostgresJobStoreTests(unittest.TestCase):
    def test_create_job_idempotency_conflict_returns_existing_without_changing_url(self):
        fake = FakeConnection([job_row(idempotency_key="same-request")])
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.create_job(
            "owner",
            "session",
            "https://v.douyin.com/changed",
            idempotency_key="same-request",
        )
        sql, params = fake.queries[0]
        self.assertIn("ON CONFLICT (owner_principal_id, bridge_session_id, idempotency_key)", sql)
        self.assertIn("DO UPDATE SET idempotency_key = video_jobs.idempotency_key", sql)
        self.assertEqual(params[:5], ("owner", "session", "https://v.douyin.com/changed", "same-request", "queued"))
        self.assertEqual(job.video_url_canonical, "https://v.douyin.com/abc")
        self.assertEqual(job.idempotency_key, "same-request")

    def test_claim_next_uses_worker_lease_parameters(self):
        now = datetime(2026, 6, 6, tzinfo=UTC)
        fake = FakeConnection(
            [
                job_row(
                    status="running",
                    started_at=now,
                    attempt_count=1,
                    worker_id="worker-a",
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=120),
                )
            ]
        )
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.claim_next("worker-a", 120)
        sql, params = fake.queries[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", sql)
        self.assertIn("active.bridge_session_id = video_jobs.bridge_session_id", sql)
        self.assertEqual(params, ("worker-a", 120))
        self.assertEqual(job.status, JobStatus.RUNNING)
        self.assertEqual(job.worker_id, "worker-a")

    @unittest.skipIf(Jsonb is None, "psycopg Jsonb adapter is not installed")
    def test_complete_job_with_worker_id_requires_current_lease(self):
        fake = FakeConnection(
            [
                job_row(
                    status="succeeded",
                    worker_id=None,
                    result_schema_version="schema",
                    result_location="postgres://video_results/job-1",
                )
            ]
        )
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.complete_job("job-1", {"ok": True}, "schema", worker_id="worker-a")
        sql, params = fake.queries[0]
        self.assertIn("AND worker_id = %s", sql)
        self.assertIn("AND status = 'running'", sql)
        self.assertEqual(params, ("schema", "postgres://video_results/job-1", "job-1", "worker-a"))
        self.assertEqual(job.status, JobStatus.SUCCEEDED)

    @unittest.skipIf(Jsonb is None, "psycopg Jsonb adapter is not installed")
    def test_complete_job_with_stale_worker_raises_lease_error(self):
        fake = FakeConnection([None])
        store = PostgresJobStore(connection_factory=lambda: fake)
        with self.assertRaises(JobLeaseError):
            store.complete_job("job-1", {"ok": True}, "schema", worker_id="worker-a")

    def test_recover_expired_leases_returns_database_count(self):
        fake = FakeConnection([[{"job_id": "job-1"}, {"job_id": "job-2"}]])
        store = PostgresJobStore(connection_factory=lambda: fake)
        recovered = store.recover_expired_leases()
        sql, _params = fake.queries[0]
        self.assertIn("lease_expires_at < now()", sql)
        self.assertEqual(recovered, 2)

    def test_count_active_jobs_counts_only_queued_and_running_for_owner(self):
        fake = FakeConnection([{"active_count": 2}])
        store = PostgresJobStore(connection_factory=lambda: fake)
        active = store.count_active_jobs("owner")
        sql, params = fake.queries[0]
        self.assertIn("status IN ('queued', 'running')", sql)
        self.assertEqual(params, ("owner",))
        self.assertEqual(active, 2)

    def test_create_job_persists_job_spec_parameter(self):
        fake = FakeConnection([job_row(job_spec={"provider": "bailian"})])
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.create_job("owner", "session", "https://v.douyin.com/abc", job_spec={"provider": "bailian"})
        sql, params = fake.queries[0]
        self.assertIn("job_spec", sql)
        self.assertEqual(params[0:4], ("owner", "session", "https://v.douyin.com/abc", "queued"))
        self.assertEqual(job.job_spec["provider"], "bailian")

    def test_api_key_cooldown_queries_use_hashes_only(self):
        fake = FakeConnection([[{"provider": "bailian", "key_hash": "abc", "rate_limit_count": 1}]])
        store = PostgresJobStore(connection_factory=lambda: fake)
        rows = store.list_api_key_cooldowns("bailian", ["abc"])
        sql, params = fake.queries[0]
        self.assertIn("model_api_key_cooldowns", sql)
        self.assertEqual(params, ("bailian", ["abc"]))
        self.assertIn("abc", rows)

    def test_lane_lease_acquire_uses_slots(self):
        fake = FakeConnection([{"lease_id": "lease-1", "slot_index": 3}])
        store = PostgresJobStore(connection_factory=lambda: fake)
        lease = store.acquire_lane_lease("video_model_request", worker_id="worker-a", max_concurrent=200, lease_seconds=900)
        self.assertEqual(lease, ("lease-1", 3))
        self.assertIn("generate_series", fake.queries[1][0])

    def test_get_job_by_idempotency_uses_owner_session_and_key(self):
        fake = FakeConnection([job_row(idempotency_key="same-request")])
        store = PostgresJobStore(connection_factory=lambda: fake)
        job = store.get_job_by_idempotency("owner", "session", "same-request")
        sql, params = fake.queries[0]
        self.assertIn("owner_principal_id = %s", sql)
        self.assertIn("bridge_session_id = %s", sql)
        self.assertIn("idempotency_key = %s", sql)
        self.assertEqual(params, ("owner", "session", "same-request"))
        self.assertEqual(job.idempotency_key, "same-request")

    def test_cleanup_terminal_jobs_before_returns_deleted_ids_and_upload_uris(self):
        cutoff = datetime(2026, 6, 1, tzinfo=UTC)
        fake = FakeConnection(
            [
                {
                    "deleted_jobs": 2,
                    "deleted_results": 1,
                    "deleted_job_ids": [
                        "11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222",
                    ],
                    "upload_uris": ["upload://11111111-1111-1111-1111-111111111111/sample.mp4"],
                }
            ]
        )
        store = PostgresJobStore(connection_factory=lambda: fake)
        result = store.cleanup_terminal_jobs_before("owner", cutoff)

        sql, params = fake.queries[0]
        self.assertIn("WITH doomed AS", sql)
        self.assertIn("owner_principal_id = %s", sql)
        self.assertIn("DELETE FROM video_results", sql)
        self.assertIn("DELETE FROM video_jobs", sql)
        self.assertIn("array_agg(job_id::text)", sql)
        self.assertEqual(params, ("owner", cutoff, "owner", "owner"))
        self.assertEqual(result.deleted_jobs, 2)
        self.assertEqual(result.deleted_results, 1)
        self.assertEqual(
            result.deleted_job_ids,
            (
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ),
        )
        self.assertEqual(result.upload_uris, ("upload://11111111-1111-1111-1111-111111111111/sample.mp4",))


class PostgresSessionStoreTests(unittest.TestCase):
    def test_delete_messages_for_jobs_is_scoped_by_owner_and_job_ids(self):
        fake = FakeConnection([[{"id": "message-1"}, {"id": "message-2"}]])
        store = PostgresSessionStore(connection_factory=lambda: fake)
        deleted = store.delete_messages_for_jobs(
            "owner",
            (
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ),
        )

        sql, params = fake.queries[0]
        self.assertIn("DELETE FROM bridge_messages", sql)
        self.assertIn("owner_principal_id = %s", sql)
        self.assertIn("job_id = ANY(%s::uuid[])", sql)
        self.assertEqual(
            params,
            (
                "owner",
                [
                    "11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                ],
            ),
        )
        self.assertEqual(deleted, 2)


if __name__ == "__main__":
    unittest.main()
