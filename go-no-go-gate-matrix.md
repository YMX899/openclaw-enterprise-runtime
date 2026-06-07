# OpenClaw x Dify Go/No-Go Gate Matrix

Generated: 2026-06-06  
Last refreshed: 2026-06-07 Asia/Shanghai

## Current Decision

```text
Phase 0 read-only audit: PASS
Phase 1 offline source preparation: PASS for current sidecar scope
Phase 1.5 isolated Linux Docker validation: PASS
Phase 2 private sidecar deployment: PASS for guarded sidecar scope
Phase 3/4 OpenClaw Lab public route and standalone login: PASS for current scope
Root-server deployment/testing: GO under relaxed development gates
Full final release sign-off: IN_PROGRESS until fresh root evidence is recorded
Dify Web / Dify compose modification: NO-GO
OpenClaw 2026.3.13 production security: PASS by approved exception for private Gateway scope
Web GPT review before execution: NOT_REQUIRED
Douyin login / REAL_SAMPLE_EVIDENCE gate: RETIRED
```
This file was originally created as a strict pre-deployment No-Go matrix. The
current execution baseline is intentionally more pragmatic:

```text
Proceed directly with root-server OpenClaw sidecar deployment/testing.
Do not block on Dify Web login, Douyin account login, web GPT review, or
REAL_SAMPLE_EVIDENCE.json.
Keep Dify containers untouched and preserve rollback.
```

The detailed current execution baseline is recorded in:

```text
openclaw-engineering-baseline.md
development-pragmatic-gates-20260607.md
```

## Historical Evidence

```text
Earlier GPT/web reviews are preserved as historical context only.
They no longer gate normal implementation or root-server testing.

Git rollback anchors include:
  phase1-5-executable-gates
  phase1-5-douyin-candidate-adapter
  phase1-5-douyin-minimal-source
  phase1-5-docker-gates-loader-smoke
  phase0-server-readonly-refresh-20260606
  phase0-real-chrome-dify-baseline-20260606
  go-no-go-gate-matrix-20260606
  openclaw-3-13-security-no-go-20260606
  phase1-5-security-approval-gate-20260606
  douyin-real-sample-runner-20260606
  production-readiness-audit-20260606
  chatgpt-production-readiness-no-go-20260606

Server read-only audit recorded Dify 1.11.2 running on AI-01 and an existing
0.0.0.0:5001 Dify API listener. Do not add more public listeners.
```

## Current Passed Items

```text
OpenClaw standalone login browser acceptance: PASS.
OpenClaw user page: https://www.huahuoai.com/ai/openclaw-lab/.
OpenClaw also remains available through the deployed Lab route.
Unauthenticated OpenClaw API returns 401.
Bridge is exposed through OpenResty/127.0.0.1 backend routing only.
OpenClaw Gateway and Bridge Postgres are not publicly exposed.
Post-Login Acceptance is deployed.
Public Playwright smoke passed with no new 5xx, no Gateway direct request, and
no token URL leak.
Dify api/web/nginx container IDs and StartedAt timestamps remained unchanged
during prior sidecar updates.
Video link-read mode is adopted.
REAL_SAMPLE_EVIDENCE.json is optional diagnostic history, not a blocker.
```

## Retired No-Go Items

```text
Dify Web login for OpenClaw: retired; use OpenClaw standalone login.
Douyin account login/Cookie/storage state: retired; use video link-read mode.
REAL_SAMPLE_EVIDENCE.json: retired as a blocker; optional diagnostic only.
Mandatory web GPT review before execution: retired; optional only by request.
```

## Current Root-Test Requirements

```text
1. Deploy/test OpenClaw directly on root with rollback preserved.
2. Confirm OpenClaw login page at https://www.huahuoai.com/ai/openclaw-lab/.
3. Confirm standalone OpenClaw login and post-login acceptance.
4. Confirm unauthenticated OpenClaw API returns 401.
5. Confirm video link-read negative URL/security tests.
6. Confirm Dify core containers were not restarted/recreated.
7. Confirm public Dify routes still respond and no new checked 5xx appears.
8. Commit/push the checkpoint and record sanitized evidence.
```

## Still Prohibited

```text
docker compose down/restart/rebuild of Dify containers
docker restart of Dify containers
editing Dify compose
editing Dify Web image/runtime files
reading or logging cookies, tokens, CSRF values, .env, full env, DB strings,
Redis passwords, TLS private keys or model API keys
exposing OpenClaw Gateway, Bridge Postgres, Docker socket, or model keys to the browser/public network
claiming final release completion before fresh root deployment/browser evidence passes
```

## Next Best Action

```text
1. Commit the relaxed-gate/documentation update.
2. Build, upload and deploy the current OpenClaw sidecar bundle on root.
3. Test https://www.huahuoai.com/ai/openclaw-lab/ directly with the OpenClaw
   standalone login UI.
4. Run post-login acceptance, security negative checks and public smoke.
5. Record sanitized root evidence, then commit/push the checkpoint.
```
