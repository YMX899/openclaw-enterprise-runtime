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

## Fixed-Version Gateway Regression Gates

Before production, the fixed artifact must pass these checks in an isolated
Ubuntu 24.04 environment:

- `openclaw --version`
- `openclaw doctor --lint --json`
- `openclaw doctor --deep`
- `openclaw gateway status --deep`
- `openclaw gateway probe`
- `openclaw status --deep`
- `openclaw devices list`
- Bridge contract tests against the exact Gateway API path.
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

