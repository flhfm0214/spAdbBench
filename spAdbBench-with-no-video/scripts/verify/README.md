# 分模块验证

只运行本次修改涉及的模块，不再每次执行完整测试集。

| 验证脚本 | 对应源码 | 测试 |
| --- | --- | --- |
| `packages.ps1` | `adbtool/services/packages.py` | `test_package_service.py`、`test_extract_batch.py` |
| `apps_page.ps1` | `adbtool/ui/pages/apps_page.py` | `test_apps_page.py` |
| `foreground_bar.ps1` | `adbtool/ui/widgets/foreground_bar.py` | `test_foreground_bar.py` |
| `performance_page.ps1` | `adbtool/ui/pages/performance_page.py` | `test_metrics_page.py` |
| `ui_shell.ps1` | 主窗口与页面布局 | `test_ui_shell.py` |
| `snapshot_registry.ps1` | `adbtool/services/snapshot_registry.py` | `test_snapshot_registry.py` |
| `snapshot_service.ps1` | `adbtool/services/snapshot.py`、`snapshot_files.py` | `test_snapshot_service.py` |
| `snapshot_ui.ps1` | `snapshot_page.py`、`ui/context.py`、`main_window.py` | `test_snapshot_ui.py`、`test_ui_shell.py` |
| `flash.ps1` | `adbtool/services/flash.py`、`flash_page.py` | `test_flash_service.py`、`test_flash_page.py`、`test_ui_shell.py` |

单独运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\packages.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\apps_page.ps1
```

只运行多个已修改模块：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\run.ps1 packages,apps_page,foreground_bar
```

脚本只对相关源码执行 `py_compile`，并只运行对应测试；pytest 临时目录放在项目 `.deps/verify-tmp-<area>`，完成后删除，不在项目根目录留下 `pytest-of-*` 或 `.pytest_cache`。如果 PowerShell 执行策略阻止脚本，用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\packages.ps1
```
