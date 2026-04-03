param(
    [string]$Name = "routehub",
    [string]$IconPath = "config_ui\\static\\icons\\app-icon.ico",
    [switch]$OneDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    $modeArgs = if ($OneDir) { @("--onedir") } else { @("--onefile") }
    $dataArg = "config_ui\static;config_ui\static"
    $iconArgs = @()
    if (Test-Path $IconPath) {
        $iconArgs = @("--icon", $IconPath)
    }

    & python -m PyInstaller `
        --noconfirm `
        --clean `
        --name $Name `
        @modeArgs `
        @iconArgs `
        --add-data $dataArg `
        service_entry.py

    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
