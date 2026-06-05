# OpenClaw Gateway Contract

Status: draft. The real Gateway API contract is not locked.

## Required Contract Tests

The Bridge must prove the exact fixed-version Gateway behavior before server
deployment:

- health/status endpoint path.
- chat or response endpoint path.
- required auth header format.
- timeout behavior.
- error response schema.
- wrong token behavior.
- missing token behavior.
- token rotation behavior.
- request payload schema.
- response payload schema.
- streaming/SSE support if used.
- no Gateway token leaks to browser API responses.

## Current Placeholder

The local draft client uses:

```text
GET  /health
POST /channels/dify-web/chat
Authorization: Bearer <gateway-token>
```

This path is intentionally treated as unproven. It must be replaced or approved
by contract tests against the fixed OpenClaw `2026.3.13` Gateway artifact.

