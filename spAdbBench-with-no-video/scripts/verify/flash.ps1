. "$PSScriptRoot\_common.ps1"

Invoke-Verify `
    -Area "flash" `
    -CompileFiles @(
        "adbtool/services/flash.py",
        "adbtool/ui/pages/flash_page.py",
        "adbtool/ui/main_window.py"
    ) `
    -Tests @(
        "tests/test_flash_service.py",
        "tests/test_flash_page.py",
        "tests/test_ui_shell.py"
    )
