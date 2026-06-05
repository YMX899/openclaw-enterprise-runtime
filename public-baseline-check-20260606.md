# Public Baseline Check

Status: passed for unauthenticated baseline.

This file records non-authenticated public baseline checks only. It must not
contain cookies, tokens, CSRF values, full request headers, or private account
data.

Command template:

```powershell
python openclaw-video\tests\public_baseline_check.py --base-url https://ai001.huahuoai.com
```

Expected gate:

- `/signin` returns 200.
- `/apps` returns 200 or a login redirect accepted by current Dify policy.
- `/console/api/account/profile` returns 401 when not logged in.

Authenticated Dify app flow is a separate gate and must be performed through a
real logged-in browser without recording cookies or tokens.

## Run 2026-06-06

Command:

```powershell
python openclaw-video\tests\public_baseline_check.py --base-url https://ai001.huahuoai.com
```

Result:

```json
{
  "schema": "openclaw-video-public-baseline.v1",
  "base_url": "https://ai001.huahuoai.com",
  "checks": [
    {
      "path": "/signin",
      "status": 200,
      "final_url": "https://ai001.huahuoai.com/signin",
      "elapsed_ms": 353
    },
    {
      "path": "/apps",
      "status": 200,
      "final_url": "https://ai001.huahuoai.com/apps",
      "elapsed_ms": 316
    },
    {
      "path": "/console/api/account/profile",
      "status": 401,
      "final_url": "https://ai001.huahuoai.com/console/api/account/profile",
      "elapsed_ms": 249
    }
  ],
  "secrets_recorded": false
}
```

