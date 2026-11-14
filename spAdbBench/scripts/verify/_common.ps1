$ErrorActionPreference = "Stop"

$script:RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:Python = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"

function Invoke-Verify {
    param(
        [Parameter(Mandatory = $true)][string]$Area,
        [Parameter(Mandatory = $true)][string[]]$CompileFiles,
        [Parameter(Mandatory = $true)][string[]]$Tests
    )

    if (-not (Test-Path -LiteralPath $script:Python)) {
        throw "Python venv not found: $script:Python"
    }

    $baseTemp = Join-Path $script:RepoRoot ".deps\verify-tmp-$Area"
    if (Test-Path -LiteralPath $baseTemp) {
        Remove-Item -LiteralPath $baseTemp -Recurse -Force
    }

    Push-Location $script:RepoRoot
    try {
        Write-Host "== $Area =="
        & $script:Python -m py_compile @CompileFiles
        if ($LASTEXITCODE -ne 0) {
            throw "$Area compile failed"
        }

        & $script:Python -m pytest @Tests -q -p no:cacheprovider --basetemp $baseTemp
        if ($LASTEXITCODE -ne 0) {
            throw "$Area tests failed"
        }
        Write-Host "$Area OK"
    } finally {
        Pop-Location
        if (Test-Path -LiteralPath $baseTemp) {
            Remove-Item -LiteralPath $baseTemp -Recurse -Force
        }
    }
}
