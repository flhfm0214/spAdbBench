param(
    [switch]$SkipBuild,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$mainRoot = Join-Path $root "spAdbBench"
$noVideoRoot = Join-Path $root "spAdbBench-with-no-video"
$release = Join-Path $root "release"

$initText = Get-Content (Join-Path $mainRoot "adbtool\__init__.py") -Raw
if ($initText -match '__version__\s*=\s*"([^"]+)"') {
    $Version = $Matches[1]
} else {
    throw "Cannot read main version."
}
$noVideoInit = Get-Content (Join-Path $noVideoRoot "adbtool\__init__.py") -Raw
if ($noVideoInit -match '__version__\s*=\s*"([^"]+)"') {
    $noVideoVersion = $Matches[1]
} else {
    throw "Cannot read no-video version."
}
if ($noVideoVersion -ne $Version) {
    throw "Version mismatch: main=$Version no-video=$noVideoVersion"
}
Write-Host ("Building spAdbBench {0}" -f $Version)

if (-not $SkipBuild) {
    & (Join-Path $mainRoot "scripts\build_exe.ps1") -Clean -Zip -Version $Version
    if ($LASTEXITCODE -ne 0) { throw "Main build failed." }
    & (Join-Path $noVideoRoot "scripts\build_exe.ps1") -Clean -Zip -Version $Version
    if ($LASTEXITCODE -ne 0) { throw "No-video build failed." }
}

$mainSetup = Join-Path $mainRoot ("dist\spAdbBench-Setup-{0}.exe" -f $Version)
$noVideoSetup = Join-Path $noVideoRoot ("dist\spAdbBench-no-video-Setup-{0}.exe" -f $Version)

if (-not $SkipInstaller) {
    & (Join-Path $mainRoot "scripts\build_installer.ps1") -Version $Version
    if ($LASTEXITCODE -ne 0) { throw "Main installer build failed." }
    & (Join-Path $noVideoRoot "scripts\build_installer.ps1") -Version $Version
    if ($LASTEXITCODE -ne 0) { throw "No-video installer build failed." }
}

$artifacts = @(
    $mainSetup,
    (Join-Path $mainRoot ("dist\spAdbBench-{0}.zip" -f $Version)),
    $noVideoSetup,
    (Join-Path $noVideoRoot ("dist\spAdbBench-no-video-{0}.zip" -f $Version))
)
foreach ($path in $artifacts) {
    if (-not (Test-Path $path)) {
        throw "Missing release artifact: $path"
    }
}

if (Test-Path $release) {
    Remove-Item $release -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $release | Out-Null

foreach ($path in $artifacts) {
    Copy-Item $path $release -Force
}

$hashes = foreach ($file in Get-ChildItem $release -File | Sort-Object Name) {
    $hash = (Get-FileHash $file.FullName -Algorithm SHA256).Hash
    "{0}  {1}" -f $hash, $file.Name
}
$hashes | Set-Content (Join-Path $release "SHA256SUMS.txt") -Encoding ascii

Write-Host ""
Write-Host "Release artifacts:"
Get-ChildItem $release -File | Sort-Object Name | ForEach-Object {
    "{0,-48} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB)
}
