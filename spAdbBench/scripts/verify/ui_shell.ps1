. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "ui_shell" `
    -CompileFiles @("adbtool/ui/main_window.py") `
    -Tests @("tests/test_ui_shell.py")
