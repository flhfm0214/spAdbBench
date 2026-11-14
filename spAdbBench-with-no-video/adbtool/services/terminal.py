from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .adb import AdbService
from .completion_config import (
    PIPE_COMMANDS,
    PIPE_HELP,
    CompletionConfig,
    CompletionOption,
    completion_dir,
    ensure_completion_dir,
    load_completion_config,
)
from .fastboot import FASTBOOT_COMMANDS, FASTBOOT_HELP


ADB_COMMANDS = (
    "devices",
    "shell",
    "install",
    "install-multiple",
    "uninstall",
    "push",
    "pull",
    "logcat",
    "reboot",
    "root",
    "unroot",
    "remount",
    "disable-verity",
    "enable-verity",
    "forward",
    "reverse",
    "wait-for-device",
    "get-state",
    "get-serialno",
    "bugreport",
    "backup",
    "restore",
    "sideload",
    "tcpip",
    "connect",
    "disconnect",
    "pair",
    "keygen",
    "version",
    "help",
    "start-server",
    "kill-server",
    "reconnect",
    "features",
    "host-features",
    "attach",
    "detach",
)

_SHELL_COMMANDS = (
    "pm",
    "am",
    "dumpsys",
    "settings",
    "getprop",
    "setprop",
    "wm",
    "svc",
    "cmd",
    "input",
    "monkey",
    "screencap",
    "screenrecord",
    "content",
    "appops",
    "deviceidle",
    "top",
    "ps",
    "kill",
    "pidof",
    "ls",
    "cd",
    "pwd",
    "cat",
    "echo",
    "id",
    "whoami",
    "date",
    "df",
    "du",
    "find",
    "grep",
    "sed",
    "awk",
    "chmod",
    "chown",
    "mkdir",
    "rmdir",
    "rm",
    "mv",
    "cp",
    "ln",
    "mount",
    "umount",
    "reboot",
    "logcat",
    "ping",
    "netstat",
    "ifconfig",
    "ip",
    "uptime",
    "uname",
    "getevent",
    "service",
    "sh",
    "bash",
    "toybox",
    "which",
    "sleep",
)

SHELL_COMMANDS = _SHELL_COMMANDS + tuple(
    name for name in PIPE_COMMANDS if name not in _SHELL_COMMANDS
)

_ANSI_RE = re.compile(
    r"\x1B(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1B\\)|[@-Z\\-_])"
)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    syntax: str
    description: str
    layer: str


COMMAND_HELP = {
    ("ADB", "devices"): ("adb devices [-l]", "列出已连接设备"),
    ("ADB", "shell"): ("adb shell [命令]", "进入设备 shell 或执行单条命令"),
    ("ADB", "install"): ("adb install [-r] <APK>", "安装 APK"),
    ("ADB", "install-multiple"): ("adb install-multiple <APK...>", "拆分安装多个 APK"),
    ("ADB", "uninstall"): ("adb uninstall [-k] <包名>", "卸载应用"),
    ("ADB", "push"): ("adb push <本地路径> <远端路径>", "推送文件到设备"),
    ("ADB", "pull"): ("adb pull <远端路径> [本地路径]", "从设备拉取文件"),
    ("ADB", "logcat"): ("adb logcat [过滤选项]", "读取设备日志"),
    ("ADB", "reboot"): ("adb reboot [bootloader|recovery|edl]", "重启设备或进入指定模式"),
    ("ADB", "root"): ("adb root", "以 root 重启 adbd"),
    ("ADB", "unroot"): ("adb unroot", "恢复非 root adbd"),
    ("ADB", "remount"): ("adb remount", "重新挂载系统分区为可写"),
    ("ADB", "disable-verity"): ("adb disable-verity", "关闭 dm-verity"),
    ("ADB", "enable-verity"): ("adb enable-verity", "开启 dm-verity"),
    ("ADB", "forward"): ("adb forward tcp:<本地端口> tcp:<设备端口>", "建立端口转发"),
    ("ADB", "reverse"): ("adb reverse tcp:<设备端口> tcp:<本地端口>", "建立反向端口转发"),
    ("ADB", "wait-for-device"): ("adb wait-for-device", "等待设备上线"),
    ("ADB", "get-state"): ("adb get-state", "读取设备连接状态"),
    ("ADB", "get-serialno"): ("adb get-serialno", "读取设备序列号"),
    ("ADB", "bugreport"): ("adb bugreport [目录]", "生成完整错误报告"),
    ("ADB", "backup"): ("adb backup [-f <文件>] <包名>", "备份应用数据"),
    ("ADB", "restore"): ("adb restore <文件>", "恢复应用数据"),
    ("ADB", "sideload"): ("adb sideload <ZIP>", "通过 recovery 刷入更新包"),
    ("ADB", "tcpip"): ("adb tcpip <端口>", "切换设备到无线调试"),
    ("ADB", "connect"): ("adb connect <IP:端口>", "连接无线设备"),
    ("ADB", "disconnect"): ("adb disconnect [IP:端口]", "断开无线设备"),
    ("ADB", "pair"): ("adb pair <IP:端口> [配对码]", "配对无线调试"),
    ("ADB", "keygen"): ("adb keygen <文件>", "生成 ADB 密钥"),
    ("ADB", "version"): ("adb version", "显示 ADB 版本"),
    ("ADB", "help"): ("adb help", "显示 ADB 帮助"),
    ("ADB", "start-server"): ("adb start-server", "启动 ADB 服务"),
    ("ADB", "kill-server"): ("adb kill-server", "停止 ADB 服务"),
    ("ADB", "reconnect"): ("adb reconnect [device|offline]", "重连设备"),
    ("ADB", "features"): ("adb features", "列出设备支持的特性"),
    ("ADB", "host-features"): ("adb host-features", "列出主机支持的特性"),
    ("ADB", "attach"): ("adb attach", "附加到已连接的模拟器"),
    ("ADB", "detach"): ("adb detach", "从模拟器分离"),
    ("shell", "pm"): ("pm <list|install|uninstall|enable|disable-user|clear|path> ...", "包管理"),
    ("shell", "am"): ("am <start|force-stop|broadcast|kill> ...", "活动与服务管理"),
    ("shell", "dumpsys"): ("dumpsys <服务名> [参数]", "读取系统服务状态"),
    ("shell", "settings"): ("settings <get|put|list> <命名空间> [键] [值]", "读写系统设置"),
    ("shell", "getprop"): ("getprop [属性名]", "读取系统属性"),
    ("shell", "setprop"): ("setprop <属性名> <值>", "设置系统属性"),
    ("shell", "wm"): ("wm <size|density> [宽x高|DPI]", "修改分辨率或 DPI"),
    ("shell", "svc"): ("svc <power|data|wifi> <on|off>", "切换电源、数据或 Wi-Fi"),
    ("shell", "cmd"): ("cmd <服务> [参数]", "调用系统命令服务"),
    ("shell", "input"): ("input <text|keyevent|tap|swipe> ...", "注入按键、文本或触控"),
    ("shell", "monkey"): ("monkey -p <包名> <事件数>", "向应用发送随机事件"),
    ("shell", "screencap"): ("screencap -p <文件>", "截取设备屏幕"),
    ("shell", "screenrecord"): ("screenrecord <文件>", "录制设备屏幕"),
    ("shell", "content"): ("content <query|insert|update|delete> ...", "访问内容提供器"),
    ("shell", "appops"): ("appops <get|set> <包名> <权限> [模式]", "管理应用权限"),
    ("shell", "deviceidle"): ("deviceidle <force-idle|unforce>", "控制 Doze 状态"),
    ("shell", "top"): ("top [-n 次数] [-d 秒]", "查看进程资源占用"),
    ("shell", "ps"): ("ps [-A] [过滤]", "列出进程"),
    ("shell", "kill"): ("kill [-9] <PID>", "终止进程"),
    ("shell", "pidof"): ("pidof <进程名>", "按名称查找进程号"),
    ("shell", "ls"): ("ls [-l] [路径]", "列出目录"),
    ("shell", "cd"): ("cd <目录>", "切换目录"),
    ("shell", "pwd"): ("pwd", "显示当前目录"),
    ("shell", "cat"): ("cat <文件>", "输出文件内容"),
    ("shell", "echo"): ("echo <文本>", "输出文本"),
    ("shell", "id"): ("id", "显示当前用户与组"),
    ("shell", "whoami"): ("whoami", "显示当前用户名"),
    ("shell", "date"): ("date [格式]", "显示或设置时间"),
    ("shell", "df"): ("df [-h]", "查看磁盘空间"),
    ("shell", "du"): ("du [-h] [路径]", "统计目录占用"),
    ("shell", "find"): ("find <路径> [-name <模式>]", "查找文件"),
    ("shell", "grep"): ("grep <模式> [文件]", "文本过滤"),
    ("shell", "sed"): ("sed <表达式> [文件]", "流式文本编辑"),
    ("shell", "awk"): ("awk <表达式> [文件]", "文本字段处理"),
    ("shell", "chmod"): ("chmod <模式> <文件>", "修改权限"),
    ("shell", "chown"): ("chown <用户:组> <文件>", "修改所有者"),
    ("shell", "mkdir"): ("mkdir [-p] <目录>", "创建目录"),
    ("shell", "rmdir"): ("rmdir <目录>", "删除空目录"),
    ("shell", "rm"): ("rm [-rf] <路径>", "删除文件或目录"),
    ("shell", "mv"): ("mv <源> <目标>", "移动或重命名"),
    ("shell", "cp"): ("cp [-r] <源> <目标>", "复制文件或目录"),
    ("shell", "ln"): ("ln -s <目标> <链接>", "创建链接"),
    ("shell", "mount"): ("mount [选项] <设备> <挂载点>", "挂载文件系统"),
    ("shell", "umount"): ("umount <挂载点>", "卸载文件系统"),
    ("shell", "reboot"): ("reboot [bootloader|recovery]", "重启设备"),
    ("shell", "logcat"): ("logcat [过滤选项]", "读取设备日志"),
    ("shell", "ping"): ("ping [-c 次数] <地址>", "测试网络连通性"),
    ("shell", "netstat"): ("netstat [-an]", "查看网络连接"),
    ("shell", "ifconfig"): ("ifconfig [接口] [参数]", "查看或配置网络接口"),
    ("shell", "ip"): ("ip <addr|route|link> ...", "查看或配置 IP"),
    ("shell", "uptime"): ("uptime", "显示运行时间与负载"),
    ("shell", "uname"): ("uname [-a]", "显示内核信息"),
    ("shell", "getevent"): ("getevent [-lt]", "读取输入事件"),
    ("shell", "service"): ("service <list|call> ...", "调用系统服务"),
    ("shell", "sh"): ("sh [脚本]", "执行 shell"),
    ("shell", "bash"): ("bash [脚本]", "执行 bash"),
    ("shell", "toybox"): ("toybox [命令]", "调用 toybox 工具集"),
    ("shell", "which"): ("which <命令>", "查找命令路径"),
    ("shell", "sleep"): ("sleep <秒>", "延时指定秒数"),
}

for _pipe_name, (_pipe_syntax, _pipe_description) in PIPE_HELP.items():
    COMMAND_HELP.setdefault(
        ("shell", _pipe_name),
        (_pipe_syntax, _pipe_description),
    )


def command_specs() -> list[CommandSpec]:
    specs: list[CommandSpec] = []
    groups = (
        ("shell", SHELL_COMMANDS, COMMAND_HELP),
        ("ADB", ADB_COMMANDS, COMMAND_HELP),
        ("Fastboot", FASTBOOT_COMMANDS, FASTBOOT_HELP),
    )
    for layer, names, help_map in groups:
        for name in names:
            default_syntax = (
                f"adb {name} [参数]"
                if layer == "ADB"
                else f"fastboot {name} [参数]"
                if layer == "Fastboot"
                else f"{name} [参数]"
            )
            default_description = (
                "ADB 子命令"
                if layer == "ADB"
                else "fastboot 子命令"
                if layer == "Fastboot"
                else "设备 shell 命令"
            )
            syntax, description = help_map.get(
                (layer, name), (default_syntax, default_description)
            )
            specs.append(CommandSpec(name, syntax, description, layer))
    return specs


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "").replace("\r\n", "\n")


def split_adb_command(command: str) -> list[str]:
    lexer = shlex.shlex(command or "", posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens: list[str] = []
    for token in lexer:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            token = token[1:-1]
        if token:
            tokens.append(token)
    return tokens


class CompletionCatalog:
    def __init__(
        self,
        config_root: Path | str | None = None,
        packages: list[str] | None = None,
    ) -> None:
        self._config_root = Path(config_root) if config_root is not None else None
        self._config_dir = (
            completion_dir(self._config_root)
            if self._config_root is not None
            else None
        )
        self._config = CompletionConfig.defaults()
        self._config_signature: tuple | None = None
        self.last_error = ""
        self._packages: list[str] = []
        self.set_packages(packages or [])
        if self._config_root is not None:
            try:
                ensure_completion_dir(self._config_root)
                self.reload()
            except OSError as exc:
                self.last_error = str(exc)

    @staticmethod
    def static_adb_commands() -> list[str]:
        return list(ADB_COMMANDS)

    @staticmethod
    def static_shell_commands() -> list[str]:
        return list(SHELL_COMMANDS)

    @staticmethod
    def static_fastboot_commands() -> list[str]:
        return list(FASTBOOT_COMMANDS)

    def shell_commands(self) -> list[str]:
        return list(SHELL_COMMANDS)

    @staticmethod
    def pipe_commands() -> list[str]:
        return list(PIPE_COMMANDS)

    @property
    def packages(self) -> list[str]:
        return list(self._packages)

    def set_packages(self, packages: list[str]) -> None:
        cleaned = {
            str(package).strip()
            for package in packages
            if str(package).strip()
        }
        self._packages = sorted(cleaned)

    def reload(self) -> None:
        if self._config_dir is None:
            return
        try:
            signature = tuple(
                (path.name, path.stat().st_mtime_ns, path.stat().st_size)
                for path in sorted(self._config_dir.glob("*"))
                if path.is_file()
            )
        except OSError as exc:
            self.last_error = str(exc)
            return
        if signature == self._config_signature:
            return
        config = load_completion_config(self._config_root)
        self._config = config
        self._config_signature = signature
        self.last_error = "；".join(config.errors)

    def complete_command(
        self,
        command: str,
        path: tuple[str, ...],
        prefix: str,
    ) -> list[CompletionOption]:
        self.reload()
        command = command.strip()
        if not command:
            return []
        options = self._config.subcommands_at(command, path, prefix)
        if options:
            return options
        values = self._config.values_at(command, path, prefix)
        if values:
            return values
        if self._config.is_package_path(command, path):
            return [
                CompletionOption(
                    name=package,
                    path=path + (package,),
                    syntax="",
                    description="",
                )
                for package in self._packages
                if package.startswith(prefix)
            ]
        return []

    def candidates(self, prefix: str) -> list[str]:
        prefix = (prefix or "").lstrip()
        result: list[str] = []
        for command in ADB_COMMANDS + tuple(self.shell_commands()):
            if command.startswith(prefix) and command not in result:
                result.append(command)
        for package in self._packages:
            if package.startswith(prefix) and package not in result:
                result.append(package)
        return result


class AdbCommandSession(QObject):
    output = Signal(str)
    state = Signal(str)
    error = Signal(str)
    finished = Signal(object)

    def __init__(self, adb: AdbService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self._serial = ""
        self._process = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.is_running

    @property
    def serial(self) -> str:
        return self._serial

    def start(self, serial: str, command: str) -> None:
        self.stop()
        serial = (serial or "").strip()
        if not serial:
            self.error.emit("未选择设备")
            return
        args = split_adb_command(command)
        if args and args[0].lower() == "adb":
            args = args[1:]
        cleaned: list[str] = []
        index = 0
        while index < len(args):
            if args[index] in {"-s", "--serial"} and index + 1 < len(args):
                index += 2
                continue
            if args[index] in {"-d", "-e"}:
                index += 1
                continue
            cleaned.append(args[index])
            index += 1
        if not cleaned:
            self.error.emit("请输入 ADB 命令")
            return
        self._serial = serial
        process = self.adb.run_argv(
            self.adb.build(serial, *cleaned),
            timeout_ms=0,
        )
        self._process = process
        process.output.connect(self.output.emit)
        process.error_output.connect(self.output.emit)
        process.finished.connect(
            lambda result, p=process: self._on_finished(p, result)
        )
        self.state.emit("执行中…")

    def stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.is_running:
            self.state.emit("正在停止…")
            process.cancel()

    def interrupt(self) -> None:
        self.stop()

    def wait(self, timeout_ms: int = 1500) -> None:
        if self._process is not None:
            self._process.wait(timeout_ms)

    def _on_finished(self, process, result) -> None:
        if process is not self._process:
            return
        self._process = None
        self.finished.emit(result)
        if result.cancelled:
            self.state.emit("已停止")
        elif result.ok:
            self.state.emit("已完成")
        else:
            self.state.emit(f"执行失败（退出码 {result.exit_code}）")


class TerminalSession(QObject):
    output = Signal(str)
    state = Signal(str)
    error = Signal(str)

    def __init__(self, adb: AdbService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self._serial = ""
        self._process: QProcess | None = None
        self._kill_timer: QTimer | None = None
        self._stopping = False
        self._failed = False

    @property
    def running(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    @property
    def serial(self) -> str:
        return self._serial

    def _build_argv(self, serial: str) -> list[str]:
        return [str(self.adb.adb_path), "-s", serial, "shell"]

    def start(self, serial: str) -> None:
        self.stop()
        serial = (serial or "").strip()
        if not serial:
            self.error.emit("未选择设备")
            self.state.emit("未连接")
            return
        self._serial = serial
        self._stopping = False
        self._failed = False
        argv = self._build_argv(serial)
        process = QProcess(self)
        process.setProgram(argv[0])
        process.setArguments(argv[1:])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda p=process: self._read_output(p)
        )
        process.started.connect(lambda p=process: self._on_started(p))
        process.finished.connect(
            lambda code, status, p=process: self._on_finished(p, code, status)
        )
        process.errorOccurred.connect(
            lambda error, p=process: self._on_error(p, error)
        )
        self._process = process
        self.state.emit("正在连接…")
        process.start()

    def stop(self) -> None:
        process = self._process
        self._serial = ""
        self._stopping = True
        if process is None:
            return
        if process.state() == QProcess.ProcessState.NotRunning:
            self._finish_stop(process)
            return
        self.state.emit("正在停止…")
        process.terminate()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(800)
        timer.timeout.connect(lambda p=process: self._kill_if_running(p))
        self._kill_timer = timer
        timer.start()

    def wait(self, timeout_ms: int = 1500) -> None:
        """Finish a stopped process during window shutdown only."""
        process = self._process
        if process is None:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.waitForFinished(timeout_ms)
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(500)
        if process is self._process:
            self._on_finished(process, -1, QProcess.ExitStatus.CrashExit)

    def send(self, text: str) -> None:
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            self.error.emit("终端未连接")
            return
        process.write(f"{text}\n".encode("utf-8"))

    def interrupt(self) -> None:
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            self.error.emit("终端未连接")
            return
        process.write(b"\x03")

    def _read_output(self, process: QProcess) -> None:
        if process is not self._process or self._stopping:
            return
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        if chunk:
            clean = strip_ansi(chunk)
            if clean:
                self.output.emit(clean)

    def _on_started(self, process: QProcess) -> None:
        if process is not self._process:
            return
        self.state.emit("已连接")

    def _on_error(self, process: QProcess, error: QProcess.ProcessError) -> None:
        if process is not self._process:
            return
        if error != QProcess.ProcessError.FailedToStart:
            return
        self._failed = True
        self.error.emit(f"终端启动失败：{process.errorString()}")
        self.state.emit("连接失败")

    def _on_finished(
        self,
        process: QProcess,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if process is not self._process:
            process.deleteLater()
            return
        self._read_output(process)
        self._process = None
        self._serial = ""
        self._stop_kill_timer()
        if self._failed:
            self.state.emit("连接失败")
        elif self._stopping:
            self.state.emit("已停止")
        else:
            self.state.emit("已断开")
        process.deleteLater()

    def _finish_stop(self, process: QProcess) -> None:
        if process is not self._process:
            return
        self._process = None
        self._stop_kill_timer()
        self._stopping = False
        self.state.emit("已停止")
        process.deleteLater()

    def _kill_if_running(self, process: QProcess) -> None:
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()

    def _stop_kill_timer(self) -> None:
        if self._kill_timer is not None:
            self._kill_timer.stop()
            self._kill_timer.deleteLater()
            self._kill_timer = None
