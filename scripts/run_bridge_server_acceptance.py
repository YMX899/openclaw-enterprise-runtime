#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any

import requests


@dataclass
class Check:
    name: str
    status: str
    evidence: str


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    response = requests.request(method, url, timeout=20, **kwargs)
    return response


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def run(base_url: str, account: str, tenant: str, poll_seconds: int, test_secret: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    checks: list[Check] = []

    def add(name: str, ok: bool, evidence: str) -> None:
        checks.append(Check(name, "PASS" if ok else "FAIL", evidence))

    if not test_secret:
        add("test_identity_secret_present", False, "missing --test-secret or BRIDGE_TEST_IDENTITY_SECRET")
        return {
            "schema": "openclaw-bridge-server-acceptance.v1",
            "base_url": base,
            "overall": "FAIL",
            "checks": [asdict(item) for item in checks],
        }

    headers = {
        "x-test-account": account,
        "x-test-tenant": tenant,
        "x-openclaw-test-identity-secret": test_secret,
    }
    other_headers = {
        "x-test-account": account + "-other",
        "x-test-tenant": tenant,
        "x-openclaw-test-identity-secret": test_secret,
    }
    add("test_identity_secret_present", True, "provided")

    unauth = _request("GET", f"{base}/openclaw-api/me")
    add("unauthenticated_me", unauth.status_code == 401, f"status={unauth.status_code}")

    diagnostics = _request("GET", f"{base}/openclaw-api/identity/diagnostics", headers=headers)
    diag_body = _json(diagnostics)
    add(
        "diagnostics_authenticated",
        diagnostics.status_code == 200
        and diag_body.get("authenticated") is True
        and diag_body.get("profile_ok") is True
        and diag_body.get("workspace_ok") is True
        and "tenant_id" not in diagnostics.text
        and "account_id" not in diagnostics.text,
        f"status={diagnostics.status_code} authenticated={diag_body.get('authenticated')}",
    )

    me = _request("GET", f"{base}/openclaw-api/me", headers=headers)
    me_body = _json(me)
    principal = me_body.get("principal_id")
    add(
        "me_authenticated",
        me.status_code == 200 and isinstance(principal, str) and len(principal) == 64,
        f"status={me.status_code} principal_len={len(principal) if isinstance(principal, str) else 0}",
    )

    session = _request(
        "POST",
        f"{base}/openclaw-api/sessions",
        headers=headers,
        json={"title": f"server acceptance {uuid.uuid4()}"},
    )
    session_body = _json(session)
    session_id = (session_body.get("session") or {}).get("id")
    add("create_session", session.status_code == 201 and bool(session_id), f"status={session.status_code}")

    if not session_id:
        return {
            "schema": "openclaw-bridge-server-acceptance.v1",
            "base_url": base,
            "overall": "FAIL",
            "checks": [asdict(item) for item in checks],
        }

    other_messages = _request(
        "GET",
        f"{base}/openclaw-api/sessions/{session_id}/messages",
        headers=other_headers,
    )
    add("cross_user_session_404", other_messages.status_code == 404, f"status={other_messages.status_code}")

    job = _request(
        "POST",
        f"{base}/openclaw-api/jobs",
        headers=headers,
        json={
            "session_id": session_id,
            "video_url": "https://example.com/not-douyin",
            "content": "Acceptance invalid URL should be rejected.",
            "idempotency_key": "acceptance-" + session_id,
        },
    )
    job_body = _json(job)
    job_id = (job_body.get("job") or {}).get("job_id")
    add("create_invalid_url_job", job.status_code == 202 and bool(job_id), f"status={job.status_code}")

    if job_id:
        other_job = _request("GET", f"{base}/openclaw-api/jobs/{job_id}", headers=other_headers)
        add("cross_user_job_404", other_job.status_code == 404, f"status={other_job.status_code}")

        deadline = time.monotonic() + poll_seconds
        final_status = None
        final_error = None
        while time.monotonic() < deadline:
            poll = _request("GET", f"{base}/openclaw-api/jobs/{job_id}", headers=headers)
            body = _json(poll).get("job") or {}
            final_status = body.get("status")
            final_error = body.get("error_code")
            if final_status in {"failed", "timed_out", "cancelled", "succeeded"}:
                break
            time.sleep(1)
        add(
            "invalid_url_job_rejected",
            final_status == "failed" and final_error == "url_rejected",
            f"status={final_status} error={final_error}",
        )

    messages = _request("GET", f"{base}/openclaw-api/sessions/{session_id}/messages", headers=headers)
    messages_body = _json(messages)
    count = len(messages_body.get("messages") or [])
    add("messages_visible_to_owner", messages.status_code == 200 and count >= 1, f"status={messages.status_code} count={count}")

    overall = "PASS" if all(item.status == "PASS" for item in checks) else "FAIL"
    return {"schema": "openclaw-bridge-server-acceptance.v1", "base_url": base, "overall": overall, "checks": [asdict(item) for item in checks]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run server-side Bridge acceptance using explicit test identity headers.")
    parser.add_argument("--base-url", default="http://127.0.0.1:18181")
    parser.add_argument("--account", default="acceptance-account")
    parser.add_argument("--tenant", default="acceptance-tenant")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--test-secret", default=os.environ.get("BRIDGE_TEST_IDENTITY_SECRET", ""))
    args = parser.parse_args(argv)

    result = run(args.base_url, args.account, args.tenant, args.poll_seconds, args.test_secret)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
