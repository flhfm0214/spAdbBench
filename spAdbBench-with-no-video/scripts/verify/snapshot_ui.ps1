. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "snapshot_ui" `
    -CompileFiles @(
        "adbtool/services/snapshot.py",
        "adbtool/ui/context.py",
        "adbtool/ui/pages/snapshot_page.py",
        "adbtool/ui/main_window.py",
        "adbtool/ui/widgets/danger_dialog.py"
    ) `
    -Tests @("tests/test_snapshot_ui.py", "tests/test_ui_shell.py")
