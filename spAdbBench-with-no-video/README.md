# spAdbBench-with-no-video

基于 spAdbBench 的无视频版本。保留设备连接、应用管理、安装与文件、屏幕参数与按键、截图、性能监控、Logcat、系统设置、电池与电源、刷机辅助、脚本、终端、配置快照和运行日志等功能。

不包含实时视频预览、独立手机控制窗口和 scrcpy 视频通道，因此不依赖 `wetest-scrcpy`、`av`、`cv2`、`numpy` 或 `vendor/scrcpy`。二维码生成仍使用 `qrcode` 与 Pillow。

默认开启 ADB / Fastboot 自动检测，设备列表默认每 1 秒刷新一次（最低 0.2 秒）；性能采样默认间隔为 1 秒（最低 0.1 秒，可关闭）。

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

也可以双击项目内的 `run.bat`；没有 `.venv` 时会回退到系统 `python`。

## 打包

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -Clean -Zip
```

输出：

```text
dist\spAdbBench-no-video\spAdbBench-no-video.exe
dist\spAdbBench-no-video-<版本>.zip
```

发布时压缩整个 `dist\spAdbBench-no-video` 文件夹，不能只发 exe。

## 目录

```text
spAdbBench-with-no-video\
├─ main.py
├─ adbtool\                 # UI、服务与基础设施
├─ platform-tools\          # adb.exe、fastboot.exe
├─ config\                  # 设置与命令补全
├─ data\                    # 运行数据
├─ packaging\               # PyInstaller spec、图标、版本信息
├─ scripts\                 # 构建与权限脚本
└─ tests\                   # 非视频功能测试
```

## 与完整版的差异

- 移除 `adbtool/channels` 中的视频编解码与 scrcpy 控制实现，只保留空的 `ScrcpySession` 兼容层。
- 移除 `control_window.py`、`video_panel.py` 的视频实现，改为无视频提示占位。
- 设置中隐藏“屏幕预览”页和 `scrcpy-server` 路径项。
- 删除 `vendor/scrcpy` 及视频相关测试。
- 截图功能仍使用 ADB `exec-out screencap`，不需要视频依赖。
