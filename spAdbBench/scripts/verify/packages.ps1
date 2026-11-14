. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "packages" `
    -CompileFiles @("adbtool/services/packages.py") `
    -Tests @("tests/test_package_service.py", "tests/test_extract_batch.py")
