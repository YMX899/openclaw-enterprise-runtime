#!/usr/bin/env python
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import platform
import re
import shutil
import subprocess
import sys
from typing import Callable


CommandRunner = Callable[[list[str]], tuple[int, str, str]]


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    status: str
    evidence: str


def _run(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _parse_bytes(text: str) -> int | None:
    match = re.match(r"^\s*(\d+)\s*$", text)
    if not match:
        return None
    return int(match.group(1))


def check_os() -> CheckResult:
    system = platform.system()
    machine = platform.machine()
    if system != "Linux":
        return CheckResult("host_os", "NO_GO", f"expected Linux, got {system} {machine}")
    if machine not in {"x86_64", "amd64"}:
        return CheckResult("host_os", "NO_GO", f"expected x86_64 Linux, got {machine}")
    return CheckResult("host_os", "PASS", f"{system} {machine}")


def check_command(name: str, command: list[str], runner: CommandRunner = _run) -> CheckResult:
    if shutil.which(command[0]) is None:
        return CheckResult(name, "NO_GO", f"{command[0]} is not in PATH")
    code, stdout, stderr = runner(command)
    if code != 0:
        return CheckResult(name, "NO_GO", stderr or stdout or f"{command[0]} exited {code}")
    return CheckResult(name, "PASS", stdout.splitlines()[0] if stdout else f"{command[0]} OK")


def _command_exists(command: list[str]) -> bool:
    return bool(command) and shutil.which(command[0]) is not None


def _run_no_throw(command: list[str], runner: CommandRunner) -> tuple[int, str, str]:
    try:
        return runner(command)
    except subprocess.TimeoutExpired:
        return 124, "", "command timed out"


def check_docker(docker_cmd: list[str] | None = None, runner: CommandRunner = _run) -> CheckResult:
    docker_cmd = docker_cmd or ["docker"]
    if not _command_exists(docker_cmd):
        return CheckResult("docker_engine", "NO_GO", f"{docker_cmd[0]} is not in PATH")
    code, stdout, stderr = _run_no_throw(
        [*docker_cmd, "version", "--format", "Docker server={{.Server.Version}}"],
        runner,
    )
    if code != 0:
        return CheckResult("docker_engine", "NO_GO", stderr or stdout or "docker server unavailable")
    if "{{.Server.Version}}" in stdout or stdout.endswith("server="):
        return CheckResult("docker_engine", "NO_GO", "docker format output was not evaluated")
    return CheckResult("docker_engine", "PASS", stdout)


def check_compose(docker_cmd: list[str] | None = None, runner: CommandRunner = _run) -> CheckResult:
    docker_cmd = docker_cmd or ["docker"]
    if not _command_exists(docker_cmd):
        return CheckResult("docker_compose", "NO_GO", f"{docker_cmd[0]} is not in PATH")
    code, stdout, stderr = _run_no_throw([*docker_cmd, "compose", "version"], runner)
    if code != 0:
        return CheckResult("docker_compose", "NO_GO", stderr or stdout or "docker compose unavailable")
    return CheckResult("docker_compose", "PASS", stdout)


def check_disk(min_free_gb: int, runner: CommandRunner = _run) -> CheckResult:
    code, stdout, stderr = runner(["python3", "-c", "import shutil; print(shutil.disk_usage('.').free)"])
    if code != 0:
        return CheckResult("disk_free", "NO_GO", stderr or stdout or "disk check failed")
    free_bytes = _parse_bytes(stdout)
    if free_bytes is None:
        return CheckResult("disk_free", "NO_GO", f"could not parse free bytes: {stdout!r}")
    free_gb = free_bytes / (1024**3)
    if free_gb < min_free_gb:
        return CheckResult("disk_free", "NO_GO", f"{free_gb:.1f}GiB free, need {min_free_gb}GiB")
    return CheckResult("disk_free", "PASS", f"{free_gb:.1f}GiB free")


def check_memory(min_memory_gb: int, runner: CommandRunner = _run) -> CheckResult:
    code, stdout, stderr = runner(
        ["python3", "-c", "import os; print(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'))"]
    )
    if code != 0:
        return CheckResult("memory_total", "NO_GO", stderr or stdout or "memory check failed")
    total_bytes = _parse_bytes(stdout)
    if total_bytes is None:
        return CheckResult("memory_total", "NO_GO", f"could not parse total bytes: {stdout!r}")
    total_gb = total_bytes / (1024**3)
    if total_gb < min_memory_gb:
        return CheckResult("memory_total", "NO_GO", f"{total_gb:.1f}GiB total, need {min_memory_gb}GiB")
    return CheckResult("memory_total", "PASS", f"{total_gb:.1f}GiB total")


def readiness_report(min_free_gb: int, min_memory_gb: int, docker_cmd: list[str] | None = None) -> dict:
    checks = [
        check_os(),
        check_command("python3", ["python3", "--version"]),
        check_command("node", ["node", "--version"]),
        check_docker(docker_cmd),
        check_compose(docker_cmd),
        check_disk(min_free_gb),
        check_memory(min_memory_gb),
    ]
    overall = "PASS" if all(check.status == "PASS" for check in checks) else "NO_GO"
    return {
        "schema_version": "phase1.5-host-readiness.v1",
        "target": "isolated_linux_docker_host",
        "overall": overall,
        "checks": [asdict(check) for check in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Phase 1.5 isolated host readiness check.")
    parser.add_argument("--min-free-gb", type=int, default=20)
    parser.add_argument("--min-memory-gb", type=int, default=8)
    parser.add_argument(
        "--docker-cmd",
        nargs="+",
        default=["docker"],
        help="Docker command prefix, for example: docker or sudo -n docker",
    )
    parser.add_argument(
        "--use-sudo-docker",
        action="store_true",
        help="Use the non-interactive sudo Docker prefix: sudo -n docker",
    )
    parser.add_argument("--fail-on-no-go", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    docker_cmd = ["sudo", "-n", "docker"] if args.use_sudo_docker else args.docker_cmd
    report = readiness_report(args.min_free_gb, args.min_memory_gb, docker_cmd)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_no_go and report["overall"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
