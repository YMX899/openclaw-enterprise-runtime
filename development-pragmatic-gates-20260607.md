# Development Pragmatic Gates - 2026-06-07

## Decision

The project is now using an efficiency-first development gate while keeping the production safety bottom line.

We no longer require a web GPT review before every implementation step. Web GPT review remains optional for major architecture changes, security disputes, or release sign-off.

## Non-Negotiable Baseline

During server-side development, these rules still apply:

- Do not restart, rebuild, or recreate existing Dify containers unless explicitly approved for a planned Dify maintenance action.
- Do not modify the Dify compose file for OpenClaw development.
- Keep OpenClaw as a sidecar service with independent rollback.
- Keep the public OpenClaw lab on an independent port during active development.
- Keep OpenClaw Gateway, Worker, and Postgres off the public network.
- Do not expose model keys, Gateway tokens, Cookies, Authorization headers, CSRF tokens, `.env` files, database URLs, TLS private keys, or full container environments in logs or documents.
- Use Git commits for meaningful local changes and push them to the configured remote repository.
- Preserve a rollback point before server deployment changes.

## Fast Development Allowances

These actions are allowed for development speed:

- Build and iterate OpenClaw sidecar code directly on the root server when needed.
- Adjust OpenClaw sidecar compose, Bridge, Worker, Gateway, and OpenResty sidecar routing when the change is reversible and does not touch Dify containers.
- Use synthetic identities and local upload samples for fast API testing, then disable synthetic identities afterward.
- Use simplified security exceptions while the feature is still under controlled development, provided they are recorded and do not expose secrets or Dify internals.
- Defer full SBOM, vulnerability matrix, and deep hardening until production-release sign-off.

## Required Browser Tests

Every externally visible OpenClaw UI/API change must be tested through real Chrome against the public server.

Minimum browser checks:

- Dify `/signin` loads.
- Dify `/apps` works under the current login state or correctly redirects to login.
- At least one existing Dify app page opens when a logged-in session is available.
- If a logged-in Dify app is available, sending a normal message still works.
- OpenClaw `/openclaw-lab/` loads on the public port.
- Unauthenticated OpenClaw API requests return `401`.
- Logged-in OpenClaw access is tested when a Dify login session is available.
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

