# OpenClaw x Dify Go/No-Go Gate Matrix

Generated: 2026-06-06  
Current commit: `1d0f1e3` / tag `douyin-real-sample-runner-20260606`

## Current Decision

```text
Phase 0 read-only audit: PASS for current unauthenticated/server baseline
Phase 1 offline source preparation: PARTIAL PASS
Phase 1.5 isolated Linux Docker validation: NOT PASSED
Phase 2 production sidecar deployment: NO-GO
OpenResty public route change: NO-GO
Dify Web / Dify compose modification: NO-GO
OpenClaw 2026.3.13 production security: NO-GO
```

## Evidence Passed

```text
GPT-5.5 Thinking review completed:
  chatgpt-execution-preflight-review-20260606.md
  verdict: production Phase 2 remains NO-GO

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

Server read-only audit:
  server-readonly-audit.md
  Dify 1.11.2 running on AI-01
  docker-web-1 unhealthy cause recorded as missing pg_isready
  0.0.0.0:5001 Dify API listener recorded as existing risk
  no OpenClaw route added

OpenResty redacted route map:
  openresty-route-map-redacted.md
  no OpenClaw route present
  future route must be isolated /openclaw-lab/ and /openclaw-api/

Real Chrome unauthenticated baseline:
  dify-public-baseline.md
  /apps redirects to /signin
  /signin visible and usable as login page
  no current authenticated Dify session in Chrome

Local source/test gates:
  openclaw-video tests: 94 tests pass
  vendored douyin_chong SOURCE_SHA256SUMS gate passes locally
  Phase 1.5 scripts pass only with Docker skipped
  sanitized real-sample runner exists:
    scripts/run_douyin_real_sample.py
  runner tests prove no secret file content, raw URL or raw stdout/stderr is
  recorded in the sanitized evidence summary

OpenClaw 2026.3.13 audit:
  artifacts/openclaw-2026.3.13/SECURITY_DECISION.md
  npm audit --omit=dev reports 7 vulnerability groups:
    critical=1, high=4, moderate=2
  direct package openclaw@2026.3.13 is affected
  current production decision: reject fixed version as currently pinned
```

## Hard No-Go Items

These are required before production Phase 2 can start:

```text
1. Non-production Linux Docker host must run scripts/verify_phase1_5_gates.sh
   without SKIP_DOCKER=1.

2. The same host should run RUN_COMPOSE_UP=1 to prove localhost Bridge health,
   private Gateway/Postgres surfaces and teardown cleanup.

3. Real model-backed single-video sample must run through
   openclaw-douyin-adapter using only an explicit runtime env file.

4. The real sample must produce openclaw-video-result.v1 JSON and pass schema
   validation. Use scripts/run_douyin_real_sample.py to create sanitized
   evidence without recording secrets.

5. Worker timeout, cleanup and resource profile evidence must be captured:
   CPU, memory, disk, duration, temp path and failure behavior.

6. OpenClaw 2026.3.13 security/audit decision must move from current
   reject/No-Go to approved vendor patch, approved exception, or approved
   upgrade strategy.

7. Authenticated real-browser Dify baseline must pass:
   /apps, existing app open, existing app message send, response, refresh,
   history/entry behavior and sign-out.

8. Existing host-level 0.0.0.0:5001 Dify API exposure must be recorded in the
   future risk review. Do not add more public listeners.
```

## Explicitly Prohibited Until No-Go Items Pass

```text
docker compose up on production Dify host for OpenClaw sidecar
docker compose down/restart/rebuild of Dify containers
docker restart of Dify containers
openresty -s reload / nginx -s reload
editing Dify compose
editing Dify Web image/runtime files
adding /openclaw-lab/ or /openclaw-api/ public routes
reading or logging cookies, tokens, CSRF values, .env, full env, DB strings,
Redis passwords, TLS private keys or model API keys
```

## Next Best Action

```text
Provide or configure a non-production Linux Docker host, then run:

  REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
  PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh

  REQUIRE_OPENCLAW_SECURITY_APPROVAL=1 \
  RUN_COMPOSE_UP=1 \
  PYTHON=/path/to/python scripts/verify_phase1_5_gates.sh

Bring back the evidence listed in phase1.5-isolated-host-handoff.md.
```
