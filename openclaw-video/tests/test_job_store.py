import unittest

from openclaw_video.job_state import JobStatus
from openclaw_video.job_store import InMemoryJobStore, JobOwnershipError


class JobStoreTests(unittest.TestCase):
    def test_claim_next_moves_queued_to_running_once(self):
        store = InMemoryJobStore()
        job = store.create_job("owner", "session", "https://v.douyin.com/abc")
        claimed = store.claim_next()
        self.assertEqual(claimed.job_id, job.job_id)
        self.assertEqual(claimed.status, JobStatus.RUNNING)
        self.assertEqual(claimed.attempt_count, 1)
        self.assertIsNone(store.claim_next())

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


if __name__ == "__main__":
    unittest.main()

