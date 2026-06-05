import unittest
from datetime import timedelta

from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import InMemoryJobStore, JobLeaseError, JobNotFound, JobOwnershipError


class JobStoreTests(unittest.TestCase):
    def test_claim_next_moves_queued_to_running_once(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        claimed = store.claim_next()
        self.assertEqual(claimed.job_id, job.job_id)
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.attempt_count, 1)
        self.assertEqual(claimed.worker_id, "worker")
        self.assertIsNotNone(claimed.lease_expires_at)
        self.assertIsNone(store.claim_next())

    def test_create_job_idempotency_key_returns_existing_job(self):
        store = InMemoryJobStore()
        first = store.create_job(
            "owner",
            "session",
            "https://v.douyin.com/abc",
            idempotency_key="same-request",
        )
        second = store.create_job(
            "owner",
            "session",
            "https://v.douyin.com/abc",
            idempotency_key="same-request",
        )
        self.assertEqual(first.job_id, second.job_id)

    def test_owner_isolation(self):
        store = InMemoryJobStore()
        job = store.create_job("owner-a", "session", "https://v.douyin.com/abc")
        with self.assertRaises(JobOwnershipError):
            store.get_job(job.job_id, "owner-b")

    def test_complete_stores_result(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next()
        completed = store.complete_job(job.job_id, {"ok": True}, "schema")
        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(store.get_result(job.job_id, "owner").result, {"ok": True})

    def test_complete_rejects_stale_worker(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a")
        with self.assertRaises(JobLeaseError):
            store.complete_job(job.job_id, {"ok": True}, "schema", worker_id="worker-b")

    def test_fail_rejects_stale_worker(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a")
        with self.assertRaises(JobLeaseError):
            store.fail_job(job.job_id, "tool_failed", worker_id="worker-b")

    def test_heartbeat_extends_current_worker_lease(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a", lease_seconds=1)
        updated = store.heartbeat_job(job.job_id, "worker-a", lease_seconds=30)
        self.assertEqual(updated.worker_id, "worker-a")
        self.assertGreater(updated.lease_expires_at, updated.heartbeat_at)

    def test_heartbeat_rejects_wrong_worker(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        store.claim_next("worker-a")
        with self.assertRaises(JobLeaseError):
            store.heartbeat_job(job.job_id, "worker-b")

    def test_recover_expired_lease_requeues_job(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        claimed = store.claim_next("worker-a", lease_seconds=1)
        recovered = store.recover_expired_leases(now=claimed.lease_expires_at + timedelta(seconds=1))
        self.assertEqual(recovered, 1)
        requeued = store.get_job(job.job_id)
        self.assertEqual(requeued.status, JobStatus.QUEUED)
        self.assertIsNone(requeued.worker_id)
        reclaimed = store.claim_next("worker-b")
        self.assertEqual(reclaimed.job_id, job.job_id)
        self.assertEqual(reclaimed.attempt_count, 2)

    def test_cancel_enforces_owner(self):
        store = InMemoryJobStore()
        job = store.create_job("owner-a", "session", "https://v.douyin.com/abc")
        with self.assertRaises(JobOwnershipError):
            store.cancel_job(job.job_id, "owner-b")
        cancelled = store.cancel_job(job.job_id, "owner-a")
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)

    def test_cancel_missing_job(self):
        store = InMemoryJobStore()
        with self.assertRaises(JobNotFound):
            store.cancel_job("missing", "owner")


if __name__ == "__main__":
    unittest.main()
