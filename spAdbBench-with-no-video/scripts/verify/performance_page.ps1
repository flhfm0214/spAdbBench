. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "performance_page" `
    -CompileFiles @("adbtool/ui/pages/performance_page.py") `
    -Tests @("tests/test_metrics_page.py")
