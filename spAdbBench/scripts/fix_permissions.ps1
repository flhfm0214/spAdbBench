# 可选：以管理员身份运行，提升项目目录的完整性级别。
# 适用于 icacls 显示 "Mandatory Label\Low Mandatory Level" 的情况。
# 运行前请关闭 adb-utils，避免 .venv / platform-tools 中的 DLL 被占用。
$ErrorActionPreference = "Stop"
$target = "H:\ADB_ tool"
$appDir = Join-Path $target "adb-utils"
$launcher = Join-Path $target "启动 adb-utils.bat"
$log = Join-Path $appDir ".deps\fix_permissions.log"
$deps = Split-Path $log -Parent
if (-not (Test-Path -LiteralPath $deps)) {
    New-Item -ItemType Directory -Path $deps | Out-Null
}

function Write-Log {
    param([string]$Text)
    $Text | Out-File -LiteralPath $log -Append -Encoding utf8
}

"=== $(Get-Date -Format o) ===" | Out-File -LiteralPath $log -Encoding utf8
"Before root:" | Out-File -LiteralPath $log -Append -Encoding utf8
(icacls $target) 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8

& icacls $target /setintegritylevel Medium 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
& icacls $appDir /setintegritylevel Medium /T /C /Q 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
if (Test-Path -LiteralPath $launcher) {
    & icacls $launcher /setintegritylevel Medium 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
}

# G:\APKs 默认只授予 Everyone 读取；如需继续使用该目录导出 APK，给当前用户 Modify。
$apkDir = "G:\APKs"
if (Test-Path -LiteralPath $apkDir) {
    "Granting Modify on $apkDir to $env:USERNAME" | Out-File -LiteralPath $log -Append -Encoding utf8
    & icacls $apkDir /grant "${env:USERNAME}:(OI)(CI)M" /T /C 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
}

"After root:" | Out-File -LiteralPath $log -Append -Encoding utf8
(icacls $target) 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
"After venv python:" | Out-File -LiteralPath $log -Append -Encoding utf8
(icacls (Join-Path $appDir ".venv\Scripts\python.exe")) 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
"After adb:" | Out-File -LiteralPath $log -Append -Encoding utf8
(icacls (Join-Path $appDir "platform-tools\adb.exe")) 2>&1 | Out-File -LiteralPath $log -Append -Encoding utf8
