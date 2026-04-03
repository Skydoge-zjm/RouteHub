param(
    [string]$Config = "E:\api_test\router_config.json",
    [string]$CaptureDir = "E:\api_test\captures",
    [switch]$Capture,
    [switch]$CaptureRequest,
    [switch]$CaptureResponse,
    [switch]$CaptureHeadersOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "capture_proxy.py"

$argsList = @(
    $pythonScript,
    "--config", $Config,
    "--capture-dir", $CaptureDir
)

if ($Capture) {
    $argsList += "--capture"
}

if ($CaptureRequest) {
    $argsList += "--capture-request"
}

if ($CaptureResponse) {
    $argsList += "--capture-response"
}

if ($CaptureHeadersOnly) {
    $argsList += "--capture-headers-only"
}

& python @argsList

exit $LASTEXITCODE
