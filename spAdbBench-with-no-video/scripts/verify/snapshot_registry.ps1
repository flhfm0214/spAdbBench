. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "snapshot_registry" `
    -CompileFiles @("adbtool/services/snapshot_registry.py") `
    -Tests @("tests/test_snapshot_registry.py")
