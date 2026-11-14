param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Area
)

$ErrorActionPreference = "Stop"
$allowed = @("packages", "apps_page", "foreground_bar", "performance_page", "ui_shell", "snapshot_registry", "snapshot_service", "snapshot_ui", "flash")
$areas = @()
foreach ($item in $Area) {
    $areas += $item -split ","
}

foreach ($name in $areas) {
    if ($name -notin $allowed) {
        throw "Unknown verification area: $name"
    }
    & (Join-Path $PSScriptRoot "$name.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
