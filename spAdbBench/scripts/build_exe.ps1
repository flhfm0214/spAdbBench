param(
    [switch]$Clean,
    [switch]$Zip,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$spec = Join-Path $root "packaging\adb-utils.spec"
$build = Join-Path $root "build"
$dist = Join-Path $root "dist"
$app = Join-Path $dist "spAdbBench"

if (-not (Test-Path $python)) {
    throw "Python venv not found: $python"
}

if (-not $Version) {
    $initFile = Join-Path $root "adbtool\__init__.py"
    $initText = Get-Content $initFile -Raw
    if ($initText -match '__version__\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    } else {
        throw "Cannot read __version__ from $initFile"
    }
}

$versionInfo = Join-Path $root "packaging\version_info.txt"
$versionText = Get-Content $versionInfo -Raw
if (-not $versionText.Contains($Version)) {
    Write-Warning "packaging/version_info.txt does not contain version $Version; update it before release."
}

if ($Clean) {
    foreach ($path in @($build, $dist)) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
        }
    }
}

& $python -m PyInstaller --noconfirm --clean --distpath $dist --workpath $build $spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}
$exe = Join-Path $app "spAdbBench.exe"
if (-not (Test-Path $exe)) {
    throw "Build output is missing spAdbBench.exe: $app"
}

# Keep runtime resources next to the executable (onedir layout).
$platformTools = Join-Path $root "platform-tools"
$targetTools = Join-Path $app "platform-tools"
if (-not (Test-Path $platformTools)) {
    throw "platform-tools not found: $platformTools"
}
robocopy $platformTools $targetTools /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

$configDir = Join-Path $app "config"
$dataDir = Join-Path $app "data"
New-Item -ItemType Directory -Force -Path $configDir, $dataDir | Out-Null
$settingsExample = Join-Path $root "config\settings.example.json"
if (-not (Test-Path $settingsExample)) {
    throw "settings example not found: $settingsExample"
}
Copy-Item $settingsExample $configDir -Force
Copy-Item (Join-Path $root "README.md") $app -Force

$zipPath = $null
if ($Zip) {
    $zipPath = Join-Path $dist ("spAdbBench-{0}.zip" -f $Version)
    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }
    Compress-Archive -Path $app -DestinationPath $zipPath -CompressionLevel Optimal
}

$size = (Get-ChildItem $app -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("Build completed: {0} ({1:N1} MB)" -f $app, ($size / 1MB))
Write-Host ("Version: {0}" -f $Version)
if ($zipPath) {
    Write-Host ("Archive: {0}" -f $zipPath)
}

exit 0
