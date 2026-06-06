# Phase 1 Artifact Gates

Status: blocked until artifacts are supplied, built, and verified offline.

## OpenClaw Version Lock

Requested version: OpenClaw `3.13`.

Observed public package registry information:

```text
npm package: openclaw
stable matching version: 2026.3.13
tarball: https://registry.npmjs.org/openclaw/-/openclaw-2026.3.13.tgz
integrity: sha512-/juSUb070Xz8K8CnShjaZQr7CVtRaW4FbR93lgr1hLepcRSbyz2PQR+V4w5giVWkea61opXWPA6Vb8dybaztFg==
shasum: 559b4cc4a605616ada0d11a9ca29b7395af91e0e
binary: openclaw -> openclaw.mjs
```

Observed local offline sandbox verification:

```text
test directory: D:\DESK\Dify\.phase1-sandbox\openclaw-3.13
install command: npm install openclaw@2026.3.13 --ignore-scripts
version output: OpenClaw 2026.3.13 (61d171a)
CLI commands observed: gateway, doctor, config, setup, status, health, sessions, memory, agents, backup
gateway supports: --bind, --auth, --token, --port, call/status/probe/run
gateway call supports: health/status/system-presence/cron.* methods through the Gateway RPC helper
doctor supports: --non-interactive, --generate-gateway-token, --repair
doctor does not expose: --lint or --json in this fixed-version help output
config supports: file/get/set/unset/validate
```

Observed local Gateway WebSocket contract:

```text
temporary Gateway: ws://127.0.0.1:18190
version: OpenClaw 2026.3.13 (61d171a)
client id/mode: gateway-client / backend
protocol: WebSocket v3
chat methods: chat.history, chat.send
minimum Bridge scopes: operator.read, operator.write
admin scope: not required and not allowed for V1 Bridge
session key format: agent:main:<openclaw_routing_user>
wrong token: fails closed with AUTH_TOKEN_MISMATCH
unsigned backend client: connects but loses scopes; chat.history fails with missing operator.read
signed backend client: status and chat.history pass with read/write scopes
chat.send: ack/event shape verified; real model reply blocked locally by missing provider key
```

Required production implication:

- Bridge must hold a read-only Ed25519 device private key file for Gateway
  signing.
- Bridge must hold the Gateway token via a read-only file, not browser state.
- Bridge must not send Gateway token, device key, device id, public key or
  signatures to the browser.
- Gateway token must not be passed as a process command-line argument.
- `POST /channels/dify-web/chat` is rejected for V1.

Security gate from local `npm audit`:

```text
total vulnerabilities: 7
moderate: 2
high: 4
critical: 1
affected direct package: openclaw@2026.3.13
```

Important implication:

- OpenClaw `2026.3.13` is installable, but npm audit reports security advisories affecting this version and its dependencies.
- Production use of this fixed version requires an explicit security exception, a patched vendor build, or a user-approved version upgrade strategy.
- Without that security decision, the project remains No-Go for production even if Bridge and video worker are implemented.

This registry observation is not enough for production deployment. Phase 1 must still lock:

- exact install method: npm package, source checkout, or container image.
- exact version output from `openclaw --version`.
- exact result of `openclaw doctor`.
- exact Gateway API surface used by Bridge.
- exact Gateway bind address and port.
- exact state/config/data directories.
- exact token generation and storage method.
- image digest if a Docker image is used.
- rollback and backup behavior for all OpenClaw state.

Gateway safety gate:

- Gateway must not be exposed to public interfaces.
- Gateway token must never enter browser JavaScript or network requests.
- Control UI/default Gateway port such as `18789` must not be bound to `0.0.0.0`.

Gateway regression gate for fixed `2026.3.13 (61d171a)`:

- `openclaw gateway probe` must pass with the token and scopes that Bridge will
  use.
- `openclaw gateway call health` and `openclaw gateway call status` must pass
  against the exact isolated Gateway URL that Bridge will use.
- `openclaw status` must not report missing `operator.read`.
- stale Gateway processes must not occupy the intended port.
- Gateway entrypoint and service command must match the fixed package layout.
- wrong or rotated tokens must fail closed with no browser exposure.
- Bridge contract tests must prove the exact Gateway RPC/adapter path used by
  the sidecar. The placeholder HTTP path `/channels/dify-web/chat` is rejected
  for V1.
- `scripts/verify_openclaw_gateway_ws_contract.mjs` must pass in the isolated
  build environment and later against the server-side private Gateway before
  any public route is added.
- public reports of `2026.3.13` token mismatch, missing `operator.read`,
  port-conflict and probe/ACP failures must be explicitly excluded in an
  isolated environment before production.

## Missing Or Incomplete Artifacts

Current local and server checks did not find production-ready:

- `openclaw-bridge` image or complete production source.
- OpenClaw Gateway deployment assets for version `2026.3.13`.
- `douyin_chong` or equivalent video-analysis source/image/binary.
- real worker wrapper bound to the actual video-analysis artifact.
- final JSON result schema for the real video-analysis output.
- applied and tested Bridge database migrations on a real Postgres container.
- acceptance tests for real session ACL, job lifecycle, and authenticated Dify baseline.

Local draft artifacts now exist for Bridge identity, URL guarding, job state,
in-memory job claiming, Postgres durable queue adapter, worker lease/heartbeat
flow, worker status transitions, redirect target revalidation, fixed-argument
video resource-limit wrapper contract, Gateway token isolation, database
migration draft, rollback SQL, versioned read-only short-video knowledge-base
artifact, Bridge API JSON Schema request/response contracts, OpenClaw Gateway
WS v3 contract tests, rollback runbook and baseline test script. These are
offline implementation progress, not production deployment evidence.

Because of these missing artifacts:

```text
Phase 1 offline artifact preparation: CONDITIONAL GO for local implementation
Phase 1.5 isolated Docker/Linux validation: GO
Phase 2 sidecar deployment: NO-GO
Phase 3 public route: NO-GO
Phase 4 controlled trial: NO-GO
Phase 5 Dify entry integration: NO-GO
```

The project may continue implementing local Phase 1 artifacts, but Phase 1
cannot be considered complete until production adapters, Docker build, contract
tests, vulnerability triage and real artifact manifests are verified.

Current local Docker status: the workstation has no `docker` command available,
so Docker build, compose render and real Postgres migration integration remain
unverified. Adapter replay tests are useful local evidence, not a replacement
for container integration.

After the 2026-06-06 GPT-5.5 Thinking web review, `phase1.5-isolated-docker-gates.md`
is the controlling gate before any production server sidecar deployment. The
production Dify server must not be used as the first Docker build/compose/up
validation environment.

## Required Offline Deliverables

All deliverables must be stored in git before any server deployment:

- `openclaw-bridge` source code.
- `openclaw-bridge` Dockerfile and pinned image tag/digest.
- `openclaw-gateway` version lock for OpenClaw `2026.3.13`.
- `video-analysis-worker` source code.
- fixed-argument `douyin_chong` wrapper.
- `bridge-postgres` migration SQL.
- `docker-compose.openclaw-video.yaml`.
- `rollback-runbook.md`.
- `acceptance-test-cases.md`.
- versioned read-only knowledge-base artifact with `VERSION`, `SHA256SUMS`,
  manifest and verification scripts.
- JSON Schemas for:
  - `GET /openclaw-api/me` response.
  - session create request and session create/list responses.
  - session and message objects.
  - message-list response.
  - chat request/response.
  - job create request and job read/create responses.
  - job SSE event payloads.
  - error responses.
  - video job states.
  - video analysis result.
- SSRF and URL validation tests.
- ACL isolation tests.
- Dify public baseline test script.

## Minimum Knowledge-Base Contract

The knowledge base must:

- be stored as a versioned artifact under `artifacts/knowledge-base-short-video/<version>`.
- include `VERSION`, `MANIFEST.md` and `SHA256SUMS`.
- pass `scripts/verify_knowledge_base_artifact.ps1` on Windows and
  `scripts/verify_knowledge_base_artifact.sh` on Linux or an isolated Docker
  host.
- be mounted read-only at `/knowledge/short-video:ro`.
- not be used as per-user memory, session storage, job storage or result
  storage.
- create a new version directory and git commit for every content update.

## Minimum Bridge Contract

Browser-facing endpoints:

```text
GET  /openclaw-api/me
GET  /openclaw-api/sessions
POST /openclaw-api/sessions
GET  /openclaw-api/sessions/{session_id}/messages
POST /openclaw-api/chat
POST /openclaw-api/jobs
GET  /openclaw-api/jobs/{job_id}
GET  /openclaw-api/jobs/{job_id}/events
```

Required identity behavior:

- Browser sends existing Dify login state only to Bridge through same-origin requests.
- Bridge calls `http://api:5001/console/api/account/profile`.
- Bridge calls `http://api:5001/console/api/workspaces`.
- If zero or multiple current workspaces are returned, fail closed.
- Do not return full workspace list to browser.
- Do not log Cookie, Authorization, CSRF token, complete request headers, or model API keys.
- Do not forward Dify cookies to OpenClaw Gateway.

Required ID derivation:

```text
logical_user = "dify:" + tenant_id + ":" + account_id
principal_id = HMAC-SHA256(bridge_identity_secret, logical_user)
openclaw_routing_user = HMAC-SHA256(secret, principal_id + ":" + bridge_session_id)
```

Required OpenClaw Gateway behavior:

- Bridge uses `OPENCLAW_GATEWAY_URL=ws://openclaw-gateway:18789`.
- Bridge reads Gateway token from `OPENCLAW_GATEWAY_TOKEN_FILE`.
- Bridge reads an Ed25519 device private key from
  `OPENCLAW_GATEWAY_DEVICE_KEY_FILE`.
- Bridge sends `connect` with `client.id="gateway-client"`,
  `client.mode="backend"`, protocol v3, and scopes
  `operator.read,operator.write`.
- Bridge sends non-video chat to `chat.send` with
  `sessionKey="agent:main:<openclaw_routing_user>"`.
- Bridge treats OpenClaw internal agent failure text as a Gateway error, not as
  normal assistant content.

## Minimum Worker Contract

The worker must:

- use asynchronous jobs only.
- start with `worker_concurrency=1`.
- call `douyin_chong` only through a fixed-argument wrapper.
- reject non-allowlisted domains.
- validate redirects and final resolved IPs.
- reject redirect loops and excessive redirect chains.
- reject localhost, private networks, link-local ranges, cloud metadata IPs, and internal IPv6.
- enforce download size, video duration, frame count, timeout, temp directory, CPU, memory, and PID limits.
- run as non-root.
- avoid Docker socket mounts.
- avoid Dify RDS and Dify Redis access.
- clean temp files.
- return JSON matching the committed schema.

## Git and Rollback Gate

Before moving from Phase 1 to Phase 2:

- repository must be clean.
- every artifact must be committed.
- generated images/packages must have SHA256 or digest recorded.
- server deployment directory must be versioned independently or deployed from a versioned artifact.
- rollback commands must be tested in a non-production or no-op mode.
