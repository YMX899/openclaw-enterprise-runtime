# OpenClaw x Dify Go/No-Go Gate Matrix

Generated: 2026-06-06  
Last refreshed: 2026-06-07 Asia/Shanghai
Current commit: `cdf815d` / tag `phase4-chrome-post-login-runner-20260607`

## Current Decision

```text
Phase 0 read-only audit: PASS
Phase 1 offline source preparation: PASS for current sidecar scope
Phase 1.5 isolated Linux Docker validation: PASS
Phase 2 private sidecar deployment: PASS for guarded sidecar scope
Phase 3 same-origin OpenClaw Lab route: PASS for guarded test route
Phase 4 authenticated browser acceptance: PENDING Huahuo user-web login
Full production completion: NO-GO
Dify Web / Dify compose modification: NO-GO
OpenClaw 2026.3.13 production security: PASS by approved exception for private Gateway scope
```

This file was originally created as a pre-deployment No-Go matrix. It has now
been refreshed to distinguish two different decisions:

```text
Current guarded sidecar route is deployed and rollback-controlled.
The full project objective is not complete until authenticated browser acceptance,
real/sample video evidence, and final regression gates pass.
```

## Historical Evidence

```text
GPT-5.5 Thinking review completed:
  chatgpt-execution-preflight-review-20260606.md
  verdict at that time: production Phase 2 remains NO-GO

Git rollback anchors:
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

Server read-only audit:
  server-readonly-audit.md
  Dify 1.11.2 running on AI-01
  docker-web-1 unhealthy cause recorded as missing pg_isready
  0.0.0.0:5001 Dify API listener recorded as existing risk
  no OpenClaw route added at that time

OpenResty redacted route map:
  openresty-route-map-redacted.md
  no OpenClaw route present at that time
  future route requirement was isolated /openclaw-lab/ and /openclaw-api/

Real Chrome unauthenticated baseline:
  dify-public-baseline.md
  /apps redirects to /signin
  /signin visible and usable as login page
  no current authenticated Dify session in Chrome

Local source/test gates:
  openclaw-video tests: 98 tests pass
  vendored douyin_chong SOURCE_SHA256SUMS gate passes locally
  Phase 1.5 scripts pass only with Docker skipped
  production readiness audit exists:
    scripts/audit_production_readiness.py
    current overall: NO_GO
    fail-on-no-go exits nonzero as intended
  sanitized real-sample runner exists:
    scripts/run_douyin_real_sample.py
  runner tests prove no secret file content, raw URL or raw stdout/stderr is
  recorded in the sanitized evidence summary
  production audit now requires sanitized REAL_SAMPLE_EVIDENCE.json; manifest
  text alone cannot make the douyin artifact gate sufficient for Phase 2

OpenClaw 2026.3.13 audit:
  artifacts/openclaw-2026.3.13/SECURITY_DECISION.md
  npm audit --omit=dev reports 7 vulnerability groups:
    critical=1, high=4, moderate=2
  direct package openclaw@2026.3.13 is affected
  original production decision: reject fixed version as currently pinned
```

These historical records are preserved for rollback context. Current Phase 4
status is governed by `phase4-same-origin-openclaw-lab-deployment-evidence-20260607.md`
and `scripts/audit_phase4_current_state.py`.

## Current Passed Items

```text
OpenClaw same-origin Lab is public at https://www.huahuoai.com/openclaw-lab/.
Unauthenticated https://www.huahuoai.com/openclaw-api/me returns 401.
OpenClaw Bridge is exposed only through 127.0.0.1:18181 behind OpenResty.
OpenClaw Gateway and Bridge Postgres are not publicly exposed.
Post-Login Acceptance button is deployed.
Chrome post-login runner exists and records sanitized visible-page evidence only.
Public Playwright smoke passes with no new 5xx, no Gateway direct request, and no token URL leak.
Dify api/web/nginx container IDs and StartedAt timestamps remained unchanged during sidecar updates.
Rollback to /app/bin/openclaw-video/releases/84e13d007d33 is documented.
Git tags are present for each deployed sidecar step.
```

## Remaining No-Go Items

These are required before production Phase 2 can start:

```text
1. Real model-backed single-video sample must run through
   openclaw-douyin-adapter using only an explicit runtime env file.

2. The real sample must produce openclaw-video-result.v1 JSON and pass schema
   validation. Use scripts/run_douyin_real_sample.py to create sanitized
   evidence without recording secrets.

3. Worker timeout, cleanup and resource profile evidence must be captured:
   CPU, memory, disk, duration, temp path and failure behavior.

4. Huahuo user-web login must be restored in Chrome and the deployed
   Post-Login Acceptance gate must return PASS.

5. Authenticated real-browser Huahuo/Dify regression must pass:
   user page opens chat, existing message send works, response is visible,
   page refresh behaves normally, and no new 5xx appears.

6. Existing host-level 0.0.0.0:5001 Dify API exposure must be recorded in the
   future risk review. Do not add more public listeners.
```

## Explicitly Prohibited Until No-Go Items Pass

```text
docker compose down/restart/rebuild of Dify containers
docker restart of Dify containers
editing Dify compose
editing Dify Web image/runtime files
reading or logging cookies, tokens, CSRF values, .env, full env, DB strings,
Redis passwords, TLS private keys or model API keys
exposing OpenClaw Gateway, Bridge Postgres, Docker socket, or model keys to the browser/public network
claiming full completion before Post-Login Acceptance and real sample evidence pass
```

## Next Best Action

```text
1. Restore Huahuo user-web login in Chrome at https://www.huahuoai.com/ai/?id=4.
2. Run the Chrome post-login runner:
   scripts/huahuo_post_login_acceptance_runner.mjs through the Chrome skill.
3. Record PASS/FAIL evidence without cookies, tokens, local storage values,
   request headers, or response bodies.
4. Run a real/sanitized douyin sample if final production readiness still
   requires it.
5. Re-run:
   python scripts/audit_phase4_current_state.py --smoke-summary <latest summary.json> --include-git-clean
```
