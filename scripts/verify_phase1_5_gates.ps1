param(
    [string]$ComposeFile = "openclaw-video/docker-compose.openclaw-video.yaml",
    [string]$PythonCmd = "python",
    [switch]$SkipDocker,
    [switch]$RunComposeUp,
    [switch]$RequireDouyinArtifact,
    [switch]$RequireOpenClawSecurityApproval,
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

function Assert-LastExitCode($Message) {
    if ($LASTEXITCODE -ne 0) {
        Fail "$Message failed with exit code $LASTEXITCODE"
    }
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
& $PythonCmd -B -c "import cryptography, fastapi, httpx, jsonschema, psycopg, pydantic, requests, websockets; import volcenginesdkarkruntime; from psycopg.types.json import Jsonb"
Assert-LastExitCode "Python dependency gate"

Step "Python tests"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "openclaw-video/src"
& $PythonCmd -B -m unittest discover openclaw-video/tests -v
Assert-LastExitCode "Python unittest"
& $PythonCmd -B -m compileall openclaw-video/src openclaw-video/tests
Assert-LastExitCode "Python compileall"

Step "vendored douyin_chong source gate"
$vendorGate = @'
from hashlib import sha256
from pathlib import Path
import subprocess

vendor = Path("openclaw-video/vendor/douyin_chong")
hashes = vendor / "SOURCE_SHA256SUMS"
expected_files = {
    "__init__.py",
    "clients/__init__.py",
    "clients/ark_video.py",
    "clients/douyin.py",
    "clients/resolver.py",
    "clients/tiktok.py",
    "config.py",
    "models.py",
    "README.md",
}
entries = {}
for line in hashes.read_text(encoding="utf-8").splitlines():
    digest, relative = line.split("  ", 1)
    entries[relative] = digest
if set(entries) != expected_files:
    raise SystemExit(f"vendor hash manifest mismatch: {sorted(set(entries) ^ expected_files)}")
for relative, expected_digest in entries.items():
    try:
        data = subprocess.check_output(
            ["git", "show", f"HEAD:openclaw-video/vendor/douyin_chong/{relative}"],
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        data = (vendor / relative).read_bytes()
    actual = sha256(data).hexdigest()
    if actual != expected_digest:
        raise SystemExit(f"vendor source digest mismatch: {relative}")
for forbidden in [".env", ".env.local", ".douyin_storage_state.json", "douyin_login_state.py", "profile_batch_fashion.py"]:
    if (vendor / forbidden).exists():
        raise SystemExit(f"forbidden vendor file present: {forbidden}")
for path in vendor.rglob("*"):
    text = str(path).lower()
    if "__pycache__" in text or path.suffix in {".pyc", ".log", ".json"} or "storage" in text or "cookie" in text:
        raise SystemExit(f"forbidden vendor runtime artifact present: {path}")
print("vendor source gate: OK")
'@
$vendorGate | & $PythonCmd -B -
Assert-LastExitCode "vendored douyin_chong source gate"

Step "Node syntax"
node --check scripts/verify_openclaw_gateway_ws_contract.mjs
Assert-LastExitCode "Node syntax"

Step "static phase gates"
$staticGate = @'
import json
from pathlib import Path
import re


def is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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
elif "Status: minimal candidate source vendored" in manifest:
    print("douyin_chong artifact gate: MINIMAL_SOURCE_NOT_MODEL_VERIFIED")
else:
    print("douyin_chong artifact gate: CANDIDATE_NOT_VERIFIED")

decision = Path("artifacts/douyin_chong/LINK_READ_DECISION.md").read_text(encoding="utf-8")
required_decision = [
    r"link_read_mode:\s*ADOPTED\b",
    r"REAL_SAMPLE_EVIDENCE\.json:\s*NOT_REQUIRED\b",
    r"douyin_account_login:\s*NOT_REQUIRED\b",
    r"browser_storage_state:\s*NOT_REQUIRED\b",
    r"runtime_path:\s*url_guard\s*->\s*worker_service\s*->\s*douyin_legacy_adapter\s*->\s*UniversalVideoResolver\b",
    r"allowlisted_douyin_hosts:\s*PASS\b",
    r"redirect_revalidation:\s*PASS\b",
    r"private_ip_blocking:\s*PASS\b",
    r"no_browser_login_state:\s*PASS\b",
]
missing_decision = [pattern for pattern in required_decision if not re.search(pattern, decision, re.IGNORECASE)]
if missing_decision:
    raise SystemExit("link-read decision is incomplete")

url_guard = Path("openclaw-video/src/openclaw_video/url_guard.py").read_text(encoding="utf-8")
worker = Path("openclaw-video/src/openclaw_video/worker_service.py").read_text(encoding="utf-8")
adapter = Path("openclaw-video/src/openclaw_video/douyin_legacy_adapter.py").read_text(encoding="utf-8")
required_source = [
    (url_guard, "ALLOWED_HOST_SUFFIXES"),
    (url_guard, '"douyin.com"'),
    (url_guard, '"iesdouyin.com"'),
    (url_guard, "validate_video_url_with_redirects"),
    (url_guard, "blocked non-public IP"),
    (worker, "validate_video_url_with_redirects("),
    (worker, "canonical = validated.canonical"),
    (worker, "analysis = self.analyzer(canonical, Path(tmp))"),
    (adapter, "UniversalVideoResolver().resolve(args.input_url)"),
    (adapter, 'getattr(video, "video_url"'),
    (adapter, 'getattr(video, "playwm_url"'),
    (adapter, "ArkVideoClient(config).analyze(video_urls=video_urls"),
]
for source, needle in required_source:
    if needle not in source:
        raise SystemExit(f"missing link-read source marker: {needle}")
print("video link-read mode gate: VERIFIED")
'@
$staticGate | & $PythonCmd -B -
Assert-LastExitCode "static phase gates"

Step "OpenClaw 2026.3.13 security decision"
$openClawSecurityGate = @'
from pathlib import Path

decision = Path("artifacts/openclaw-2026.3.13/SECURITY_DECISION.md").read_text(encoding="utf-8").lower()
if "decision: reject_fixed_version_for_production_currently" in decision:
    print("openclaw security gate: REJECTED_FOR_PRODUCTION")
elif "decision: approve_exception" in decision or "decision: vendor_patch" in decision or "decision: upgrade_strategy" in decision:
    if "security_owner: not assigned" in decision or "engineering_owner: codex draft" in decision:
        raise SystemExit("openclaw security decision is present but not human-approved")
    print("openclaw security gate: APPROVED")
else:
    raise SystemExit("openclaw security decision is missing or unrecognized")
'@
$openClawSecurityGate | & $PythonCmd -B -
Assert-LastExitCode "OpenClaw security decision"

if ($RequireDouyinArtifact) {
    $manifest = Get-Content -Path "artifacts/douyin_chong/ARTIFACT_MANIFEST.md" -Raw
    if ($manifest -notmatch "Status:\s*verified") {
        Fail "RequireDouyinArtifact was set, but artifacts/douyin_chong/ARTIFACT_MANIFEST.md is not verified."
    }
    $linkReadDecision = Get-Content -Path "artifacts/douyin_chong/LINK_READ_DECISION.md" -Raw
    if ($linkReadDecision -notmatch "link_read_mode:\s*ADOPTED") {
        Fail "RequireDouyinArtifact was set, but video link-read mode is not adopted."
    }
}

if ($RequireOpenClawSecurityApproval) {
    $securityDecision = Get-Content -Path "artifacts/openclaw-2026.3.13/SECURITY_DECISION.md" -Raw
    if ($securityDecision -notmatch "decision:\s*(approve_exception|vendor_patch|upgrade_strategy)") {
        Fail "RequireOpenClawSecurityApproval was set, but OpenClaw 2026.3.13 is not approved for production."
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
Assert-LastExitCode "docker compose config"
$rendered = Get-Content -Path $renderedPath -Raw
foreach ($forbidden in @("0.0.0.0:18789", "0.0.0.0:5432", "/var/run/docker.sock", "--token", "internal: true")) {
    if ($rendered.Contains($forbidden)) {
        Fail "compose render exposes forbidden surface: $forbidden"
    }
}

Step "compose build"
docker compose -f $ComposeFile build --no-cache
Assert-LastExitCode "docker compose build"

Step "worker image smoke"
$workerImage = docker compose -f $ComposeFile images -q video-analysis-worker
Assert-LastExitCode "docker compose images"
if (-not $workerImage) {
    Fail "could not resolve built video-analysis-worker image id"
}
docker run --rm -e SKIP_SECRET_STAGING=1 $workerImage openclaw-douyin-adapter --help | Out-Null
Assert-LastExitCode "worker image adapter help smoke"
docker run --rm -e SKIP_SECRET_STAGING=1 $workerImage python -c "from openclaw_video.douyin_legacy_adapter import _load_legacy_components; print([component.__name__ for component in _load_legacy_components()])"
Assert-LastExitCode "worker image adapter loader smoke"

if ($RunComposeUp) {
    Step "compose up isolated sidecar"
    try {
        docker compose -f $ComposeFile up -d
        Assert-LastExitCode "docker compose up"
        docker compose -f $ComposeFile ps
        Assert-LastExitCode "docker compose ps"

        Step "localhost health"
        Invoke-WebRequest -Uri "http://127.0.0.1:18181/healthz" -UseBasicParsing -TimeoutSec 10 | Out-Null

        Step "port exposure check"
        $ports = netstat -ano -p tcp
        if ($ports -match "0\.0\.0\.0:18181|0\.0\.0\.0:18789|0\.0\.0\.0:5432") {
            Fail "forbidden public listener detected"
        }
    }
    finally {
        docker compose -f $ComposeFile down --remove-orphans --volumes
        Assert-LastExitCode "docker compose down"
    }
} else {
    Write-Host "Compose up skipped. Use -RunComposeUp only in an isolated Docker/Linux validation host."
}

Write-Host "Phase 1.5 gate checks completed for this environment."
