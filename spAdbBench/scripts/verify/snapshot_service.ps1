. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "snapshot_service" `
    -CompileFiles @("adbtool/services/snapshot.py", "adbtool/services/snapshot_files.py") `
    -Tests @("tests/test_snapshot_service.py")
