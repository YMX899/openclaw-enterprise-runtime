# OpenClaw 2026.3.13 Security Decision

Status: unresolved. Production use is No-Go until this file is completed and
approved.

## npm Audit Gate

Local sandbox audit reported:

```text
total vulnerabilities: 7
moderate: 2
high: 4
critical: 1
affected direct package: openclaw@2026.3.13
```

## Required Triage

For every advisory:

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

No production deployment is allowed while this decision is blank.

