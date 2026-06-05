# douyin_chong Security Review

Status: unresolved. Production use is No-Go until this file is completed.

## Required Review Areas

- SSRF resistance.
- redirect revalidation.
- DNS rebinding handling.
- maximum download size.
- maximum video duration.
- maximum frame count.
- network egress destinations.
- temporary file cleanup.
- non-root execution.
- read-only root filesystem compatibility.
- CPU, memory and PID limits.
- no Docker socket.
- no Dify credentials.
- no shell command construction from user input.
- JSON schema validation.

## Approval

```text
security_owner:
engineering_owner:
decision_date:
decision:
```

