import json
import unittest
from pathlib import Path

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
        return {"x-test-account": account, "x-test-tenant": tenant}

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

        messages_response = self.client.get(
            f"/openclaw-api/sessions/{session['id']}/messages",
            headers=self.auth(),
        )
        self.assertEqual(messages_response.status_code, 200, messages_response.text)
        validate_schema(messages_response.json(), "message-list-response.schema.json")

        unauthenticated = self.client.get("/openclaw-api/me")
        self.assertEqual(unauthenticated.status_code, 401)
        validate_schema(unauthenticated.json(), "error-response.schema.json")

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
