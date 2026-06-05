$ErrorActionPreference = "Stop"

$OpenClawBin = if ($env:OPENCLAW_BIN) { $env:OPENCLAW_BIN } else { "openclaw" }
$ExpectedOpenClawVersion = if ($env:EXPECTED_OPENCLAW_VERSION) {
    $env:EXPECTED_OPENCLAW_VERSION
} else {
    "OpenClaw 2026.3.13 (61d171a)"
}
$GatewayTimeoutMs = if ($env:OPENCLAW_GATEWAY_TIMEOUT_MS) {
    $env:OPENCLAW_GATEWAY_TIMEOUT_MS
} else {
    "5000"
}

function Resolve-OpenClawBinary {
    param([string]$Binary)

    if (Test-Path -LiteralPath $Binary) {
        return (Resolve-Path -LiteralPath $Binary).Path
    }

    $command = Get-Command $Binary -ErrorAction SilentlyContinue
    if (-not $command) {
        Write-Error "openclaw binary not found: $Binary"
        exit 2
    }
    return $command.Source
}

function Invoke-OpenClaw {
    param([string[]]$CommandArgs)

    $output = & $script:ResolvedOpenClawBin @CommandArgs 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String).TrimEnd()
    if ($exitCode -ne 0) {
        throw "openclaw $($CommandArgs -join ' ') failed with exit $exitCode`n$text"
    }
    return $text
}

function Assert-Contains {
    param(
        [string]$Haystack,
        [string]$Needle,
        [string]$Label
    )

    if (-not $Haystack.Contains($Needle)) {
        Write-Error "missing expected OpenClaw CLI contract token in ${Label}: $Needle"
        exit 1
    }
}

function Invoke-RpcCheck {
    param(
        [string]$Label,
        [string[]]$CommandArgs
    )

    try {
        Invoke-OpenClaw -CommandArgs $CommandArgs | Out-Null
        Write-Host "${Label}: OK"
    } catch {
        Write-Error "${Label}: FAILED"
        if (-not $env:OPENCLAW_GATEWAY_TOKEN) {
            Write-Error $_
        } else {
            Write-Error "output suppressed because OPENCLAW_GATEWAY_TOKEN is set"
        }
        exit 1
    }
}

$script:ResolvedOpenClawBin = Resolve-OpenClawBinary -Binary $OpenClawBin

Write-Host "== openclaw version =="
$version = Invoke-OpenClaw -CommandArgs @("--version")
Write-Host $version
if ($version -ne $ExpectedOpenClawVersion) {
    Write-Error "unexpected OpenClaw version; expected: $ExpectedOpenClawVersion"
    exit 1
}
Write-Host ""

$topHelp = Invoke-OpenClaw -CommandArgs @("--help")
$gatewayHelp = Invoke-OpenClaw -CommandArgs @("gateway", "--help")
$gatewayCallHelp = Invoke-OpenClaw -CommandArgs @("gateway", "call", "--help")
$gatewayStatusHelp = Invoke-OpenClaw -CommandArgs @("gateway", "status", "--help")
$gatewayProbeHelp = Invoke-OpenClaw -CommandArgs @("gateway", "probe", "--help")
$gatewayRunHelp = Invoke-OpenClaw -CommandArgs @("gateway", "run", "--help")
$doctorHelp = Invoke-OpenClaw -CommandArgs @("doctor", "--help")
$healthHelp = Invoke-OpenClaw -CommandArgs @("health", "--help")
$statusHelp = Invoke-OpenClaw -CommandArgs @("status", "--help")
$agentHelp = Invoke-OpenClaw -CommandArgs @("agent", "--help")

Assert-Contains $topHelp "gateway *" "openclaw --help"
Assert-Contains $topHelp "agent" "openclaw --help"
Assert-Contains $topHelp "health" "openclaw --help"
Assert-Contains $topHelp "status" "openclaw --help"
Assert-Contains $gatewayHelp "call" "openclaw gateway --help"
Assert-Contains $gatewayHelp "probe" "openclaw gateway --help"
Assert-Contains $gatewayHelp "run" "openclaw gateway --help"
Assert-Contains $gatewayHelp "status" "openclaw gateway --help"
Assert-Contains $gatewayHelp "--auth <mode>" "openclaw gateway --help"
Assert-Contains $gatewayHelp "--bind <mode>" "openclaw gateway --help"
Assert-Contains $gatewayHelp "--token <token>" "openclaw gateway --help"
Assert-Contains $gatewayCallHelp "gateway call [options] <method>" "openclaw gateway call --help"
Assert-Contains $gatewayCallHelp "health/status/system-presence/cron.*" "openclaw gateway call --help"
Assert-Contains $gatewayCallHelp "--url <url>" "openclaw gateway call --help"
Assert-Contains $gatewayCallHelp "--token <token>" "openclaw gateway call --help"
Assert-Contains $gatewayStatusHelp "--require-rpc" "openclaw gateway status --help"
Assert-Contains $gatewayProbeHelp "--url <url>" "openclaw gateway probe --help"
Assert-Contains $gatewayRunHelp "--force" "openclaw gateway run --help"
Assert-Contains $doctorHelp "--non-interactive" "openclaw doctor --help"
Assert-Contains $doctorHelp "--generate-gateway-token" "openclaw doctor --help"
Assert-Contains $healthHelp "--json" "openclaw health --help"
Assert-Contains $statusHelp "--json" "openclaw status --help"
Assert-Contains $agentHelp "--session-id <id>" "openclaw agent --help"
Assert-Contains $agentHelp "--json" "openclaw agent --help"

if ($doctorHelp.Contains("--lint") -or $doctorHelp.Contains("--json")) {
    Write-Error "doctor unexpectedly exposes --lint or --json; update the contract docs before deploying"
    exit 1
}

Write-Host "== openclaw gateway call --help =="
Write-Host $gatewayCallHelp
Write-Host ""
Write-Host "== openclaw gateway status --help =="
Write-Host $gatewayStatusHelp
Write-Host ""
Write-Host "== openclaw gateway probe --help =="
Write-Host $gatewayProbeHelp
Write-Host ""
Write-Host "OpenClaw CLI contract check: OK"

if ($env:OPENCLAW_GATEWAY_URL) {
    $tokenArgs = @()
    if ($env:OPENCLAW_GATEWAY_TOKEN) {
        $tokenArgs = @("--token", $env:OPENCLAW_GATEWAY_TOKEN)
    }

    Write-Host "== OpenClaw Gateway RPC checks =="
    Write-Host "gateway URL is configured; token value will not be printed"
    Invoke-RpcCheck "gateway status RPC" (@(
        "gateway", "status", "--json", "--require-rpc", "--url", $env:OPENCLAW_GATEWAY_URL,
        "--timeout", $GatewayTimeoutMs
    ) + $tokenArgs)
    Invoke-RpcCheck "gateway probe RPC" (@(
        "gateway", "probe", "--json", "--url", $env:OPENCLAW_GATEWAY_URL,
        "--timeout", $GatewayTimeoutMs
    ) + $tokenArgs)
    Invoke-RpcCheck "gateway call health" (@(
        "gateway", "call", "health", "--json", "--url", $env:OPENCLAW_GATEWAY_URL,
        "--timeout", $GatewayTimeoutMs
    ) + $tokenArgs)
    Invoke-RpcCheck "gateway call status" (@(
        "gateway", "call", "status", "--json", "--url", $env:OPENCLAW_GATEWAY_URL,
        "--timeout", $GatewayTimeoutMs
    ) + $tokenArgs)

    if ($env:OPENCLAW_GATEWAY_TOKEN) {
        try {
            Invoke-OpenClaw -CommandArgs @(
                "gateway", "call", "health", "--json", "--url", $env:OPENCLAW_GATEWAY_URL,
                "--timeout", $GatewayTimeoutMs, "--token", "__wrong_openclaw_contract_token__"
            ) | Out-Null
            Write-Error "wrong Gateway token unexpectedly succeeded"
            exit 1
        } catch {
            Write-Host "wrong Gateway token check: OK"
        }
    } else {
        Write-Host "wrong-token check skipped because OPENCLAW_GATEWAY_TOKEN is not set"
    }
} else {
    Write-Host "Gateway RPC checks skipped: set OPENCLAW_GATEWAY_URL in an isolated environment to enable them."
}
