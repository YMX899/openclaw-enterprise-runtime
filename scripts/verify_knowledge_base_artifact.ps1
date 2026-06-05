$ErrorActionPreference = "Stop"

$ArtifactDir = if ($env:KNOWLEDGE_BASE_ARTIFACT_DIR) {
    $env:KNOWLEDGE_BASE_ARTIFACT_DIR
} else {
    "artifacts\knowledge-base-short-video\2026.06.06"
}

$ResolvedArtifactDir = Resolve-Path -LiteralPath $ArtifactDir
$versionPath = Join-Path $ResolvedArtifactDir "VERSION"
$sumsPath = Join-Path $ResolvedArtifactDir "SHA256SUMS"

if (-not (Test-Path -LiteralPath $versionPath)) {
    throw "VERSION not found: $versionPath"
}
if (-not (Test-Path -LiteralPath $sumsPath)) {
    throw "SHA256SUMS not found: $sumsPath"
}

$checked = 0
foreach ($line in Get-Content -LiteralPath $sumsPath -Encoding UTF8) {
    if (-not $line.Trim()) {
        continue
    }
    if ($line -notmatch "^([0-9a-fA-F]{64})\s+(.+)$") {
        throw "Invalid SHA256SUMS line: $line"
    }
    $expected = $matches[1].ToLowerInvariant()
    $fileName = $matches[2]
    $filePath = Join-Path $ResolvedArtifactDir $fileName
    if (-not (Test-Path -LiteralPath $filePath)) {
        throw "Knowledge-base file not found: $fileName"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $filePath).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "SHA256 mismatch for ${fileName}: expected $expected got $actual"
    }
    $checked += 1
}

if ($checked -lt 1) {
    throw "No knowledge-base files verified"
}

Write-Host "knowledge-base artifact ok: $checked files verified at $ResolvedArtifactDir"
