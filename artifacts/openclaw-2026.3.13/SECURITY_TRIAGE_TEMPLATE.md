# OpenClaw 2026.3.13 Security Triage Template

status: TEMPLATE_PENDING
openclaw_version: 2026.3.13
production_decision: reject

Do not copy this template to `SECURITY_TRIAGE.md` until every advisory is
reviewed by named human owners. This file is not production approval.

## Required Owners

```text
security_owner: <name>
engineering_owner: <name>
decision_date: <YYYY-MM-DD>
decision: reject | vendor_patch | approve_exception | upgrade_strategy
```

## Required Summary

```text
npm_audit_command: npm audit --omit=dev --json
npm_audit_total: <number>
npm_audit_critical: <number>
npm_audit_high: <number>
runtime_scope: private OpenClaw Gateway behind Bridge only
browser_exposure: Gateway token never sent to browser
bridge_scopes: operator.read, operator.write
operator_admin: forbidden
```

## Required Advisory Rows

Every row must be filled. `reachable` may be `yes`, `no`, or `unknown`.
Production approval is forbidden while any critical/high advisory is
`reachable: yes` or `reachable: unknown` without a listed patch or approved
compensating control.

| advisory_id | package | version | severity | dependency_path | affected_surface | reachable | exposed_to_browser | unauthenticated | mitigation | residual_risk | decision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| <id> | openclaw | 2026.3.13 | critical | direct | gateway/webhook/env/browser/exec/MCP/config | unknown | no | unknown | <patch/control> | <risk> | reject |
| <id> | @buape/carbon | <version> | high | openclaw -> @buape/carbon | <surface> | unknown | no | unknown | <patch/control> | <risk> | reject |
| <id> | @hono/node-server | <version> | high | openclaw -> @buape/carbon -> @hono/node-server | <surface> | unknown | no | unknown | <patch/control> | <risk> | reject |
| <id> | @larksuiteoapi/node-sdk | <version> | high | openclaw -> @larksuiteoapi/node-sdk | <surface> | unknown | no | unknown | <patch/control> | <risk> | reject |
| <id> | axios | <version> | high | openclaw -> @larksuiteoapi/node-sdk -> axios | <surface> | unknown | no | unknown | <patch/control> | <risk> | reject |
| <id> | hono | <version> | moderate | openclaw -> hono / @hono/node-server -> hono | <surface> | unknown | no | unknown | <patch/control> | <risk> | reject |
| <id> | ws | <version> | moderate | openclaw -> @buape/carbon -> ws | <surface> | unknown | no | unknown | <patch/control> | <risk> | reject |

## Required Compensating Controls

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

## Final Approval

```text
approved_by_security_owner: <name>
approved_by_engineering_owner: <name>
approval_date: <YYYY-MM-DD>
approval_scope: phase1.5 only | production phase2
```

Passing this triage is not enough by itself. Production also requires the real
video artifact, real sample evidence, isolated Docker proof, authenticated Dify
baseline, and production readiness audit to pass.
