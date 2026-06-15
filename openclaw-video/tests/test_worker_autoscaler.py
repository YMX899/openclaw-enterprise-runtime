import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from openclaw_video_worker_autoscaler import AutoscaleConfig, desired_worker_count


class WorkerAutoscalerTests(unittest.TestCase):
    def test_desired_worker_count_keeps_three_minimum_and_two_idle(self):
        cfg = AutoscaleConfig(min_workers=3, max_workers=30, target_idle_workers=2)
        self.assertEqual(desired_worker_count(queued=0, running=0, cfg=cfg), 3)
        self.assertEqual(desired_worker_count(queued=0, running=1, cfg=cfg), 3)
        self.assertEqual(desired_worker_count(queued=0, running=2, cfg=cfg), 4)
        self.assertEqual(desired_worker_count(queued=3, running=5, cfg=cfg), 10)

    def test_desired_worker_count_caps_at_maximum(self):
        cfg = AutoscaleConfig(min_workers=3, max_workers=30, target_idle_workers=2)
        self.assertEqual(desired_worker_count(queued=100, running=10, cfg=cfg), 30)


if __name__ == "__main__":
    unittest.main()
