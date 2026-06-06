# douyin_chong Vendor Slot

Status: minimal candidate source subset, not verified for production.

Only the V1 single-video source subset of the candidate `douyin_chong` package
may be placed here. Never copy runtime secrets, browser state, generated
outputs, caches or sample credentials into this directory.

Forbidden files include:

```text
.env
.env.*
*storage*
*.log
__pycache__/
*.pyc
profile_batch_exports/
cover_exports/
video_fashion_exports/
knowledge_exports/
```

The production worker mounts this directory read-only at
`/app/vendor/douyin_chong` and calls the candidate only through
`openclaw-douyin-adapter`, with credentials mounted separately at runtime as
`/run/secrets/douyin_chong_env`.

`SOURCE_SHA256SUMS` pins the current vendored source files. It is evidence for
local change control, not a production image digest.
