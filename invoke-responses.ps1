param(
    [string]$Url = "http://127.0.0.1:8327/v1/responses",
    [string]$ApiKey = "codex-proxy-key",
    [string]$Model = "gpt-5.4",
    [Alias("Input")]
    [string]$Prompt = "Say ping",
    [string]$SystemPrompt = "",
    [string]$ReasoningEffort = "medium",
    [string]$Verbosity = "medium",
    [int]$TimeoutSeconds = 60,
    [switch]$ShowEvents
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "invoke_responses.py"

$argsList = @(
    $pythonScript,
    "--url", $Url,
    "--api-key", $ApiKey,
    "--model", $Model,
    "--input", $Prompt,
    "--timeout-seconds", $TimeoutSeconds
)

if ($SystemPrompt) {
    $argsList += @("--system-prompt", $SystemPrompt)
}

if ($ReasoningEffort) {
    $argsList += @("--reasoning-effort", $ReasoningEffort)
}

if ($Verbosity) {
    $argsList += @("--verbosity", $Verbosity)
}

if ($ShowEvents) {
    $argsList += "--show-events"
}

& python @argsList
$exitCode = $LASTEXITCODE
exit $exitCode
