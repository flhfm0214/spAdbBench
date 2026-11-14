. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "foreground_bar" `
    -CompileFiles @("adbtool/ui/widgets/foreground_bar.py") `
    -Tests @("tests/test_foreground_bar.py")
