# OpenClaw 2026.3.13 Artifact Manifest

Status: incomplete. This file is a production gate, not a deployment approval.

Requested product version:

```text
openclaw@2026.3.13
expected CLI output: OpenClaw 2026.3.13 (61d171a)
```

## Required Evidence Before Phase 2

The OpenClaw artifact must be locked before it can be used in any server
deployment:

- source type: npm tarball, source checkout, or container image.
- artifact URL or repository URL.
- exact version string.
- tarball integrity or image digest.
- SHA256 for downloaded files.
- Node.js version.
- lockfile or package manager metadata.
- install command.
- runtime user.
- state directory.
- config directory.
- Gateway bind address and port.
- Gateway auth mode.
- Gateway token storage method.
- API surface Bridge will call.
- rollback and uninstall procedure.
- SBOM.
- dependency scan result.
- license and production-use approval.

## Current Known Local Evidence

```text
npm package: openclaw
version: 2026.3.13
integrity: sha512-/juSUb070Xz8K8CnShjaZQr7CVtRaW4FbR93lgr1hLepcRSbyz2PQR+V4w5giVWkea61opXWPA6Vb8dybaztFg==
shasum: 559b4cc4a605616ada0d11a9ca29b7395af91e0e
local sandbox output: OpenClaw 2026.3.13 (61d171a)
```

This is not sufficient for production.

## Observed CLI Surface For 2026.3.13

Local read-only CLI help checks confirmed the following fixed-version surface:

```text
openclaw --version
openclaw --help
openclaw gateway --help
openclaw gateway call --help
openclaw gateway status --help
openclaw gateway probe --help
openclaw gateway run --help
openclaw doctor --help
openclaw health --help
openclaw status --help
openclaw agent --help
```

Important corrections:

- `openclaw doctor --lint --json` is not exposed by this fixed-version help
  output and must not be used as a production gate.
- `openclaw gateway` is a WebSocket Gateway surface with RPC-style
  `gateway call <method>` helpers, not an HTTP REST contract by default.
- The local Bridge placeholder path `POST /channels/dify-web/chat` remains
  unproven and must not be treated as an OpenClaw standard API.
- `gateway run --force`, `gateway start`, `gateway restart`, `gateway stop`,
  `gateway install` and `doctor --repair/--fix` are operational commands and
  must not run during read-only checks.

## Fixed-Version Gateway Regression Gates

Before production, the fixed artifact must pass these checks in an isolated
Ubuntu 24.04 environment:

- `openclaw --version`
- read-only CLI surface checks in `scripts/verify_openclaw_contract.sh`.
- `openclaw doctor --non-interactive` in an isolated environment.
- `openclaw gateway status --json --require-rpc --url <ws-url>`.
- `openclaw gateway probe --json --url <ws-url>`.
- `openclaw gateway call health --json --url <ws-url>`.
- `openclaw gateway call status --json --url <ws-url>`.
- wrong-token and rotated-token checks when token auth is enabled.
- Bridge contract tests against the exact Gateway RPC/adapter path.
- Wrong-token request fails closed.
- Rotated-token request fails closed.
- Gateway token never appears in browser-facing responses.

The following public reports are mandatory risk checks for `2026.3.13`:

- `openclaw/openclaw#46117`: missing `operator.read` in status/probe despite a
  paired token.
- `openclaw/openclaw#48008`: token mismatch, stale port conflict, and entrypoint
  drift after upgrading to `2026.3.13`.

These reports do not prove this deployment will fail, but they prevent treating
"installable" as "production-ready".
