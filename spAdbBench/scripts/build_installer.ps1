param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$iss = Join-Path $root "packaging\installer.iss"
$isccCandidates = @(
    (Join-Path $root "..\.tools\InnoSetupNuget\tools\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup compiler (ISCC.exe) not found."
}

if (-not $Version) {
    $initText = Get-Content (Join-Path $root "adbtool\__init__.py") -Raw
    if ($initText -match '__version__\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    } else {
        throw "Cannot read __version__ from adbtool\__init__.py"
    }
}

$appDir = Join-Path $root "dist\spAdbBench"
$exe = Join-Path $appDir "spAdbBench.exe"
if (-not (Test-Path $exe)) {
    throw "Build output is missing spAdbBench.exe: $appDir"
}

& $iscc "/DAppVersion=$Version" $iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$setup = Join-Path $root ("dist\spAdbBench-Setup-{0}.exe" -f $Version)
if (-not (Test-Path $setup)) {
    throw "Installer output is missing: $setup"
}
Write-Host ("Installer: {0}" -f $setup)
