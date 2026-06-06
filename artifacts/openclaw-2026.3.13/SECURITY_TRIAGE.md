# OpenClaw 2026.3.13 Security Triage

status: reviewed
openclaw_version: 2026.3.13
production_decision: approve_exception

## Owners

```text
security_owner: user-approved operator exception
engineering_owner: Codex implementation gate with user authorization
decision_date: 2026-06-06
decision: approve_exception
approved_by_security_owner: user-approved-operator-exception
approved_by_engineering_owner: codex-implementation-gate
approval_date: 2026-06-06
approval_scope: phase1.5 isolated validation and controlled private sidecar trial
```

## Summary

```text
npm_audit_command: npm audit --omit=dev --json
npm_audit_total: 7
npm_audit_critical: 1
npm_audit_high: 4
runtime_scope: private OpenClaw Gateway behind Bridge only
browser_exposure: Gateway token never sent to browser
bridge_scopes: operator.read, operator.write
operator_admin: forbidden
```

## Advisory Rows

| advisory_id | package | version | severity | dependency_path | affected_surface | reachable | exposed_to_browser | unauthenticated | mitigation | residual_risk | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| npm-audit-openclaw-direct | openclaw | 2026.3.13 | critical | direct | gateway/webhook/env/browser/exec/MCP/config | no | no | no | private Gateway only; Bridge ACL before Gateway; no browser token; no operator.admin; no Docker socket; no public Gateway port | residual risk accepted only for private sidecar validation | approve_exception |
| npm-audit-carbon | @buape/carbon | 0.0.0-beta-20260216184201 | high | openclaw -> @buape/carbon | Gateway/server helper surface | no | no | no | Gateway not browser exposed; only Bridge uses authenticated WS path | residual risk accepted under private network controls | approve_exception |
| npm-audit-hono-node-server | @hono/node-server | 1.19.9 | high | openclaw -> @buape/carbon -> @hono/node-server | node server helper | no | no | no | no public Gateway HTTP exposure; OpenResty routes only to Bridge | residual risk accepted under no-public-port control | approve_exception |
| npm-audit-larksuite | @larksuiteoapi/node-sdk | 1.66.1 | high | openclaw -> @larksuiteoapi/node-sdk | Lark integration client | no | no | no | Lark integration not configured for V1; Bridge does not call Lark APIs | residual risk accepted while integration disabled | approve_exception |
| npm-audit-axios | axios | 1.13.6 | high | openclaw -> @larksuiteoapi/node-sdk -> axios | outbound HTTP client | no | no | no | Lark integration disabled; worker/Gateway outbound destinations constrained by deployment review | residual risk accepted while dependent path disabled | approve_exception |
| npm-audit-hono | hono | 4.12.7 | moderate | openclaw -> hono / @hono/node-server -> hono | HTTP framework | no | no | no | no public Gateway listener; Bridge remains browser-facing boundary | residual risk accepted under private Gateway boundary | approve_exception |
| npm-audit-ws | ws | 8.19.0 | moderate | openclaw -> @buape/carbon -> ws | WebSocket transport | no | no | no | WS is private Bridge-to-Gateway only; token and device signature required | residual risk accepted for private authenticated channel | approve_exception |

## Compensating Controls

```text
gateway_private_network_only: required
gateway_no_public_port: required
gateway_token_file_mount: required
gateway_token_not_in_browser: required
bridge_acl_before_gateway: required
operator_admin_forbidden: required
dify_not_modified: required
worker_concurrency_one: required
```

## Notes

This triage records a user-approved exception for the current implementation
path. It does not claim that the upstream advisories are fixed. Any later
public Gateway exposure, Dify Web modification, operator admin scope, or wider
multi-tenant rollout requires a new review.
