import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
import os

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover - exercised when optional deps are absent
    TestClient = None

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover - exercised when optional deps are absent
    Draft202012Validator = None
    FormatChecker = None
    Registry = None
    Resource = None

from openclaw_video.job_store import InMemoryJobStore
from openclaw_video.openclaw_gateway import GatewayChatResult
from openclaw_video.session_store import InMemorySessionStore


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas"


def _load_schemas():
    schemas = {}
    for path in sorted(SCHEMA_ROOT.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[schema["$id"]] = schema
    return schemas


SCHEMAS = _load_schemas()


def _schema_id(name):
    return f"https://huahuoai.local/schemas/openclaw-video/{name}"


def _registry():
    return Registry().with_resources(
        (_id, Resource.from_contents(schema)) for _id, schema in SCHEMAS.items()
    )


def validate_schema(instance, schema_name):
    schema = SCHEMAS[_schema_id(schema_name)]
    validator = Draft202012Validator(
        schema,
        registry=_registry(),
        format_checker=FormatChecker(),
    )
    validator.validate(instance)


def parse_sse_events(body):
    events = []
    for block in body.strip().split("\n\n"):
        if not block:
            continue
        event_name = None
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        if event_name and data_lines:
            events.append({"event": event_name, "data": json.loads("\n".join(data_lines))})
    return events


class FakeDifyClient:
    async def profile(self, headers):
        account_id = headers.get("x-test-account")
        if not account_id:
            raise PermissionError("login required")
        return {"id": account_id}

    async def workspaces(self, headers):
        tenant_id = headers.get("x-test-tenant", "tenant-a")
        return {"data": [{"id": tenant_id, "current": True}]}


class FakeGateway:
    async def chat(self, request):
        return GatewayChatResult(content=f"reply to {request.content}", raw={"content": request.content})


def video_link_read_check_fixture():
    return {
        "schema_version": "openclaw-video-link-read-check.v1",
        "status": "PASS",
        "checked_at": "2026-06-07T00:00:00+00:00",
        "input_url_sha256": "a" * 64,
        "canonical_url_sha256": "b" * 64,
        "source_url_sha256": None,
        "share_url_sha256": None,
        "canonical_host": "www.douyin.com",
        "redirect_hop_count": 1,
        "redirect_chain_hosts": ["v.douyin.com", "www.douyin.com"],
        "resolved_ip_count": 1,
        "resolver": "douyin_chong.UniversalVideoResolver",
        "video_id_present": True,
        "video_id_sha256": "c" * 64,
        "direct_video_candidate_count": 2,
        "direct_video_host": "v3-dy-o.zjcdn.com",
        "playwm_host": "v26-dy.ixigua.com",
        "content_type_present": True,
        "content_type": "video/mp4",
        "duration_seconds": 12.345,
        "size_bytes": 2_621_440,
        "video_url_source": "direct",
        "limits": {
            "max_duration_seconds": 300,
            "max_download_bytes": 512 * 1024 * 1024,
            "max_model_video_bytes": 50 * 1024 * 1024,
            "default_video_understanding_fps": 4.0,
            "min_video_understanding_fps": 0.2,
            "max_video_understanding_fps": 5.0,
            "duration_known": True,
            "size_known": True,
            "duration_ok": True,
            "download_size_ok": True,
            "model_size_ok": True,
            "size_ok": True,
            "video_understanding_fps": 4.0,
            "fps_adjusted": False,
            "eligible_for_model_analysis": True,
        },
        "elapsed_ms": 123,
        "raw_url_recorded": False,
        "direct_video_url_recorded": False,
        "cookies_recorded": False,
        "headers_recorded": False,
        "tokens_recorded": False,
        "model_invoked": False,
    }


@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class SchemaFileTests(unittest.TestCase):
    def test_all_schema_files_have_unique_ids_and_are_valid_draft_2020_12(self):
        paths = sorted(SCHEMA_ROOT.glob("*.schema.json"))
        self.assertGreaterEqual(len(paths), 10)
        ids = []
        for path in paths:
            schema = json.loads(path.read_text(encoding="utf-8"))
            ids.append(schema["$id"])
            Draft202012Validator.check_schema(schema)
        self.assertEqual(len(ids), len(set(ids)))


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class BridgeApiSchemaContractTests(unittest.TestCase):
    def setUp(self):
        from openclaw_video.bridge_app import create_app

        self.sessions = InMemorySessionStore()
        self.jobs = InMemoryJobStore()
        self.env_patch = mock.patch.dict(
            os.environ,
            {"BRIDGE_ENABLE_TEST_IDENTITY_HEADERS": "1", "BRIDGE_TEST_IDENTITY_SECRET": "test-mode-secret"},
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(
            create_app(
                dify=FakeDifyClient(),
                session_store=self.sessions,
                job_store=self.jobs,
                gateway=FakeGateway(),
                identity_secret="test-secret",
            )
        )

    def auth(self, account="account-a", tenant="tenant-a"):
        return {
            "x-openclaw-test-identity-secret": "test-mode-secret",
            "x-test-account": account,
            "x-test-tenant": tenant,
        }

    def create_session(self):
        payload = {"title": "Video analysis"}
        validate_schema(payload, "session-create-request.schema.json")
        response = self.client.post("/openclaw-api/sessions", json=payload, headers=self.auth())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        validate_schema(body, "session-create-response.schema.json")
        return body["session"]

    def test_me_session_message_job_and_error_responses_match_committed_schemas(self):
        me_response = self.client.get("/openclaw-api/me", headers=self.auth())
        self.assertEqual(me_response.status_code, 200, me_response.text)
        validate_schema(me_response.json(), "me-response.schema.json")
        self.assertNotIn("tenant_id", me_response.json())
        self.assertNotIn("account_id", me_response.json())

        diagnostics_response = self.client.get(
            "/openclaw-api/identity/diagnostics",
            headers={**self.auth(), "Cookie": "dify=secret"},
        )
        self.assertEqual(diagnostics_response.status_code, 200, diagnostics_response.text)
        validate_schema(diagnostics_response.json(), "identity-diagnostics-response.schema.json")
        self.assertNotIn("tenant-a", diagnostics_response.text)
        self.assertNotIn("account-a", diagnostics_response.text)
        self.assertNotIn("secret", diagnostics_response.text)

        fixture = video_link_read_check_fixture()
        raw_url = "https://v.douyin.com/abc"
        with mock.patch("openclaw_video.bridge_app.probe_video_link", return_value=fixture):
            read_check_response = self.client.post(
                "/openclaw-api/video-link/read-check",
                json={"video_url": raw_url},
                headers=self.auth(),
            )
        self.assertEqual(read_check_response.status_code, 200, read_check_response.text)
        validate_schema(read_check_response.json(), "video-link-read-check-response.schema.json")
        self.assertNotIn(raw_url, read_check_response.text)
        self.assertFalse(read_check_response.json()["model_invoked"])

        session = self.create_session()

        sessions_response = self.client.get("/openclaw-api/sessions", headers=self.auth())
        self.assertEqual(sessions_response.status_code, 200, sessions_response.text)
        validate_schema(sessions_response.json(), "session-list-response.schema.json")

        empty_messages = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth(),
        )
        self.assertEqual(empty_messages.status_code, 200, empty_messages.text)
        validate_schema(empty_messages.json(), "message-list-response.schema.json")

        job_payload = {
            "session_id": session["id"],
            "video_url": "https://v.douyin.com/abc",
            "content": "analyze this",
            "idempotency_key": "sample-job-1",
        }
        validate_schema(job_payload, "job-create-request.schema.json")
        job_response = self.client.post("/openclaw-api/jobs", json=job_payload, headers=self.auth())
        self.assertEqual(job_response.status_code, 202, job_response.text)
        validate_schema(job_response.json(), "job-response.schema.json")
        job_id = job_response.json()["job"]["job_id"]

        read_job_response = self.client.get(f"/openclaw-api/jobs/{job_id}", headers=self.auth())
        self.assertEqual(read_job_response.status_code, 200, read_job_response.text)
        validate_schema(read_job_response.json(), "job-response.schema.json")

        result_payload = {
            "schema_version": "openclaw-video-result.v1",
            "source": {
                "video_url_canonical": "https://v.douyin.com/abc",
                "platform": "douyin",
                "duration_seconds": 1,
            },
            "summary": "ok",
            "signals": {"hook": "ok"},
            "raw_tool_result": {"ok": True},
            "created_at": "2026-06-06T00:00:00Z",
        }
        validate_schema(result_payload, "video-analysis-result.schema.json")
        self.jobs.complete_job(job_id, result_payload, "openclaw-video-result.v1")
        result_response = self.client.get(f"/openclaw-api/jobs/{job_id}/result", headers=self.auth())
        self.assertEqual(result_response.status_code, 200, result_response.text)
        validate_schema(result_response.json(), "job-result-response.schema.json")

        messages_response = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth(),
        )
        self.assertEqual(messages_response.status_code, 200, messages_response.text)
        validate_schema(messages_response.json(), "message-list-response.schema.json")

        unauthenticated = self.client.get("/openclaw-api/me")
        self.assertEqual(unauthenticated.status_code, 401)
        validate_schema(unauthenticated.json(), "error-response.schema.json")

    def test_upload_job_response_and_upload_result_match_committed_schemas(self):
        session = self.create_session()
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"BRIDGE_UPLOAD_DIR": tmp}):
            upload_response = self.client.post(
                "/openclaw-api/uploads",
                data={"session_id": session["id"], "content": "upload"},
                files={"video": ("sample.mp4", b"video bytes", "video/mp4")},
                headers=self.auth(),
            )
        self.assertEqual(upload_response.status_code, 202, upload_response.text)
        validate_schema(upload_response.json(), "upload-job-response.schema.json")

        job_id = upload_response.json()["job"]["job_id"]
        upload_result = {
            "schema_version": "openclaw-video-result.v1",
            "source": {
                "video_url_canonical": upload_response.json()["job"]["video_url_canonical"],
                "platform": "upload",
                "duration_seconds": None,
            },
            "summary": "uploaded file validated",
            "signals": {"visual_notes": "uploaded_file=sample.mp4; size_bytes=11"},
            "raw_tool_result": {
                "tool": "openclaw-upload-file-analyzer",
                "mode": "file-level-validation",
                "filename": "sample.mp4",
                "size_bytes": 11,
            },
            "created_at": "2026-06-06T00:00:00Z",
        }
        validate_schema(upload_result, "video-analysis-result.schema.json")
        self.jobs.complete_job(job_id, upload_result, "openclaw-video-result.v1")
        result_response = self.client.get(f"/openclaw-api/jobs/{job_id}/result", headers=self.auth())
        self.assertEqual(result_response.status_code, 200, result_response.text)
        validate_schema(result_response.json(), "job-result-response.schema.json")

    def test_retention_cleanup_response_matches_committed_schema(self):
        from openclaw_video.bridge_app import create_app

        sessions = InMemorySessionStore()
        jobs = InMemoryJobStore()
        with mock.patch.dict(os.environ, {"OPENCLAW_DATA_RETENTION_DAYS": "1"}):
            client = TestClient(
                create_app(
                    dify=FakeDifyClient(),
                    session_store=sessions,
                    job_store=jobs,
                    gateway=FakeGateway(),
                    identity_secret="test-secret",
                )
            )
        session = client.post(
            "/openclaw-api/sessions",
            json={"title": "Video analysis"},
            headers=self.auth(),
        ).json()["session"]
        job_response = client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/old"},
            headers=self.auth(),
        )
        self.assertEqual(job_response.status_code, 202, job_response.text)
        job_id = job_response.json()["job"]["job_id"]
        jobs.fail_job(job_id, "old_failed")
        jobs.get_job(job_id).finished_at = datetime.now(UTC) - timedelta(days=2)

        cleanup_response = client.post("/openclaw-api/retention/cleanup", headers=self.auth())

        self.assertEqual(cleanup_response.status_code, 200, cleanup_response.text)
        validate_schema(cleanup_response.json(), "retention-cleanup-response.schema.json")

    def test_text_chat_response_matches_schema_and_video_chat_uses_job_response_schema(self):
        session = self.create_session()

        chat_payload = {"session_id": session["id"], "content": "hello"}
        validate_schema(chat_payload, "chat-request.schema.json")
        chat_response = self.client.post("/openclaw-api/chat", json=chat_payload, headers=self.auth())
        self.assertEqual(chat_response.status_code, 200, chat_response.text)
        validate_schema(chat_response.json(), "chat-response.schema.json")

        video_payload = {"session_id": session["id"], "video_url": "https://v.douyin.com/video"}
        validate_schema(video_payload, "chat-request.schema.json")
        video_response = self.client.post("/openclaw-api/chat", json=video_payload, headers=self.auth())
        self.assertEqual(video_response.status_code, 202, video_response.text)
        validate_schema(video_response.json(), "job-response.schema.json")

    def test_job_events_stream_matches_schema(self):
        session = self.create_session()
        job_response = self.client.post(
            "/openclaw-api/jobs",
            json={"session_id": session["id"], "video_url": "https://v.douyin.com/abc"},
            headers=self.auth(),
        )
        self.assertEqual(job_response.status_code, 202, job_response.text)
        job_id = job_response.json()["job"]["job_id"]
        self.jobs.complete_job(job_id, {"ok": True}, "openclaw-video-result.v1")

        with self.client.stream(
            "GET",
            f"/openclaw-api/jobs/{job_id}/events",
            headers=self.auth(),
        ) as stream:
            self.assertEqual(stream.status_code, 200)
            body = "".join(stream.iter_text())

        events = parse_sse_events(body)
        self.assertEqual([item["event"] for item in events], ["job", "done"])
        for event in events:
            validate_schema(event, "job-event.schema.json")


if __name__ == "__main__":
    unittest.main()
