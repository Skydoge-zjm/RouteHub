param(
    [string]$Config = $(if ($env:ROUTER_PROXY_CONFIG) { $env:ROUTER_PROXY_CONFIG } else { Join-Path $HOME ".router-proxy\router_config.json" }),
    [string]$CaptureDir = $(Join-Path $HOME ".router-proxy\captures"),
    [switch]$Capture,
    [switch]$CaptureRequest,
    [switch]$CaptureResponse,
    [switch]$CaptureHeadersOnly,
    [string]$StatsLogPath = $(Join-Path $HOME ".router-proxy\logs"),
    [string]$UiHost = "127.0.0.1",
    [int]$UiPort = 8340
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonModule = "router_proxy.service"

$argsList = @(
    "-m", $pythonModule,
    "--config", $Config,
    "--capture-dir", $CaptureDir,
    "--stats-log-path", $StatsLogPath,
    "--ui-host", $UiHost,
    "--ui-port", $UiPort
)

if ($Capture) { $argsList += "--capture" }
if ($CaptureRequest) { $argsList += "--capture-request" }
if ($CaptureResponse) { $argsList += "--capture-response" }
if ($CaptureHeadersOnly) { $argsList += "--capture-headers-only" }

Push-Location $scriptDir
try {
    & python @argsList
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
