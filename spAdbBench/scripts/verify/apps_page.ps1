. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "apps_page" `
    -CompileFiles @("adbtool/ui/pages/apps_page.py") `
    -Tests @("tests/test_apps_page.py")
