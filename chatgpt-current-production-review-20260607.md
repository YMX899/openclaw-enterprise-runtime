# ChatGPT Current Production Review - 2026-06-07

## Context

- Review time: 2026-06-07 Asia/Shanghai.
- Review surface: logged-in ChatGPT web page controlled through Chrome.
- Target system: OpenClaw x Dify short-video analysis sidecar.
- Current deployed sidecar release: `84d0feff0862`.
- Current documentation HEAD before this note: `677da9713262`.
- Public OpenClaw entry: `https://ai001.huahuoai.com:18443/openclaw-lab/`.
- Dify entry remains on the original public service and is not modified by the OpenClaw sidecar.

The prompt asked ChatGPT to review the current deployment facts from a strict production-readiness and Go / No-Go perspective. The stated final goal was stable deployment on the existing root server without affecting the original Dify service.

## Go / No-Go

Current answer: **No-Go for unconditional production**.

The review explicitly rejected wording such as "100% will not affect Dify". Even after all gates pass, the recommended production wording is:

> The system has met the production release gates; within the executed functional, isolation, performance, security, recovery, and rollback test scope, no regression to existing Dify functionality was observed, and known residual risks have been formally accepted.

The current architecture direction remains acceptable because it keeps OpenClaw as a sidecar, avoids rebuilding Dify, exposes Gateway and Postgres only on private networks, and uses the independent `18443` public port. However, smoke tests and unit tests are not enough to call the system production-ready.

## Blocking Gaps

The remaining hard blockers are:

- Real logged-in Chrome regression for Dify is still incomplete: `/apps`, existing app page, message send, streaming or normal reply, refresh, history entry, and logout.
- Real logged-in Chrome OpenClaw Lab upload flow is still incomplete.
- Cross-user ACL, CSRF, session-expiry behavior, and cleanup endpoint authorization have not been fully proven through browser-level evidence.
- Resource hard limits are not yet fully evidenced for CPU, memory, PIDs, logs, disk pressure, upload size, duration, resolution, and task timeout.
- Fault recovery, backup restore, and one-command rollback have not yet been exercised end to end.
- Deployed sidecar release and documentation HEAD differ, so a formal release manifest is required.
- OpenClaw `2026.3.13` must be treated as a security exception unless upgraded or patched through a controlled maintenance branch with evidence.

## Minimum Next Loop

The next safe loop is:

1. Freeze a release manifest.
2. Complete real Chrome Dify regression without restarting or rebuilding Dify containers.
3. Complete real Chrome OpenClaw Lab upload, job polling, result display, refresh recovery, and error cases.
4. Verify Dify still works while OpenClaw performs a video job.
5. Prove Gateway and Postgres cannot be accessed publicly.
6. Prove no Gateway token, model key, Cookie, Authorization, CSRF token, or full request header appears in browser-visible data or application logs.
7. Run at least one rollback drill that removes or disables the OpenClaw public route and stops the sidecar without touching Dify containers.

The review suggested that any change to Dify container IDs or `StartedAt` timestamps during OpenClaw validation should be treated as a failure until explained.

## Release Manifest Required

The release manifest should include:

```text
SIDECAR_GIT_SHA=<full-sha>
DOCS_SHA=<full-sha>
OPENCLAW_VERSION=2026.3.13
OPENCLAW_UPSTREAM_COMMIT=<full-sha>
BRIDGE_IMAGE_DIGEST=sha256:<digest>
GATEWAY_IMAGE_DIGEST=sha256:<digest>
WORKER_IMAGE_DIGEST=sha256:<digest>
POSTGRES_IMAGE_DIGEST=sha256:<digest>
COMPOSE_SHA256=<sha256>
OPENRESTY_INCLUDE_SHA256=<sha256>
DB_SCHEMA_REVISION=<revision>
```

It should also capture sanitized outputs for:

- `docker ps --no-trunc`
- Dify container IDs, image digests, and `StartedAt`
- OpenClaw sidecar container IDs, image digests, and `StartedAt`
- `docker network inspect` for expected networks
- listening ports
- mounts, capabilities, users, restart policy, and resource limits
- CPU, memory, disk, and Dify response-time baseline

## 18443 Versus 443

Recommendation: **keep `18443` for first production validation**.

Reasoning:

- `https://ai001.huahuoai.com` and `https://ai001.huahuoai.com:18443` are different origins because the port differs.
- This gives JavaScript same-origin isolation between Dify UI and OpenClaw UI.
- Cookie scope is not port-isolated, so the Bridge must still discard unneeded Cookies, avoid logging full headers, and enforce Origin/CSRF checks.
- Moving OpenClaw under `443` as `/openclaw-lab/` and `/openclaw-api/` increases same-origin risk if the OpenClaw UI ever has XSS or supply-chain compromise.

Migration to `443` should be a separate change only after `18443` passes production validation. Conditions:

- add only exact prefixes `^~ /openclaw-lab/` and `^~ /openclaw-api/`;
- proxy only to `127.0.0.1:18181`;
- do not modify `/`, Dify upstream, global body size, global timeout, or global headers;
- use an independent include file;
- pass OpenResty syntax check before reload;
- run full Dify Chrome regression before and after reload;
- prepare a one-command include removal rollback;
- apply strict CSP to the OpenClaw UI;
- do not load arbitrary third-party scripts from the OpenClaw frontend.

## OpenClaw 2026.3.13 Security Gate

The review proposed the following production gate:

OpenClaw `2026.3.13` is not accepted for normal production traffic unless one of these paths is completed:

- upgrade to a supported/stable version that passes all system regression tests; or
- maintain an organization-patched `2026.3.13+org.1` branch with all relevant Critical/High fixes backported, tested, and documented.

Required evidence:

- exact upstream commit;
- internal patch commits;
- image digests;
- dependency lock files;
- SBOM;
- reproducible build record;
- vulnerability/advisory matrix;
- scanner reports with no unhandled Critical findings and no unhandled High findings related to enabled features;
- explicit risk acceptance for every temporary exception, with owner, approver, expiration date, compensation control, and revocation condition.

Runtime restrictions required for OpenClaw:

- no public Gateway exposure;
- strong Gateway authentication;
- disable non-business capabilities such as broad exec/elevated/browser/control UI/external channel features unless explicitly required and reviewed;
- no runtime plugin, Hook, Skill, npm package, or remote-code installation;
- no Docker socket mount;
- no host root mount;
- no Dify secret/config/data mount;
- non-root containers;
- `Privileged=false`;
- `no-new-privileges`;
- read-only root filesystem wherever practical;
- CPU, memory, PIDs, upload, task-timeout, and log limits enforced.

## Additional Architecture Concern

The review considered Bridge joining the full Dify `docker_default` network a risk. The preferred future hardening is an Auth Relay sidecar that joins Dify's network and exposes only fixed identity-check endpoints to Bridge.

Current sidecar can remain under controlled testing, but production hardening should either:

- replace direct Bridge access to `docker_default` with a constrained Auth Relay; or
- provide equivalent network-policy evidence that Bridge can only reach the intended Dify identity endpoints.

## Current Operational Decision

Proceed with the following status:

- Continue using independent public port `18443`.
- Continue real browser validation.
- Do not move to `443` yet.
- Do not claim unconditional production safety.
- Do not broaden user access until logged-in Dify regression, logged-in OpenClaw upload, security evidence, resource limits, and rollback evidence are all complete.

