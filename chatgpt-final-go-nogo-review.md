# ChatGPT Final Go/No-Go Review Capture

Date: 2026-06-06 Asia/Shanghai

Source: new Chrome ChatGPT conversation titled `OpenClaw 部署审查`.

Mode: user-provided ChatGPT web session. Captured only rendered page text. No
cookies, request headers, tokens, browser storage, or secrets were read or
recorded.

Update on 2026-06-06: a second ChatGPT web review was completed after the web
session recovered. It used GPT-5.5 Thinking mode and reviewed the repository
state after commit `ae72206` / tag `phase1-openclaw-gateway-ws-v3`.

Update on 2026-06-06: a third execution preflight review was completed in the
same ChatGPT web conversation after commit `c4fd167` / tag
`phase1-5-executable-gates`. It confirmed that the executable Phase 1.5 gates
are a valid isolated validation entry point, but production server Phase 2
remains `NO-GO` until the real video-analysis artifact, isolated Linux Docker
run, Dify authenticated baseline and OpenClaw `2026.3.13` security decision are
all closed. The detailed capture is in
`chatgpt-execution-preflight-review-20260606.md`.

## Final Verdict

```text
Production deployment: NO-GO
Server sidecar deployment: NO-GO
OpenResty public route change: NO-GO
Dify Web / Dify compose modification: NO-GO
Server Phase 0 read-only evidence collection: GO
Local Phase 1 offline engineering: CONDITIONAL GO
Phase 1.5 isolated Docker/Linux validation: GO
```

The review explicitly rejects any current claim that the project is "100%
deployable without affecting Dify". That claim can only become a proven
statement after all gates below pass with current-state evidence.

## Allowed Now

- Continue local Phase 1 implementation:
  - Postgres adapter and durable queue.
  - migration up/down tests.
  - worker lease / timeout / recovery tests.
  - Docker build and compose render.
  - OpenClaw Gateway mock contract tests.
  - Dify profile/workspace adapter tests.
  - SSRF, CSRF and log redaction tests.
  - SBOM and dependency vulnerability triage.
- Continue Phase 0 server read-only checks and real Dify public baseline tests.

## Forbidden Now

- Install OpenClaw on the Dify server.
- Deploy sidecar containers to the Dify server.
- Modify or reload OpenResty.
- Modify Dify Web or Dify compose.
- Restart, recreate, or rebuild Dify containers.
- Expose `/openclaw-lab/`, `/openclaw-api/`, OpenClaw Gateway, or Bridge
  Postgres publicly.

## Current Blockers

- No real `douyin_chong` artifact has been supplied.
- OpenClaw `2026.3.13` Gateway WS v3 contract is locally locked, but not yet
  proven inside the deployment compose with production model credentials.
- OpenClaw `2026.3.13` has public Gateway regression reports that must be
  specifically excluded in a fixed-version environment.
- `npm audit` reports a critical vulnerability affecting the fixed OpenClaw
  package path; production use requires triage or a signed exception.
- Docker build and compose render are not verified in an isolated Docker host.
- Authenticated public Dify application baseline is incomplete.
- OpenResty rollback is documented but not rehearsed.

## OpenClaw 2026.3.13 Regression Gate

The review called out public OpenClaw `2026.3.13 (61d171a)` Gateway regressions.
I cross-checked the claim with public sources before treating it as a gate:

- GitHub issue `openclaw/openclaw#46117`: `openclaw status` and
  `openclaw gateway probe` can report missing `operator.read` despite a paired
  CLI token showing that scope.
- GitHub issue `openclaw/openclaw#48008`: Gateway token mismatch, stale port
  conflict, and entrypoint drift after upgrading to `2026.3.13`.
- Official OpenClaw operator-scope documentation states calls requiring
  `operator.read`, `operator.write`, `operator.approvals`, `operator.pairing`
  or `operator.talk.secrets` must hold the corresponding scope or
  `operator.admin`.
- Official OpenClaw Gateway CLI documentation lists `openclaw gateway probe`,
  including JSON mode, as an expected Gateway diagnostic command.

These reports do not prove every installation fails, but they are enough to
make fixed-version Gateway contract tests mandatory before production.

## Required Phase Gates

### Phase 0

- Git worktree clean and current commit recorded.
- Dify compose hash recorded.
- Dify container IDs, image IDs, restart counts, created/started times and
  network bindings recorded.
- OpenResty config path, config hash, syntax-check command and reload/rollback
  method recorded without exposing secrets.
- Public unauthenticated Dify baseline recorded.
- Public authenticated Dify login, existing app page and message flow recorded.
- Server search confirms no existing OpenClaw or `douyin_chong` artifact.
- No server modifications occur.

### Phase 1

- Replace in-memory stores with production-ready Bridge Postgres adapters.
- Implement durable job queue with worker lease, timeout recovery, idempotency,
  ACL checks, cancellation and `worker_concurrency=1` enforcement.
- Add migration up/down tests.
- Freeze browser-facing API and job status contracts.
- Add CSRF/origin checks and sensitive-header log tests.
- Render Docker compose and build images in an isolated Docker environment.
- Generate SBOM and dependency-scan evidence.
- Triage OpenClaw npm audit findings.
- Keep all artifacts in git and tag the phase exit.

### Phase 1.5

- Use `phase1.5-isolated-docker-gates.md` as the controlling gate before any
  production server sidecar deployment.
- Supply and test the real `douyin_chong` or equivalent video-analysis
  artifact.
- Run Docker build, compose render, container startup, port exposure checks,
  Gateway WS v3 contract tests and worker resource tests on an isolated
  Linux Docker host.
- Close the OpenClaw `2026.3.13` security decision.
- Keep the production Dify server untouched except for read-only baselines.

### Phase 2

- Validate fixed OpenClaw `2026.3.13 (61d171a)` in disposable Ubuntu 24.04, not
  on the Dify server.
- Record tarball or image digest, Node version, lockfile and install command.
- Run `openclaw --version`, `openclaw doctor`, `openclaw gateway status`,
  `openclaw gateway probe`, `openclaw status` and `openclaw devices list`.
- Explicitly exclude token mismatch, missing `operator.read`, stale port,
  entrypoint drift and probe/ACP failure regressions.
- Validate real `douyin_chong` artifact, input/output schema, resources,
  timeout, cleanup and failure behavior.
- Destroy disposable environment after validation.

### Phase 3

- Deploy sidecar only as a private shadow service after Phase 2 passes.
- Bind Bridge only to `127.0.0.1`; do not add public routes.
- Keep Gateway and Bridge Postgres private.
- Prove Dify container IDs and restart counts are unchanged.
- Exercise sidecar rollback without Dify restart.

### Phase 4

- Add only `/openclaw-lab/` and `/openclaw-api/` via independent OpenResty
  include after Phase 3 passes.
- Syntax-check and reload OpenResty using the previously verified commands.
- Run public unauthenticated and authenticated Dify regressions.
- Exercise route rollback without Dify restart.

### Phase 5

- Enable only allowlisted users.
- Validate login reuse, tenant isolation, user isolation, async job recovery,
  worker failure behavior and absence of Gateway tokens in browser network
  traffic.
- Run Dify existing app flow during video-analysis load.

### Phase 6

- Require clean git state, production tag, fixed image digests, fixed OpenClaw
  and video-tool artifact hashes, SBOM, vulnerability decision, monitoring,
  backup, rollback runbook and evidence report.

## Immediate Next Safe Actions

1. Keep server work to Phase 0 read-only checks and authenticated Dify baseline.
2. Continue only with Phase 1.5 preparation:
   - real video-analysis artifact and wrapper verification.
   - isolated Docker/Linux build and compose validation.
   - OpenClaw security decision.
   - authenticated Dify baseline evidence.
3. Do not deploy sidecar services on the production Dify server until the
   Phase 1.5 exit commit and tag exist.
