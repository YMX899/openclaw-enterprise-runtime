# OpenClaw 2026.3.13 Security Decision

Status: rejected for production as currently pinned. Production use remains
No-Go unless this decision is replaced by an approved vendor patch, an approved
security exception, or an approved upgrade strategy that still satisfies the
project's fixed-version requirement.

## npm Audit Gate

Local sandbox command on 2026-06-06:

```text
npm audit --omit=dev --json
```

Reported:

```text
total vulnerabilities: 7
moderate: 2
high: 4
critical: 1
affected direct package: openclaw@2026.3.13
```

Summary groups:

```text
openclaw                critical  direct  <=2026.4.23-beta.6
@buape/carbon           high      transitive via openclaw
@hono/node-server       high      transitive via @buape/carbon
@larksuiteoapi/node-sdk high      transitive via openclaw
axios                   high      transitive via @larksuiteoapi/node-sdk
hono                    moderate  transitive via openclaw / @hono/node-server
ws                      moderate  transitive via @buape/carbon
```

Dependency path evidence:

```text
openclaw@2026.3.13
  +-- @buape/carbon@0.0.0-beta-20260216184201
  |   +-- @hono/node-server@1.19.9
  |   +-- ws@8.19.0
  +-- @larksuiteoapi/node-sdk@1.66.1
  |   +-- axios@1.13.6
  +-- hono@4.12.7
```

The direct `openclaw` advisory group includes critical and high findings in
Gateway, webhook, environment, browser/SSRF, exec, MCP, and config-mutation
surfaces. This matters for the planned deployment because V1 uses OpenClaw
Gateway WebSocket RPC and deliberately grants `operator.read` /
`operator.write` to the Bridge. Even if Gateway is kept private and never
directly exposed to the browser, the unresolved direct critical/high findings
prevent a "100% deployable and safe for Dify" production claim.

## Production Decision

```text
decision: reject_fixed_version_for_production_currently
decision_date: 2026-06-06
security_owner: not assigned
engineering_owner: Codex draft, requires human approval before production
```

Rationale:

- The pinned package itself is affected, not only unrelated transitive
  dependencies.
- At least one critical advisory and multiple high advisories remain open.
- The planned Bridge calls OpenClaw Gateway RPC, so Gateway-class advisories are
  potentially reachable by authenticated Bridge traffic.
- No vendor patch, runtime disablement proof, or security-owner exception has
  been approved.
- Local CLI/WS contract exploration does not prove vulnerability remediation.

## Allowed Next Actions

- Keep `openclaw@2026.3.13` only in offline or isolated validation.
- Run isolated Linux Docker Phase 1.5 gates only after documenting this No-Go.
- Evaluate one of these remediation paths:
  - approved vendor patch while preserving the requested 3.13 runtime identity;
  - approved security exception with exact reachable-surface analysis and
    compensating controls;
  - approved upgrade strategy if the user relaxes the strict 3.13 requirement.
- Re-run OpenClaw Gateway WS v3 contract tests after any patch or upgrade.

## Required Triage Before Any Exception

For every advisory, an exception review must record:

- advisory ID.
- package name and version.
- dependency path.
- severity.
- vulnerable function or feature.
- whether it is reachable in the planned Gateway/Bridge deployment.
- whether it is exposed to browser users.
- whether it is reachable without authentication.
- mitigation or patch.
- residual risk.
- final decision: reject, patch, upgrade, or exception.

## Required Approvals

```text
security_owner:
engineering_owner:
decision_date:
decision:
```

Allowed decisions:

```text
reject_fixed_version
vendor_patch
approve_exception
upgrade_strategy
```

No production deployment is allowed while this decision remains rejected or
unapproved.
