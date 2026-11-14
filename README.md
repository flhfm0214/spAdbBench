# spAdbBench

PySide6 编写的 Windows ADB 桌面工具箱，仓库同时维护两个版本：

- `spAdbBench/`：完整版，包含 scrcpy 实时画面预览与独立手机控制窗口。
- `spAdbBench-with-no-video/`：无视频版，保留设备、应用、文件、屏幕参数、性能、Logcat、系统设置、电池、刷机、脚本、终端、快照等功能，不依赖 scrcpy 视频组件。

## 仓库内容

本仓库只提交项目源码、测试、构建脚本和打包所需图标/配置模板，不包含：

- `platform-tools/`、`vendor/` 等运行时二进制
- `.venv/`、`.deps/`、`build/`、`dist/`
- `config/settings.json`、`data/`、截图和运行日志
- `release/` 中的安装包和压缩包

完整运行或打包前，请从发布包中补齐对应项目目录下的 `platform-tools/` 与 `vendor/scrcpy/`（完整版）；无视频版只需要 `platform-tools/`。

## 环境

- Windows 10/11 x64
- Python 3.14
- 完整版：`PySide6`、`wetest-scrcpy`、`qrcode`
- 无视频版：`PySide6-Essentials`、`qrcode`、`Pillow`

## 从源码运行

完整版：

```powershell
cd spAdbBench
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

无视频版：

```powershell
cd spAdbBench-with-no-video
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 打包

分别在两个项目目录下执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -Clean -Zip
```

生成 `dist\spAdbBench\` / `dist\spAdbBench-no-video\` 以及对应 ZIP。安装程序使用 `packaging\installer.iss`，需要安装 Inno Setup 6 后执行 `scripts\build_installer.ps1`。

也可以在仓库根目录执行 `build_release.ps1`，一次生成两个版本的 EXE、安装包和校验文件。

## 权限说明

打包后的主程序通过清单申请管理员权限，用于在任意本地目录创建、写入文件，并操作 ADB/Fastboot 设备。安装程序同样以管理员权限安装，但允许用户选择安装目录。

## 说明

`spAdbBench/README.md` 是完整版较详细的开发与功能说明，其中部分旧名称（如 `adb-utils`）仍在逐步整理。