# OpenClaw 2026.3.13 Security Decision

Status: approved exception for Phase 1.5 isolated validation and controlled
sidecar trials only. This is not a blanket approval to expose OpenClaw Gateway
publicly or to bypass the remaining production readiness gates.

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
allowed_scope: Phase 1.5 isolated Ubuntu 22.04 Docker validation and later private sidecar testing only
gateway_exposure: private network only
browser_exposure: Gateway token never sent to browser
bridge_scopes: operator.read, operator.write
operator_admin: forbidden
dify_modification: forbidden before independent acceptance passes
```

The pinned package still has known `npm audit --omit=dev --json` findings. The
exception relies on compensating controls documented in `SECURITY_TRIAGE.md`:
private Gateway network, no public Gateway port, no Docker socket, no browser
token exposure, Bridge ACL before Gateway calls, and no operator admin scope.

## Remaining Production Conditions

Before root deployment, the following gates must still pass:

```text
Phase 1.5 isolated Docker proof
authenticated Dify public baseline
OpenResty rollback route plan
private Gateway exposure check
Bridge/browser token leak checks
douyin_chong artifact validation or explicit current-phase deferral
```

This exception does not authorize exposing Gateway, Postgres, Docker Socket, or
worker internals to the public internet.
