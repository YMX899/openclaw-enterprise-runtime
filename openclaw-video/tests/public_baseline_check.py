from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


PATHS = (
    "/signin",
    "/apps",
    "/console/api/account/profile",
)


def check_url(base_url: str, path: str, timeout: int) -> dict:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "openclaw-video-baseline/0.1",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2048)
            return {
                "path": path,
                "url": url,
                "status": response.status,
                "final_url": response.geturl(),
                "elapsed_ms": round((time.time() - started) * 1000),
                "body_prefix_len": len(body),
            }
    except urllib.error.HTTPError as exc:
        exc.read(2048)
        return {
            "path": path,
            "url": url,
            "status": exc.code,
            "final_url": exc.geturl(),
            "elapsed_ms": round((time.time() - started) * 1000),
            "http_error": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    results = [check_url(args.base_url, path, args.timeout) for path in PATHS]
    report = {
        "schema": "openclaw-video-public-baseline.v1",
        "base_url": args.base_url,
        "checks": results,
        "secrets_recorded": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    statuses = {item["path"]: item["status"] for item in results}
    if statuses.get("/signin") != 200:
        return 1
    if statuses.get("/console/api/account/profile") != 401:
        return 1
    if statuses.get("/apps") not in {200, 302, 303, 307, 308}:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

