# Development Pragmatic Gates - 2026-06-07

## Decision

The project is now using an efficiency-first development gate while keeping the
production safety bottom line.

As of 2026-06-07, web GPT/ChatGPT review is no longer required before
implementation, deployment, or root-server testing. Web review is optional only
for major architecture disputes, release/security sign-off, or an explicit user
request.

Direct root-server deployment/testing is allowed during development when the
change is reversible and does not restart, rebuild, or recreate existing Dify
containers.

## Non-Negotiable Baseline

During server-side development, these rules still apply:

- Do not restart, rebuild, or recreate existing Dify containers unless explicitly approved for a planned Dify maintenance action.
- Do not modify the Dify compose file for OpenClaw development.
- Keep OpenClaw as a sidecar service with independent rollback.
- Keep OpenClaw as an independently rollbackable sidecar during active development.
- Keep OpenClaw Gateway, Worker, and Postgres off the public network.
- Do not expose model keys, Gateway tokens, Cookies, Authorization headers, CSRF tokens, `.env` files, database URLs, TLS private keys, or full container environments in logs or documents.
- Use Git commits for meaningful local changes and push them to the configured remote repository.
- Preserve a rollback point before server deployment changes.

## Fast Development Allowances

These actions are allowed for development speed:

- Build and iterate OpenClaw sidecar code directly on the root server when needed.
- Deploy and test directly on the root server when local gates are sufficient
  for the changed surface and the rollback path is clear.
- Adjust OpenClaw sidecar compose, Bridge, Worker, Gateway, and OpenResty sidecar routing when the change is reversible and does not touch Dify containers.
- Use synthetic identities and local upload samples for fast API testing, then disable synthetic identities afterward.
- Use simplified security exceptions while the feature is still under controlled development, provided they are recorded and do not expose secrets or Dify internals.
- Defer full SBOM, vulnerability matrix, and deep hardening until production-release sign-off.

## Current Login And Video Scope

The OpenClaw login page is part of Phase 4 standalone login acceptance and is
served at:

```text
https://www.huahuoai.com/ai/openclaw-lab/
```

The OpenClaw page has its own account/password login. Users do not need to log
in to Dify Web or Dify admin for this integration. Dify Web login is no longer a
blocking gate.

The Douyin account-login scheme is retired. The active video path is video
link-read mode through URL allowlist, redirect revalidation, private-IP
blocking, worker resolution and model analysis. `REAL_SAMPLE_EVIDENCE.json` is
optional diagnostic history, not a production/development blocker.

OpenClaw can validate the link-read stage independently from deep model
analysis with a logged-in read-check endpoint/UI action. This read-check must
not require Dify Web login, must not use Douyin account cookies/storage, must
not create analysis jobs, and must return sanitized metadata only.

## Required Browser Tests

Every externally visible OpenClaw UI/API change must be tested through real Chrome against the public server.

Minimum browser checks:

- Dify `/signin` loads.
- Dify `/apps` works under the current login state or correctly redirects to login.
- At least one existing Dify app page opens when a logged-in session is available.
- If a logged-in Dify app is available, sending a normal message still works.
- OpenClaw `/ai/openclaw-lab/` loads on the public route.
- Unauthenticated OpenClaw API requests return `401`.
- Logged-in OpenClaw access is tested with the OpenClaw standalone login UI.
- File upload is tested through the browser UI when the upload feature changes.
- Browser developer console and network-visible page state show no Gateway token or model key.

## Server Checks After Browser Tests

After each meaningful deployment or public-route change, capture sanitized server evidence:

- Dify container IDs and `StartedAt` remain unchanged.
- OpenClaw sidecar containers are running.
- Gateway and Postgres have no public host port.
- Public OpenClaw health and unauthenticated auth behavior match expectation.
- Dify `/signin` and `/apps` still respond.
- No new obvious `5xx` appears in the checked paths.

## Production Sign-Off

Before broad production use, the project still needs a stricter release gate:

- real logged-in Dify regression;
- real logged-in OpenClaw upload/job/result flow;
- cross-user isolation;
- cleanup endpoint authorization;
- resource limits;
- rollback drill;
- security exception review for OpenClaw `2026.3.13`;
- documented residual-risk acceptance.
