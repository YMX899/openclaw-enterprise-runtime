# OpenClaw 2026.3.13 Security Decision

Status: approved exception for the current OpenClaw sidecar boundary. This is
not a blanket approval to expose OpenClaw Gateway publicly or to bypass the
current production readiness gates.

## Decision

```text
decision: approve_exception
decision_date: 2026-06-06
security_owner: user-approved operator exception
engineering_owner: Codex implementation gate with user authorization
```

## Scope

```text
openclaw_version: 2026.3.13
allowed_scope: OpenClaw sidecar behind Bridge on the Huahuo domain
gateway_exposure: private network only
browser_exposure: Gateway token never sent to browser
bridge_scopes: operator.read, operator.write
operator_admin: forbidden
dify_modification: forbidden without explicit maintenance approval
```

The pinned package still has known `npm audit --omit=dev --json` findings. The
exception relies on compensating controls documented in `SECURITY_TRIAGE.md`:
private Gateway network, no public Gateway port, no Docker socket, no browser
token exposure, Bridge ACL before Gateway calls, and no operator admin scope.

## Current Production Conditions

The exception remains valid only while these conditions hold:

```text
Gateway and Postgres have no public browser route
browser traffic reaches Bridge only
Gateway token and device key stay server-side
Bridge scopes stay operator.read, operator.write
operator.admin remains forbidden
Dify api/web/nginx containers are not restarted or rebuilt for OpenClaw work
OpenClaw-owned login evidence passes
video link-read mode and real-video analysis evidence pass
```

This exception does not authorize exposing Gateway, Postgres, Docker Socket, or
worker internals to the public internet.
