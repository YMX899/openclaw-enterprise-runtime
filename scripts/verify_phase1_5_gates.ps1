param(
    [string]$ComposeFile = "openclaw-video/docker-compose.openclaw-video.yaml",
    [string]$PythonCmd = "python",
    [switch]$SkipDocker,
    [switch]$RunComposeUp,
    [switch]$RequireDouyinArtifact,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"

function Step($Name) {
    Write-Host "==> $Name"
}

function Fail($Message) {
    Write-Error $Message
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Step "git rollback anchor"
$status = git status --short
if ($status -and -not $AllowDirty) {
    Fail "git worktree is not clean; commit or discard unrelated changes before Phase 1.5 exit."
}
$head = git rev-parse HEAD
$tags = git tag --points-at HEAD
Write-Host "HEAD=$head"
Write-Host "TAGS=$tags"
Write-Host "PYTHON=$PythonCmd"

Step "Python dependency gate"
& $PythonCmd -c "import cryptography, fastapi, httpx, jsonschema, psycopg, pydantic, requests, websockets; import volcenginesdkarkruntime; from psycopg.types.json import Jsonb"

Step "Python tests"
$env:PYTHONPATH = "openclaw-video/src"
& $PythonCmd -m unittest discover openclaw-video/tests -v
& $PythonCmd -m compileall openclaw-video/src openclaw-video/tests

Step "Node syntax"
node --check scripts/verify_openclaw_gateway_ws_contract.mjs

Step "static phase gates"
$staticGate = @'
from pathlib import Path

compose = Path("openclaw-video/docker-compose.openclaw-video.yaml").read_text(encoding="utf-8")
required = [
    "127.0.0.1:18181:3000",
    "OPENCLAW_GATEWAY_URL: ws://openclaw-gateway:18789",
    "OPENCLAW_GATEWAY_TOKEN_FILE: /run/secrets/openclaw_gateway_token",
    "OPENCLAW_GATEWAY_DEVICE_KEY_FILE: /run/secrets/openclaw_bridge_device_key.pem",
    "WORKER_CONCURRENCY: \"1\"",
    "MAX_DOWNLOAD_BYTES: \"536870912\"",
    "MAX_VIDEO_DURATION_SECONDS: \"60\"",
    "MAX_VIDEO_FRAMES: \"1200\"",
    "DOUYIN_CHONG_BIN: /usr/local/bin/openclaw-douyin-adapter",
    "DOUYIN_CHONG_ENV_FILE: /run/secrets/douyin_chong_env",
    "./secrets/douyin_chong.env:/run/secrets/douyin_chong_env:ro",
    "./vendor/douyin_chong:/app/vendor/douyin_chong:ro",
    "read_only: true",
    "/tmp:size=1024m,nosuid,nodev",
    "pids_limit: 128",
]
for needle in required:
    if needle not in compose:
        raise SystemExit(f"missing compose gate: {needle}")
for forbidden in [
    "0.0.0.0:18789",
    "0.0.0.0:5432",
    "/var/run/docker.sock",
    "OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN",
    "OPENCLAW_GATEWAY_TOKEN:",
    "internal: true",
]:
    if forbidden in compose:
        raise SystemExit(f"forbidden compose surface: {forbidden}")

manifest = Path("artifacts/douyin_chong/ARTIFACT_MANIFEST.md").read_text(encoding="utf-8")
if "Status: missing" in manifest:
    print("douyin_chong artifact gate: MISSING")
elif "Status: verified" in manifest:
    print("douyin_chong artifact gate: VERIFIED")
else:
    print("douyin_chong artifact gate: CANDIDATE_NOT_VERIFIED")
'@
$staticGate | & $PythonCmd -

if ($RequireDouyinArtifact) {
    $manifest = Get-Content -Path "artifacts/douyin_chong/ARTIFACT_MANIFEST.md" -Raw
    if ($manifest -notmatch "Status:\s*verified") {
        Fail "RequireDouyinArtifact was set, but artifacts/douyin_chong/ARTIFACT_MANIFEST.md is not verified."
    }
}

if ($SkipDocker) {
    Write-Host "Docker gates skipped by operator request. This is not a Phase 1.5 exit proof."
    exit 0
}

Step "Docker availability"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "docker command is unavailable. Phase 1.5 cannot exit and production Phase 2 remains NO-GO."
}

Step "compose render"
$renderedPath = Join-Path $env:TEMP "openclaw-video-compose.phase1_5.rendered.yaml"
docker compose -f $ComposeFile config | Out-File -Encoding utf8 $renderedPath
$rendered = Get-Content -Path $renderedPath -Raw
foreach ($forbidden in @("0.0.0.0:18789", "0.0.0.0:5432", "/var/run/docker.sock", "--token", "internal: true")) {
    if ($rendered.Contains($forbidden)) {
        Fail "compose render exposes forbidden surface: $forbidden"
    }
}

Step "compose build"
docker compose -f $ComposeFile build --no-cache

if ($RunComposeUp) {
    Step "compose up isolated sidecar"
    docker compose -f $ComposeFile up -d
    docker compose -f $ComposeFile ps

    Step "localhost health"
    Invoke-WebRequest -Uri "http://127.0.0.1:18181/healthz" -UseBasicParsing -TimeoutSec 10 | Out-Null

    Step "port exposure check"
    $ports = netstat -ano -p tcp
    if ($ports -match "0\.0\.0\.0:18181|0\.0\.0\.0:18789|0\.0\.0\.0:5432") {
        Fail "forbidden public listener detected"
    }
} else {
    Write-Host "Compose up skipped. Use -RunComposeUp only in an isolated Docker/Linux validation host."
}

Write-Host "Phase 1.5 gate checks completed for this environment."
