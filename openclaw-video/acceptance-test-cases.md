# Acceptance Test Cases

## Phase 2 Local Sidecar

- `openclaw-bridge` health returns 200 on `127.0.0.1:18181/health`.
- `openclaw-bridge` reaches `api:5001` from `docker_default`.
- `openclaw-bridge` reaches `bridge-postgres` on private network.
- `openclaw-bridge` reaches OpenClaw Gateway on private network.
- OpenClaw Gateway is not bound to a public host port.
- Bridge Postgres is not bound to a public host port.
- Knowledge base is mounted at `/knowledge/short-video:ro`.
- Knowledge base `VERSION` and `SHA256SUMS` verify before sidecar startup.
- Worker claims one queued job and no more than one at a time.
- Worker timeout moves job to `timed_out`.
- Worker failure returns a user-safe error without internal stack traces.
- `/openclaw-api/jobs/{job_id}/events` streams only the current user's job
  snapshot and terminal `done` event.
- Dify containers are not recreated.

## Phase 3 Public Route

- Public `/signin` remains available.
- Public `/apps` remains available.
- Existing Dify app message flow works while video job runs.
- `/openclaw-lab/` loads from same public origin.
- Unauthenticated `/openclaw-api/me` returns 401.
- Authenticated `/openclaw-api/me` returns only non-sensitive identity projection.
- SSE disconnection does not lose job state; polling `GET /openclaw-api/jobs/{job_id}`
  recovers the latest status.
- Browser network requests do not contain OpenClaw Gateway token.
- Public network cannot access OpenClaw Gateway.
- Public network cannot access Bridge Postgres.

## User Isolation

- User A creates session A1.
- User B cannot read A1.
- User B guessing A job/session IDs gets 404 or 403.
- User A sessions A1 and A2 do not mix messages.
- Tenant switch changes principal scope or fails closed.

## Video Job Safety

- Valid Douyin URL returns 202 and job ID.
- Invalid domain is rejected.
- Localhost URL is rejected.
- Private IP URL is rejected.
- Cloud metadata IP is rejected.
- Redirect target is revalidated before download.
- Redirect chains that loop or exceed the configured hop limit are rejected.
- Redirects to non-allowlisted hosts or private/metadata IP space are rejected.
- Worker analyzes the final canonical URL after redirect validation.
- Worker invokes the video tool through fixed arguments for max download bytes,
  max video duration and max frame count.
- Result matches `schemas/video-analysis-result.schema.json`.
- Temporary files are cleaned.

## Knowledge Base

- `artifacts/knowledge-base-short-video/2026.06.06/SHA256SUMS` verifies.
- Runtime services cannot write into `/knowledge/short-video`.
- Knowledge base version is visible to operators before controlled trial.
- User memory, sessions, jobs and video results are not written to the
  knowledge-base artifact.
