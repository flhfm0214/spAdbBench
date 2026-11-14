# adb-utils

PySide6 桌面 ADB 工具箱。项目按 UI、服务、视频/控制通道、基础设施四层组织，覆盖设备连接、应用管理、文件传输、显示控制、性能监控、Logcat、系统设置、电池、刷机辅助、脚本、终端以及设备配置快照与回滚。

当前进度：基础层、主窗口与导航、设备连接、应用管理、安装与文件、屏幕与按键、性能监控、Logcat、系统设置、电池与电源、脚本、终端、scrcpy 服务通道、视频面板与官方独立控制窗口、配置快照页面、刷机辅助页面、应用设置界面已完成。所有侧边栏功能均已实现。

## 目录与启动

```text
H:\ADB_ tool\
├─ 启动 adb-utils.bat          # 双击启动
└─ adb-utils\                  # 项目本体
   ├─ main.py                  # Python 入口
   ├─ run.bat                  # 项目内启动脚本
   ├─ adbtool\                 # 四层源码
   ├─ tests\                   # 自动化测试
   ├─ platform-tools\          # 随项目提供的 ADB
   ├─ vendor\scrcpy\           # scrcpy-server + 官方独立窗口运行时
   ├─ docs\                    # 实施计划
   └─ .deps\                   # 开发期截图与依赖缓存
```

双击根目录的 `启动 adb-utils.bat` 即可启动。启动脚本进入 `adb-utils`，优先使用项目内 `.venv`，虚拟环境缺失时回退到系统 `python`，然后运行 `main.py`。

## 环境要求

- Windows 10/11 x64
- Python 3.14
- Google Platform-Tools（项目已包含 `platform-tools/adb.exe`）

## 安装

在 `adb-utils` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`wetest-scrcpy` 通过腾讯 PyPI 镜像安装：

```powershell
.\.venv\Scripts\python.exe -m pip install wetest-scrcpy==0.4.0 --extra-index-url https://mirrors.tencent.com/repository/pypi/tencent_pypi/simple
```

## ADB 路径

程序按以下顺序定位 ADB：

1. `config/settings.json` 中的 `adb_path`；
2. 项目目录 `platform-tools/adb.exe`；
3. 系统 `PATH` 中的 `adb`。

项目已提供 Platform-Tools 37.0.1，默认直接使用；`fastboot.exe` 与 `adb.exe` 位于同一目录。

## 设备与连接

顶部设备下拉与「设备与连接」页面共享当前设备状态。

- 顶部设备下拉与「设备与连接」页面同时显示 ADB 与 Fastboot 设备。进入 fastboot/bootloader 后，页面切换为 Fastboot 操作区，只保留重启到系统、Bootloader、Recovery、继续启动和重启到 EDL 等常用按钮；无线调试、ADB 重启与设备属性等 ADB 专属区域整体变灰不可用。
- 启动时先检测一次 ADB / Fastboot 设备；如果没有发现设备，每秒重试一次，直到发现设备后停止。持续自动检测默认关闭，可在「设置 → 常规 → 自动检测 ADB / Fastboot 设备」中开启；开启后默认每 1 秒继续轮询，检测间隔可在 0.2–60 秒之间调整。
- 关闭自动检测时仍可点「刷新设备」手动检测；轮询不会写入运行日志，避免每次检测产生一条记录。
- 「设备与连接」表格中的任意 ADB / Fastboot 设备均可单击选中后点「设备操作」行里的「断开设备」或「删除选中」，也可右键选择「断开设备」或「删除设备」；USB 设备断开后点「刷新设备」会自动恢复连接，无线设备需要重新执行 `adb connect`。删除只是从列表隐藏，离线设备刷新后不会重新出现，只有重新在线后刷新才会再次显示。
- 无线调试支持「二维码配对」：点击后直接生成 Android 11+ 配对二维码，手机选择「使用二维码配对设备」扫描即可；程序通过 `adb mdns services` 自动发现配对服务、执行 `adb pair`，配对成功后继续发现连接服务并 `adb connect`。
- 手动输入的地址与配对码会记录在「设备操作」区域；配对或连接失败时保留失败记录，右键可删除记录，双击记录可回填地址。没有记录时列表自动隐藏。
- 重启、断开或切换设备后，终端、Logcat、性能采样与预览会按各自页面规则停止旧任务。

## 应用管理

「应用管理」页面异步读取应用列表，并显示当前前台应用、包名与 Activity。

- 单击复选框勾选应用；双击包名、类型或状态列也能切换勾选；按住 Shift 点击两行可勾选连续范围。
- 未勾选应用时，单个应用操作与批量启用/禁用不可用；仅勾选一个应用时可执行启动、停止、卸载、清除数据、应用信息等操作。
- 「导出所选 APK」支持一次勾选多个应用，把每个应用的 base APK 与 split APK 依次拉取到同一目录，并显示逐项结果。
- 「启用/禁用 Google 套件」不依赖勾选状态，按当前列表中 Google 包的实际启用状态批量处理。
- 打开页面、切换回页面或点击「刷新应用」时，会刷新应用列表和前台应用信息；工具栏的「重启前台应用」会先强制停止再重新启动当前前台应用。

## 屏幕与按键

「屏幕与按键」页面读取 `wm size` 与 `wm density`，同时显示当前生效值和物理值；存在覆盖值时标记「覆盖」。

- 修改分辨率、修改 DPI 会先展示将执行的完整命令与影响，确认后执行。
- 「恢复初始分辨率」「恢复初始 DPI」恢复页面首次读取到的状态：首次读取时已有覆盖值，就写回该值；首次没有覆盖值，才用 `wm size reset` / `wm density reset` 清除后续覆盖。这样不会把厂商或用户原本设置的显示密度覆盖成物理默认值。
- 页面显示「初始值」，方便在修改后核对；如果软件重启后初始值已被新的当前值覆盖，可在「运行日志」中查找修改前的 `wm density` / `wm size` 输出并手动填回。
- 按键区提供主页、返回、最近任务、菜单、方向键、电源、唤醒、休眠、音量、静音、回车、删除、相机和媒体控制，共 21 个按键。
- 截图使用 `adb exec-out screencap -p` 直接写入本地 PNG，不经过设备临时目录；默认保存到设置中默认保存位置的 `screenshots/<序列号>-<时间>.png`，完成后在页面预览，并可打开图片或所在目录。
- 设备屏幕关闭或处于安全界面时，截图可能是黑屏，需要先唤醒设备。

## 性能监控

「性能监控」页面与右侧「实时信息」面板使用同一条后台采样通道，读取当前设备：

- CPU 总占用率、每个核心的当前频率与占用率
- 内存总量、已用、可用与交换分区
- 电池电量、充电状态、健康、温度、电压与供电来源
- 系统负载、运行时间
- GPU 渲染器、OpenGL ES 版本、平台与型号

采样间隔可在页面中输入 0.1–60 秒，默认 1 秒；填 0 禁用自动刷新，仍可用「立即采样」，设置写入 `config/settings.json`。采样使用异步 `QProcess`，界面不会等待命令；切换设备时会取消旧设备的在途采样，并丢弃过期结果。首次采样没有上一条 `/proc/stat` 差值，CPU 占用显示「采样中」，下一次采样后开始显示百分比。

打开「性能监控」页面时会立即重新采样，并刷新页面顶部的前台应用；「重启前台应用」会先强制停止再重新启动该应用。

右侧「实时信息」面板随设备连接自动开始采样，设备断开或切换到未授权状态时停止并清空；「屏幕预览」固定在主页右侧，不提供关闭、浮动或移动操作。

自动轮询不写入「运行日志」，避免每两秒一条采样记录淹没手动操作记录；采样失败会显示在页面和侧栏，并写入状态栏。

## Logcat

「Logcat」页面通过一条后台 `adb logcat -v threadtime -T 1` 流式读取日志，不阻塞界面。

- 最低级别筛选：Verbose、Debug、Info、警告、错误、致命
- 关键字筛选，不区分大小写
- 可选应用包名：先异步执行 `pidof` 定位 PID，再用 `--pid` 只读取该应用日志
- 开始、停止、暂停/继续、清空、导出
- 自动滚动开关与当前行数
- 页面按 120ms 批量刷新，最多保留 3000 行，避免高频日志拖慢界面
- 切换设备或停止时取消日志进程并清空本次视图
- 自动日志进程不写入运行日志，避免持续刷屏

真实设备验证：在 OnePlus 6 上运行 4.5 秒收到 22 条日志，级别、Tag 与消息解析正常。

## 系统设置

「系统设置」页面通过异步 `settings get/put` 读取和写入当前设备：

- 字体倍率 0.5–3.0，恢复值为 1.0
- 窗口、过渡、属性三项动画倍率 0–10，0 表示关闭
- 自动锁屏 0–65535 秒，写入时换算为毫秒；0 表示不熄屏
- 沉浸模式写入 `global policy_control=immersive.full=*`，关闭时写入 `null`
- 隐藏状态栏图标：提供时钟、闹钟、蓝牙、Wi-Fi、移动信号、电池、音量、旋转锁定、定位、同步、耳机、投屏 12 项
- 「隐藏状态栏图标」中的复选框勾选表示隐藏该图标，取消勾选表示恢复显示；按钮文字为「应用隐藏设置」「全部隐藏」「全部显示」
- 读取黑名单时，厂商特有的未知图标（例如 OnePlus 的 `nfc`、`wlb`）会显示在「其他已隐藏的系统图标」并保留，应用时不会丢失
- 隐藏设置支持 Global、Secure、System 三张表；读取不确认，写入前统一确认
- 非法表、非法键、空值、包含换行或空字符的值不会执行
- 写入成功后记录到 `data/settings_history.json`，按设备序列号分组；失败不记录
- 读取与写入均为异步 `QProcess`，界面不等待命令

所有值通过远端 shell 单引号转义后写入，值中的单引号会被安全处理。

## 电池与电源

「电池与电源」页面读取 `dumpsys battery`，显示电量、温度、电压、状态、健康、供电来源、电流与原始输出。

- 模拟电量、温度、电池状态、交流电/USB/无线供电、拔出充电器、恢复真实电池
- 所有模拟操作先走「模拟电池状态」确认框，文案说明重启后失效
- 模拟状态记录到 `data/battery_simulation.json`；执行恢复后清除
- 定时采样默认 2 秒，范围 1–60 秒；最多保留 50000 条
- 样本可导出 UTF-8 BOM 的 CSV，列为时间、电量、温度、电压、状态、电流
- 自动采样不写入运行日志，避免刷屏
- 切换设备或离开页面时停止采样并取消在途读取

真实设备读取结果：OnePlus 6 电量 86%、温度 29.1 °C、电压 4252 mV、状态「充电中」、供电 USB。

## 刷机辅助

「刷机辅助」页面提供重启入口、OEM 解锁命令与镜像刷写命令生成，所有设备写操作都需要确认。

- 重启模式：Bootloader、Recovery、EDL、Fastbootd。每次重启前展示将执行的重启命令，确认框默认「取消」；EDL 标注仅部分机型支持。
- 重启命令发送成功后停止当前 scrcpy 会话与性能采样，并延迟刷新设备列表，等待设备重新连接。
- 解锁/回锁：仅在设备进入 Fastboot / Bootloader 后可用，生成 `fastboot -s <序列号> oem unlock` / `oem lock`，可复制命令；ADB 模式下按钮保持灰色不可点击。点击「执行解锁」「执行回锁」并再次确认后，通过异步 fastboot 进程执行。
- 镜像刷入入口：分区可编辑下拉（boot、init_boot、recovery、vbmeta、vendor_boot、dtbo），选择本地镜像后生成 `fastboot flash <分区> "<路径>"`。本工具只生成和复制命令，不执行 fastboot。
- ADB 修复：重启 ADB 服务（`kill-server` + `start-server`）、重连离线设备、刷新设备列表、查看 `adb version`；这些操作不修改设备数据，不需要危险确认。
- 重启与设备修复命令通过异步 `QProcess` 执行，解锁/回锁通过异步 fastboot 进程执行，界面不等待；生成命令只做本地校验。

## 脚本

「脚本」页面执行 `.bat` 子集的只读/ADB 操作，不执行本地删除、格式化等命令。

支持：

- `@echo off`、`echo`、`echo.`
- `set NAME=value`、`%NAME%` 变量展开
- `:label`、`goto label`
- `timeout /t N`、`choice /t N`、`pause`（非交互运行直接跳过）
- `exit /b N`
- 以 `adb ` 或 `@adb ` 开头的命令
- `rem` 与 `::` 注释

不支持的本地命令会在结果表标记「不支持」，不会执行。解释器限制 2000 步、单次等待 300 秒，检测死循环；ADB 命令在后台线程执行，界面可停止。运行前统一弹出「运行脚本」确认，写明脚本名、行数、设备与本地命令限制。表格中的长内容会自动省略，双击任意结果行可打开完整详情，支持复制全部。

真实设备验证：`adb shell echo script-ok` 在后台线程执行成功，输出 `script-ok`。

## 终端

「终端」页面支持 ADB、设备 shell 与 Fastboot 三种模式，通过工具栏下拉切换；默认进入 ADB 模式。

- **ADB 模式**：输入 `devices`、`install -r "D:\a b\app.apk"`、`shell getprop ...` 等命令，每条命令异步执行 `adb -s <序列号> ...`，流式显示输出。`adb ` 前缀会自动去掉，`-s` 会替换为当前设备。
- **Shell 模式**：保持一条长驻 `adb -s <序列号> shell` 会话，输入设备 shell 命令并流式显示。
- **Fastboot 模式**：检测到 fastboot 设备后终端自动切换；每条命令异步执行 `fastboot -s <序列号> ...`，流式显示输出。未检测到 fastboot 设备时也可以手动选择 Fastboot 模式，顶部显示与 ADB 未连接时一致的等待提示；命令速查也包含 fastboot 子命令。
- 设备退出或切换时保留终端历史，并插入 `----------时间，设备名已退出-----------` 分隔行；切换设备、模式或页面都不会清空此前的 ADB/Fastboot 输出，历史只在应用退出时清除。
- 终端使用指南仅通过快捷键 `F1` 打开列表视图，不再占用工具栏按钮。
- 没有可用设备时，终端上方以醒目提示条显示「等待设备连接」，并分别提示 ADB 调试或 bootloader / fastboot 的连接方式，同时输入区保持未激活。
- 命令输入直接位于终端文本内部，不再单独占一行输入栏；提示符后显示光标。输出区等宽，最多保留 20000 行，命令本身留在终端历史中。
- Linux 快捷键：Ctrl+A 行首、Ctrl+E 行尾、Ctrl+U 删除到行首、Ctrl+K 删除到行尾、Ctrl+W 删除前一个词、Ctrl+C 中断、Ctrl+L 清屏、Shift+Insert 粘贴。
- 右键菜单提供粘贴、复制、全部复制、全选、中断当前命令、清屏。
- Tab 采用交换机式行为：空输入列出当前模式的前 20 个命令；唯一候选原地补全并加空格；多候选在终端内列出候选及语法，命令保持原样；无匹配时保留原命令和焦点。
- 补全会先识别当前命令，再补全该命令的子命令或选项：例如 `pm ` 列出 pm 子命令，`pm h` 优先显示 `help` / `hide`，`pm list ` 列出 `packages` 等，`settings get g` 补全 `global`；包名只在 `pm install`、`pm list packages` 等参数位置补全。
- 支持管道分段补全：输入 `|` 后按 Tab 列出并补全 Linux 管道工具，包括 `grep`、`sed`、`awk`、`cut`、`sort`、`uniq`、`tr`、`tee`、`head`、`tail`、`wc`、`xargs`、`paste`、`join`、`comm`、`od`、`hexdump`、`strings`、`base64`、`md5sum`、`gzip`、`tar` 等；例如 `pm list packages | gr` → `grep`，`sort -` 会列出排序选项；只解析最后一个管道后的内容，引号或反斜杠中的 `|` 不作为分段符。
- ADB 模式补全 ADB 子命令及其已知参数（如 `adb reboot b` → `bootloader`）；Shell 模式补全 shell 命令、命令子项和异步加载的包名，包名大小写敏感；Fastboot 模式补全 fastboot 子命令。
- 补全规则保存在 `config/completions/`：设置 →「路径与存储」→「打开补全配置目录」可直接编辑 `commands.json` 或新增 `<命令>.json`，保存后回终端按 Tab 自动重载，无需重启。
- 终端下方「命令速查」列出全部 ADB、shell 与 fastboot 命令、类型、完整语法和说明，可按命令、语法或说明搜索；选中行显示完整语法，双击命令会切换到对应模式并填入输入框。
- 包名加载失败只提示状态，不阻塞输入；切换设备会停止旧会话与命令并丢弃旧包名结果，避免设备 A 的补全内容写入设备 B，但保留终端历史。

真实设备验证：OnePlus 6 上 `echo 终端-ok` 输出 `终端-ok`，`getprop ro.product.model` 输出 `ONEPLUS A6000`。

## 运行日志

「运行日志」页面记录用户操作触发的 ADB 命令（性能监控与 Logcat 自动轮询除外）：

- 时间、设备序列号、完整命令、退出码、耗时、成功/失败/超时/取消
- 完整 stdout 与 stderr，可在详情区查看、复制命令、复制输出
- 按设备、命令、输出或错误筛选，可只看失败
- 导出本次运行记录为 `.jsonl`，默认持久化到 `data/execution-log.jsonl`
- 日志会持续追加写入，应用正常关闭时再次刷新到磁盘；重新启动只显示本次运行产生的新记录，历史日志仍保留在日志文件夹
- 页面顶部明确提示持久化行为，并提供「打开日志文件夹」按钮；底部显示历史条数与本次条数
- 打开日志文件夹直接启动 `explorer.exe` 并传入目录，不经过 Windows `ShellExecute`，避免 `ShellExecute ... failed (error 5)`；「屏幕与按键」的「打开目录」使用同一实现

日志在命令结束时立即追加到文件。软件异常退出时，已经完成的命令仍保留在文件中；下一步执行前可先查看上一条 `wm density` 或 `wm size` 的输出，确认正确值后手动填回。

## scrcpy-server

`wetest-scrcpy 0.4.0` 使用 `ct-scrcpy-ctrl` / `ct-scrcpy-video` 两个抽象 socket，并向 scrcpy-server 传入版本 `1.2.4` 与 `udt_socket_name`。项目在 `vendor/scrcpy/scrcpy-server` 放置与该客户端配套的 Tencent scrcpy-server，运行时由程序推送并启动。

独立窗口使用官方 [scrcpy](https://github.com/Genymobile/scrcpy) 4.1 的 Windows 运行时，放在 `vendor/scrcpy/native/`：`scrcpy.exe`、`scrcpy-server`、SDL3/FFmpeg/libusb DLL 和上游 `LICENSE.txt`。运行时以无边框窗口启动，再嵌入「手机控制」Qt 窗口的画面区，侧边栏按键通过 ADB 发送；该运行时与工具箱内嵌预览的 Tencent server 相互独立。

官方 `scrcpy-server v5.0.1` 使用 `scrcpy_<scid>` socket，协议与上述客户端不同；该文件保存在 `vendor/scrcpy/reference/scrcpy-server-v5.0.1`，仅作参考，不参与启动。

使用时无需手动推送 server；程序会在视频会话启动时校验 `vendor/scrcpy/scrcpy-server` 并推送到设备。

### 服务通道

`adbtool/channels/` 已实现完整的后台通道：

- `ScrcpyServerProcess`：异步 push server，并用 QProcess 长驻运行 `app_process`；停止时终止进程并等待有限时间。
- `ScrcpyControlWorker`：在 QThread 中连接 `ct-scrcpy-ctrl`，连接失败按定时器重试；提供点击、滑动、按键和截图。
- `ScrcpyVideoWorker`：在后台线程读取 `ct-scrcpy-video` 并用 `wetest-scrcpy` 解码为 `QImage`，限制最大帧率，不进入 UI 线程。
- `ScrcpySession`：按「启动服务 → 等待控制连接 → 等待视频 → 已连接」编排，统一暴露归一化坐标；任何错误进入「错误」状态并清理相关线程与进程。

OnePlus 6 实测：视频帧 512×1080，控制通道读取到物理分辨率 1080×2280；腾讯 server 的 CAPTURE 截图为空，因此会话截图复用最近一帧视频画面。视频连接状态栏的分辨率改为读取设备 `wm size` 的有效值，避免高分辨率设备被 `max_size` 缩放后显示成视频尺寸。停止后设备端无残留 `adbtool-scrcpy-server.jar` 进程。

### 屏幕预览

- 右侧面板名称为「屏幕预览」，只显示画面，不响应点击和拖动；每秒截取并显示 1 帧，降低常驻预览占用。
- 选中已连接设备后自动启动预览，切换设备会自动切换到新设备；预览区域保持宽高比居中。
- 底部有醒目的「打开独立窗口操作设备」按钮，提示实际控制需要在独立窗口完成。
- 点击后打开「手机控制」窗口：左侧为常用按键和实时状态，右侧嵌入官方 scrcpy 的 GPU 画面。
- 常用按键包含主页、返回、任务、音量 +、音量 -、电源、菜单；顶部提供「采样间隔」输入框（0.1–60 秒，0 为禁用），与性能监控页共享设置；实时状态包含 CPU/内存占用、CPU/GPU 频率、CPU/GPU/电池温度，以及设备 `thermal_zone` 传感器温度；CPU 温度优先取 CPU0 对应的传感器。
- 控制窗口复用应用级性能采样通道，不额外启动第二套采样；性能采样沿用原有内容与间隔。旋转检测每秒执行一次轻量 `dumpsys display`。
- 设备横屏时自动把按键和性能状态移到窗口顶部、画面放在下方，并调整窗口尺寸；顶部面板按内容收紧，不保留空白，内嵌画面持续贴合剩余区域，不会溢出或撑大窗口。
- 「屏幕预览」宽度固定为 340px，画面尺寸提示不参与窗口最小尺寸计算；全屏后恢复不会因为预览帧变大而撑宽主窗口。
- 每台已连接设备拥有独立的「手机控制」窗口和独立 scrcpy 进程，可以同时打开多台设备；切换主页当前设备不会关闭其他设备的控制窗口，设备断开或窗口关闭时才结束对应进程。
- 工具箱内的「屏幕预览」永久固定在主页右侧，没有关闭按钮，不能浮动或拖动，也不会因为打开独立窗口而隐藏或停止刷新。
- 预览底部提供「关闭预览 / 启用预览」按钮；默认启用。关闭后会停止当前 scrcpy 预览以降低设备占用；空闲自动关闭默认开启，默认 1 分钟，可在「设置 → 屏幕预览 → 自动关闭」中关闭或调整时间。
- 切换当前设备时，预览只接收新会话的视频帧；旧设备已经排队的迟到帧会被丢弃，不会与新画面叠加闪烁。
- 独立窗口使用 `vendor/scrcpy/native/scrcpy.exe`（官方 scrcpy 4.1，Apache 2.0），ADB 使用项目内置 `platform-tools/adb.exe`；侧边栏按键通过异步 `adb shell input keyevent` 发送。
- scrcpy 意外退出时控制窗口保持打开，显示退出码和最后一条日志，并提供「重新连接画面」按钮，不再自动关闭窗口。
- 关闭独立窗口时只结束该设备对应的 scrcpy 进程；工具箱预览会继续按 1fps 刷新。

## 应用设置

侧边栏左下角的「设置」按钮（快捷键 `Ctrl+,`）打开应用设置，设置保存在 `config/settings.json`。

- **常规**：主题（默认深色，不跟随系统外观）、自动检测 ADB / Fastboot 设备（默认关闭）、检测间隔（0.2–60 秒，默认 1 秒）、选中设备后自动连接预览、性能采样间隔（0.1–60 秒，默认 1 秒，0 为关闭）。
- **屏幕预览**：预览刷新频率 1–60 帧/秒、视频最大分辨率（上限 2160p）、视频码率（上限 32 Mbps）。修改后正在运行的预览会自动重连一次；独立控制窗口使用单独的 60 帧通道，不受预览频率影响。
- **路径与存储**：默认保存位置、ADB 路径（留空自动探测）、scrcpy-server 路径、运行数据目录。截图、快照、APK 导出和拉取文件都以默认保存位置为根目录，分别写入 `screenshots`、`snapshots`、`apk`、`files` 子目录。
- **安全**：卸载、清除数据、修改分辨率、模拟电池等危险操作的确认框始终启用，默认焦点为「取消」。

所有带范围的可输入设置项在输入框右侧标注单位与上限；下拉选择项不再额外标注上限。「系统设置」中的字体倍率、三项动画倍率与自动锁屏时间同时提供非线性滑动条：默认值位于轨道中间偏左，越向右拖动变化越快，滑动条在数值框左侧并与数值双向同步。「恢复默认」可重置为出厂值。ADB 路径变更立即对后续命令生效，主题与预览频率保存后立即生效。

## 主题

界面提供浅色、深色、跟随系统三种模式，在「视图 → 主题」或左下角「设置 → 常规」中切换，选择写入 `config/settings.json`。颜色、字号、间距与控件样式集中在 `adbtool/infrastructure/theme.py`。

## 配置快照

快照功能将分辨率、DPI、字体大小、三项动画倍率、自动锁屏时间、沉浸模式、隐藏状态栏图标设置、本工具修改过的 Global/Secure/System 键值、电池模拟状态、已禁用应用列表、设备序列号与型号、采集时间写入 JSON。

快照按设备序列号分组。每个设置项记录对应的读取命令与写入命令。回滚前展示当前值与快照值对比，不可读或缺失的项标记为「不可用」并跳过；回滚完成后提示是否重启设备。

页面操作：

- 「导出当前配置」逐项读取设备配置，显示可取消的进度条；完成后选择保存位置，默认文件名为 `adbtool-snapshot-<序列号>-<时间>.json`，默认目录为设置中默认保存位置下的 `snapshots`。
- 「导入快照」选择 JSON 文件，按当前设备序列号查找记录并自动开始对比；快照中没有当前设备时显示「当前设备不在快照中」，回滚按钮保持禁用。
- 「快照文件」列出目录中所有快照的时间、型号、序列号、项数与文件名；选中后点击「对比所选」或双击记录开始对比。
- 对比表默认勾选「可用且不同」的项目；相同项不勾选，不可用项置灰且无法勾选。每行 tooltip 包含读取、写入和重置命令。
- 「全选可用」「全不选」批量调整勾选；「回滚选中」先显示将执行的项目数与命令预览，确认框默认「取消」。
- 回滚逐项执行，失败继续下一项；完成后弹出逐项结果表，并询问「是否重启设备」，默认「稍后」。
- 所有读取、对比和回滚命令通过异步 `QProcess` 执行，界面不等待。

## Windows 权限与低完整性目录

如果出现以下现象，通常不是 ADB 或 scrcpy 本身的问题：

- `adb: cannot open C:\Users\<用户>\AppData\Local\Temp\adb.log: Permission denied`
- `* failed to start daemon`、`adb.exe: cannot connect to daemon`
- Python 写入 `%TEMP%` 时报 `PermissionError`
- 预览或视频线程报 `Connection refused` / `ConnectionResetError`

检查项目目录的完整性标签：

```powershell
icacls "H:\ADB_ tool" | Select-String "Mandatory Label"
```

如果显示 `Mandatory Label\Low Mandatory Level`，则从该目录启动的 `python.exe`、`adb.exe`、`scrcpy.exe` 会以低完整性运行，无法写入 `C:\Users\<用户>\AppData\Local\Temp` 等普通完整性目录，于是 ADB daemon 无法创建日志，scrcpy 连接随之中断。

本机采用不改动项目路径的修复：

- 将 `.venv`、`platform-tools`、`vendor/scrcpy` 复制到普通完整性的 `H:\adb-utils-runtime`。
- 将项目内这三个目录替换为指向副本的目录联接（Junction），启动脚本、配置和数据路径保持不变。
- 原目录保留为 `.venv.low`、`platform-tools.low`、`vendor/scrcpy.low` 备份。
- 不要删除 `H:\adb-utils-runtime`，否则 `.venv`、`platform-tools`、`vendor/scrcpy` 联接会失效；移动项目位置时需要重新建立联接。

永久修复需要管理员权限，执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\fix_permissions.ps1
```

脚本会把 `H:\ADB_ tool` 及 `adb-utils` 的完整性级别改为 Medium；如果存在 `G:\APKs`，还会给当前用户授予 Modify 权限。修复完成后目录联接仍可使用，也可以删除 `H:\adb-utils-runtime` 后恢复 `.low` 备份目录。

`G:\APKs` 当前只授予 `Everyone:(RX)`，普通用户无法写入；未运行上面的管理员脚本时，APK 导出会在写入测试阶段提示「目标目录不可写」，请改用项目内 `APKs` 或其他可写目录。

## 最短验证

1. 双击 `H:\ADB_ tool\启动 adb-utils.bat`，连接设备后点击「刷新设备」。
2. 点击左下角「设置」，确认预览刷新频率范围 1–60、单位与上限显示在输入框右侧；把频率改为 5 帧/秒并保存，确认侧边栏提示变为「每秒刷新 5 帧」。
3. 在「设置 → 路径与存储」选择新的默认保存位置并保存；打开「屏幕与按键」截图，确认默认路径位于该目录的 `screenshots` 下。
4. 打开「系统设置」，确认「隐藏状态栏图标」文字与复选框含义；字体倍率保持当前值点「应用字体」，确认框默认「取消」，执行后「本机最近修改」出现记录。
5. 打开「电池与电源」，确认电量、温度、电压、状态与原始输出；开始采样 5 秒后停止，确认样本数增加。
6. 打开「脚本」运行 `adb shell getprop ro.product.model`；再打开「终端」，默认 ADB 模式输入 `devices`，切换 Shell 模式输入 `echo 终端-ok`；按 Tab 看候选，试 Ctrl+A/Shift+Insert 和右键菜单。
7. 选中设备后确认「屏幕预览」约每秒刷新一次；点「打开独立窗口操作设备」，在手机控制窗口侧边栏试主页、返回、任务、音量和电源；关闭独立窗口后预览仍继续刷新。
8. 打开「运行日志」→「打开日志文件夹」，确认不再出现 `ShellExecute ... error 5`；关闭并重启软件，确认日志列表只显示新记录。

自动化验证只需一条命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 运行

推荐双击根目录 `启动 adb-utils.bat`。

也可以在 `adb-utils` 目录执行：

```powershell
.\.venv\Scripts\python.exe main.py
```

## 测试

在 `adb-utils` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 打包为 EXE

项目使用 PyInstaller 的 `onedir` 模式，输出是一个文件夹，不是单个 exe。这样 PySide6、Qt 插件、scrcpy 和 ADB 的启动速度更稳定，也方便替换 `adb.exe` / `scrcpy.exe`。

首次构建先安装构建依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

执行构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -Clean
```

需要同时生成 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -Clean -Zip
```

输出：

```text
dist\adb-utils\adb-utils.exe          # 双击运行
dist\adb-utils\_internal\             # Python、PySide6、wetest 等依赖
dist\adb-utils\_internal\vendor\      # scrcpy-server 与 scrcpy 运行时
dist\adb-utils\platform-tools\        # adb.exe、fastboot.exe
dist\adb-utils\config\                # 默认配置示例
dist\adb-utils\data\                  # 运行日志等可写数据
dist\adb-utils-<版本>.zip             # 使用 -Zip 时生成
```

发布时压缩整个 `dist\adb-utils` 文件夹，不能只发 `adb-utils.exe`；exe 离开 `_internal`、`platform-tools` 和 `vendor` 后无法启动。

### 后续更新重新编译

1. 修改 `adbtool\__init__.py` 中的 `__version__`。
2. 同步修改 `packaging\version_info.txt` 里的 `filevers`、`prodvers`、`FileVersion`、`ProductVersion`。
3. 重新执行：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -Clean -Zip
   ```
4. 升级用户时只替换程序文件，保留原来的 `config\settings.json` 和 `data\`；构建脚本不会把本机的 `config\settings.json` 或运行日志打进发布包。

如果新增了第三方 Python 包，把它加入 `requirements.txt`，并确认 PyInstaller 能自动发现；动态导入的模块需要在 `packaging\adb-utils.spec` 的 `hiddenimports` 中补充。如果新增 `.exe`、`.dll`、`.json` 等运行时文件，需要加入 spec 的 `datas`，或在 `scripts\build_exe.ps1` 中复制到输出目录。

当前保持 `console=False`，不会弹出命令行窗口；如果确实需要管理员权限，可在 spec 的 `EXE(...)` 中增加 `uac_admin=True`，但普通 ADB/scrcpy 使用不需要强制管理员权限。
