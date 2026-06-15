#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - host dependency check
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


WORKER_RE = re.compile(r"^(?P<prefix>.*video-analysis-worker-)(?P<number>\d+)$")


@dataclass(frozen=True)
class AutoscaleConfig:
    min_workers: int = 3
    max_workers: int = 30
    target_idle_workers: int = 2
    seen_within_seconds: int = 180
    scale_down_grace_seconds: int = 120
    compose_project: str = "openclaw-video"
    compose_file: str = "docker-compose.openclaw-video.yaml"
    env_file: str = "/app/bin/openclaw-video/shared/openclaw-video.env"
    workdir: str = "/app/bin/openclaw-video/current/openclaw-video"
    service: str = "video-analysis-worker"


def desired_worker_count(queued: int, running: int, cfg: AutoscaleConfig) -> int:
    desired = queued + running + cfg.target_idle_workers
    return max(cfg.min_workers, min(cfg.max_workers, desired))


def current_compose_worker_count() -> int:
    return len(compose_workers())


def compose_workers() -> list[dict[str, Any]]:
    cmd = ["docker", "ps", "--format", "{{.Names}}"]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    containers = []
    for line in result.stdout.splitlines():
        name = line.strip()
        match = WORKER_RE.match(name)
        if not match:
            continue
        inspect = subprocess.run(
            ["docker", "inspect", name, "--format", "{{.Config.Hostname}}"],
            check=True,
            capture_output=True,
            text=True,
        )
        containers.append(
            {
                "name": name,
                "number": int(match.group("number")),
                "worker_id": inspect.stdout.strip() or name,
            }
        )
    return sorted(containers, key=lambda item: int(item["number"]))


class WorkerAutoscaler:
    def __init__(self, database_url: str, cfg: AutoscaleConfig, *, dry_run: bool = False) -> None:
        if psycopg is None or dict_row is None:
            raise RuntimeError("psycopg[binary] is required for worker autoscaler")
        self.database_url = database_url
        self.cfg = cfg
        self.dry_run = dry_run

    def _connect(self) -> Any:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, count(*) AS count
                    FROM video_jobs
                    WHERE status IN ('queued', 'running')
                    GROUP BY status
                    """
                )
                job_counts = {row["status"]: int(row["count"]) for row in cur.fetchall()}
                cur.execute(
                    """
                    SELECT worker_id, state, current_job_id, last_seen_at, drain_requested_at
                    FROM video_worker_registry
                    WHERE last_seen_at >= now() - make_interval(secs => %s)
                      AND state <> 'stopped'
                    ORDER BY worker_id ASC
                    """,
                    (self.cfg.seen_within_seconds,),
                )
                workers = [dict(row) for row in cur.fetchall()]
        queued = int(job_counts.get("queued", 0))
        running = int(job_counts.get("running", 0))
        containers = compose_workers()
        return {
            "queued": queued,
            "running": running,
            "workers": workers,
            "containers": containers,
            "current": len(containers),
            "desired": desired_worker_count(queued, running, self.cfg),
        }

    def _request_drain(self, worker_id: str) -> None:
        if self.dry_run:
            print(f"dry-run: request drain {worker_id}")
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_worker_registry
                      (worker_id, state, last_seen_at, drain_requested_at, updated_at)
                    VALUES (%s, 'draining', now(), now(), now())
                    ON CONFLICT (worker_id) DO UPDATE
                    SET state = 'draining',
                        drain_requested_at = COALESCE(video_worker_registry.drain_requested_at, now()),
                        updated_at = now()
                    """,
                    (worker_id,),
                )

    def _scale(self, replicas: int) -> None:
        command = [
            "docker",
            "compose",
            "--env-file",
            self.cfg.env_file,
            "-p",
            self.cfg.compose_project,
            "-f",
            self.cfg.compose_file,
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--scale",
            f"{self.cfg.service}={replicas}",
            self.cfg.service,
        ]
        if self.dry_run:
            print("dry-run:", " ".join(command))
            return
        subprocess.run(command, check=True, cwd=self.cfg.workdir)

    def reconcile_once(self) -> dict[str, Any]:
        snap = self.snapshot()
        current = int(snap["current"])
        desired = int(snap["desired"])
        workers = list(snap["workers"])
        if desired > current:
            self._scale(desired)
            snap["action"] = f"scale_up:{current}->{desired}"
            return snap
        if desired >= current:
            snap["action"] = "stable"
            return snap

        keep = desired
        worker_by_id = {str(worker["worker_id"]): worker for worker in workers}
        candidates = [
            {**container, **worker_by_id.get(str(container["worker_id"]), {})}
            for container in sorted(snap["containers"], key=lambda item: int(item["number"]), reverse=True)
            if int(container["number"]) > keep
        ]
        busy = False
        now = time.time()
        for worker in candidates:
            worker_id = str(worker["worker_id"])
            state = str(worker.get("state") or "")
            current_job_id = worker.get("current_job_id")
            if state != "draining":
                self._request_drain(worker_id)
                busy = True
                continue
            if current_job_id:
                busy = True
                continue
            drain_requested_at = worker.get("drain_requested_at")
            if drain_requested_at is None:
                busy = True
                continue
            requested_ts = drain_requested_at.timestamp()
            if now - requested_ts < self.cfg.scale_down_grace_seconds:
                busy = True
                continue
        if busy:
            snap["action"] = f"draining_before_scale_down:{current}->{desired}"
            return snap
        self._scale(desired)
        snap["action"] = f"scale_down:{current}->{desired}"
        return snap


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autoscale openclaw-video analysis workers.")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--min-workers", type=int, default=int(os.environ.get("VIDEO_WORKER_MIN_REPLICAS", "3")))
    parser.add_argument("--max-workers", type=int, default=int(os.environ.get("VIDEO_WORKER_MAX_REPLICAS", "30")))
    parser.add_argument("--target-idle", type=int, default=int(os.environ.get("VIDEO_WORKER_TARGET_IDLE", "2")))
    parser.add_argument("--interval", type=int, default=int(os.environ.get("VIDEO_WORKER_AUTOSCALE_INTERVAL_SECONDS", "20")))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--compose-project", default=os.environ.get("OPENCLAW_VIDEO_COMPOSE_PROJECT", "openclaw-video"))
    parser.add_argument(
        "--compose-file",
        default=os.environ.get("OPENCLAW_VIDEO_COMPOSE_FILE", "docker-compose.openclaw-video.yaml"),
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("OPENCLAW_VIDEO_ENV_FILE", "/app/bin/openclaw-video/shared/openclaw-video.env"),
    )
    parser.add_argument(
        "--workdir",
        default=os.environ.get("OPENCLAW_VIDEO_WORKDIR", "/app/bin/openclaw-video/current/openclaw-video"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.database_url:
        print("DATABASE_URL or --database-url is required", file=sys.stderr)
        return 2
    cfg = AutoscaleConfig(
        min_workers=max(1, args.min_workers),
        max_workers=max(args.min_workers, args.max_workers),
        target_idle_workers=max(0, args.target_idle),
        compose_project=args.compose_project,
        compose_file=args.compose_file,
        env_file=args.env_file,
        workdir=str(Path(args.workdir)),
    )
    scaler = WorkerAutoscaler(args.database_url, cfg, dry_run=args.dry_run)
    while True:
        snap = scaler.reconcile_once()
        print(
            "queued={queued} running={running} current={current} desired={desired} action={action}".format(
                **snap
            ),
            flush=True,
        )
        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
