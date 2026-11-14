from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CompletionOption:
    name: str
    path: tuple[str, ...]
    syntax: str
    description: str


@dataclass
class CommandCompletion:
    name: str
    description: str = ""
    subcommands: list[CompletionOption] = field(default_factory=list)
    options: list[CompletionOption] = field(default_factory=list)
    package_paths: set[tuple[str, ...]] = field(default_factory=set)
    values: dict[tuple[str, ...], list[str]] = field(default_factory=dict)


@dataclass
class CompletionConfig:
    commands: dict[str, CommandCompletion] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @classmethod
    def defaults(cls) -> "CompletionConfig":
        return cls(_normalise_commands(_DEFAULT_COMMANDS))

    def command_names(self) -> list[str]:
        return sorted(self.commands)

    def subcommands_at(
        self,
        command: str,
        path: tuple[str, ...],
        prefix: str,
    ) -> list[CompletionOption]:
        item = self.commands.get(command)
        if item is None:
            return []
        result: list[CompletionOption] = []
        seen: set[str] = set()
        for option in item.subcommands:
            if option.path[: len(path)] != path or len(option.path) <= len(path):
                continue
            name = option.path[len(path)]
            if not name.startswith(prefix) or name in seen:
                continue
            seen.add(name)
            result.append(
                CompletionOption(
                    name=name,
                    path=option.path,
                    syntax=option.syntax,
                    description=option.description,
                )
            )
        if prefix.startswith("-"):
            for option in item.options:
                if option.name.startswith(prefix) and option.name not in seen:
                    seen.add(option.name)
                    result.append(option)
        elif not result and not path:
            # Commands without subcommands still benefit from showing flags
            # after "command ".
            result.extend(item.options)
        return result

    def values_at(
        self,
        command: str,
        path: tuple[str, ...],
        prefix: str,
    ) -> list[CompletionOption]:
        item = self.commands.get(command)
        if item is None:
            return []
        values = item.values.get(path, [])
        return [
            CompletionOption(
                name=value,
                path=path + (value,),
                syntax=" ".join((command, *path, value)),
                description="",
            )
            for value in values
            if value.startswith(prefix)
        ]

    def is_package_path(self, command: str, path: tuple[str, ...]) -> bool:
        item = self.commands.get(command)
        return item is not None and path in item.package_paths

    def options_for(
        self,
        command: str,
        path: tuple[str, ...],
        prefix: str,
    ) -> list[CompletionOption]:
        item = self.commands.get(command)
        if item is None:
            return []
        if prefix.startswith("-"):
            return [
                option
                for option in item.options
                if option.name.startswith(prefix)
            ]
        return []


def completion_dir(root: Path | str) -> Path:
    return Path(root) / "config" / "completions"


def ensure_completion_dir(root: Path | str) -> Path:
    target = completion_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    data_file = target / "commands.json"
    if not data_file.exists():
        data_file.write_text(
            json.dumps(
                {"version": 1, "commands": _DEFAULT_COMMANDS},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        _merge_missing_defaults(data_file)
    readme = target / "README.txt"
    if not readme.exists():
        readme.write_text(_README, encoding="utf-8")
    return target


def _merge_missing_defaults(data_file: Path) -> None:
    """Add newly shipped commands without touching user-edited entries."""
    try:
        raw = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    commands = raw.get("commands")
    if not isinstance(commands, dict):
        return
    changed = False
    for name, payload in _DEFAULT_COMMANDS.items():
        if name not in commands:
            commands[name] = payload
            changed = True
    if not changed:
        return
    try:
        data_file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def load_completion_config(root: Path | str) -> CompletionConfig:
    target = completion_dir(root)
    config = CompletionConfig.defaults()
    if not target.is_dir():
        return config
    for path in sorted(target.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            config.errors.append(f"{path.name}: {exc}")
            continue
        if not isinstance(raw, dict):
            config.errors.append(f"{path.name}: 顶层必须是 JSON 对象")
            continue
        if isinstance(raw.get("commands"), dict):
            entries = raw["commands"]
        elif raw.get("command"):
            entries = {str(raw["command"]): raw}
        else:
            entries = raw
        if not isinstance(entries, dict):
            config.errors.append(f"{path.name}: commands 必须是对象")
            continue
        normalised = _normalise_commands(entries)
        config.commands.update(normalised)
    return config


def _normalise_commands(raw: dict) -> dict[str, CommandCompletion]:
    commands: dict[str, CommandCompletion] = {}
    if not isinstance(raw, dict):
        return commands
    for name, payload in raw.items():
        command = str(name).strip()
        if not command:
            continue
        commands[command] = _normalise_command(command, payload)
    return commands


def _normalise_command(name: str, payload) -> CommandCompletion:
    if not isinstance(payload, dict):
        payload = {}
    subcommands = _normalise_options(
        name,
        payload.get("subcommands", []),
        option=False,
    )
    options = _normalise_options(
        name,
        payload.get("options", []),
        option=True,
    )
    package_paths = {
        tuple(str(item).split())
        for item in payload.get("package_arguments", [])
        if str(item).strip()
    }
    values: dict[tuple[str, ...], list[str]] = {}
    raw_values = payload.get("value_arguments", {})
    if isinstance(raw_values, dict):
        for path, items in raw_values.items():
            if not isinstance(items, list):
                continue
            key = tuple(str(path).split())
            values[key] = [str(item) for item in items if str(item).strip()]
    return CommandCompletion(
        name=name,
        description=str(payload.get("description", "")),
        subcommands=subcommands,
        options=options,
        package_paths=package_paths,
        values=values,
    )


_PIPE_DEFINITIONS = {
    "grep": (
        "grep [选项] <模式> [文件]",
        "文本过滤",
        [
            ("-i", "忽略大小写"),
            ("-v", "反向匹配"),
            ("-n", "显示行号"),
            ("-r", "递归"),
            ("-E", "扩展正则"),
            ("-F", "固定字符串"),
            ("-w", "全词匹配"),
            ("-c", "只输出计数"),
            ("-l", "只输出文件名"),
        ],
    ),
    "sed": (
        "sed [选项] <表达式> [文件]",
        "流式文本编辑",
        [
            ("-n", "不自动输出模式空间"),
            ("-e", "追加编辑脚本"),
            ("-i", "原地修改文件"),
            ("-E", "扩展正则"),
            ("-r", "扩展正则"),
            ("-s", "分别处理每个文件"),
        ],
    ),
    "awk": (
        "awk [选项] <程序> [文件]",
        "按字段处理文本",
        [
            ("-F", "指定字段分隔符"),
            ("-v", "定义变量"),
            ("-f", "从文件读取程序"),
            ("-W", "兼容性选项"),
        ],
    ),
    "cut": (
        "cut [选项] [文件]",
        "按字段或字符截取文本",
        [
            ("-d", "字段分隔符"),
            ("-f", "字段列表"),
            ("-c", "字符列表"),
            ("-b", "字节列表"),
            ("-s", "跳过无分隔符行"),
            ("--complement", "输出补集"),
        ],
    ),
    "sort": (
        "sort [选项] [文件]",
        "对文本行排序",
        [
            ("-r", "逆序"),
            ("-n", "数值排序"),
            ("-u", "去除重复行"),
            ("-k", "指定排序字段"),
            ("-t", "指定字段分隔符"),
            ("-f", "忽略大小写"),
            ("-h", "人类可读数值"),
            ("-V", "版本号排序"),
            ("-o", "输出到文件"),
        ],
    ),
    "uniq": (
        "uniq [选项] [输入 [输出]]",
        "去除相邻重复行",
        [
            ("-c", "显示重复次数"),
            ("-d", "只显示重复行"),
            ("-u", "只显示唯一行"),
            ("-i", "忽略大小写"),
            ("-f", "跳过字段"),
            ("-s", "跳过字符"),
            ("-w", "比较字符数"),
        ],
    ),
    "tr": (
        "tr [选项] <集合1> [集合2]",
        "转换或删除字符",
        [
            ("-d", "删除字符"),
            ("-s", "压缩重复字符"),
            ("-c", "取字符补集"),
            ("-t", "截断集合1"),
        ],
    ),
    "tee": (
        "tee [选项] [文件...]",
        "同时写入文件和标准输出",
        [("-a", "追加写入"), ("-i", "忽略中断信号")],
    ),
    "head": (
        "head [选项] [文件...]",
        "输出文件开头部分",
        [
            ("-n", "输出行数"),
            ("-c", "输出字节数"),
            ("-q", "不显示文件名"),
            ("-v", "显示文件名"),
        ],
    ),
    "tail": (
        "tail [选项] [文件...]",
        "输出文件末尾部分",
        [
            ("-n", "输出行数"),
            ("-c", "输出字节数"),
            ("-f", "持续跟踪文件"),
            ("-F", "跟踪并重试"),
            ("-q", "不显示文件名"),
            ("-v", "显示文件名"),
        ],
    ),
    "wc": (
        "wc [选项] [文件...]",
        "统计行数、单词数和字节数",
        [
            ("-l", "行数"),
            ("-w", "单词数"),
            ("-c", "字节数"),
            ("-m", "字符数"),
            ("-L", "最长行长度"),
        ],
    ),
    "cat": (
        "cat [选项] [文件...]",
        "输出文件内容",
        [
            ("-n", "显示行号"),
            ("-b", "非空行编号"),
            ("-s", "压缩空行"),
            ("-v", "显示不可见字符"),
            ("-E", "行尾显示 $"),
            ("-T", "Tab 显示为 ^I"),
        ],
    ),
    "nl": (
        "nl [选项] [文件]",
        "为文本添加行号",
        [
            ("-b", "编号方式"),
            ("-n", "编号格式"),
            ("-s", "行号分隔符"),
            ("-w", "行号宽度"),
            ("-v", "起始编号"),
        ],
    ),
    "tac": ("tac [文件...]", "按行反向输出文件", []),
    "rev": ("rev [文件...]", "反转每一行的字符", []),
    "paste": (
        "paste [选项] [文件...]",
        "按列合并文件内容",
        [("-d", "列分隔符"), ("-s", "串行合并")],
    ),
    "join": (
        "join [选项] <文件1> <文件2>",
        "按字段连接两个文件",
        [
            ("-1", "文件1 的连接字段"),
            ("-2", "文件2 的连接字段"),
            ("-j", "两侧相同的连接字段"),
            ("-t", "字段分隔符"),
            ("-a", "输出未匹配行"),
            ("-v", "只输出未匹配行"),
            ("-o", "指定输出字段"),
        ],
    ),
    "comm": (
        "comm [选项] <文件1> <文件2>",
        "比较两个已排序文件",
        [
            ("-1", "隐藏文件1 独有列"),
            ("-2", "隐藏文件2 独有列"),
            ("-3", "隐藏共同列"),
            ("--check-order", "检查排序"),
            ("--nocheck-order", "不检查排序"),
        ],
    ),
    "od": (
        "od [选项] [文件...]",
        "以八进制或其他格式转储数据",
        [
            ("-A", "地址进制"),
            ("-t", "输出类型"),
            ("-N", "读取字节数"),
            ("-j", "跳过字节数"),
            ("-v", "不省略重复行"),
            ("-c", "按字符显示"),
        ],
    ),
    "hexdump": (
        "hexdump [选项] [文件...]",
        "十六进制转储",
        [
            ("-C", "规范十六进制格式"),
            ("-c", "按字符显示"),
            ("-n", "读取字节数"),
            ("-s", "跳过字节数"),
            ("-v", "不省略重复行"),
        ],
    ),
    "strings": (
        "strings [选项] [文件...]",
        "提取文件中的可打印字符串",
        [
            ("-a", "扫描整个文件"),
            ("-n", "最小字符串长度"),
            ("-t", "显示偏移"),
            ("-e", "指定字符编码"),
        ],
    ),
    "base64": (
        "base64 [选项] [文件]",
        "Base64 编码或解码",
        [("-d", "解码"), ("-w", "换行宽度")],
    ),
    "md5sum": (
        "md5sum [选项] [文件...]",
        "计算或校验 MD5",
        [("-b", "二进制模式"), ("-c", "校验文件"), ("-t", "文本模式")],
    ),
    "sha1sum": (
        "sha1sum [选项] [文件...]",
        "计算或校验 SHA-1",
        [("-b", "二进制模式"), ("-c", "校验文件"), ("-t", "文本模式")],
    ),
    "sha256sum": (
        "sha256sum [选项] [文件...]",
        "计算或校验 SHA-256",
        [("-b", "二进制模式"), ("-c", "校验文件"), ("-t", "文本模式")],
    ),
    "sha512sum": (
        "sha512sum [选项] [文件...]",
        "计算或校验 SHA-512",
        [("-b", "二进制模式"), ("-c", "校验文件"), ("-t", "文本模式")],
    ),
    "cksum": (
        "cksum [选项] [文件...]",
        "计算 CRC 校验和",
        [("--algorithm", "指定算法"), ("--untagged", "仅输出校验值")],
    ),
    "sum": (
        "sum [选项] [文件...]",
        "计算 BSD 或 System V 校验和",
        [("-s", "System V 算法"), ("-r", "BSD 算法")],
    ),
    "fold": (
        "fold [选项] [文件...]",
        "按指定宽度折行",
        [("-w", "行宽"), ("-s", "在空格处折行"), ("-b", "按字节计数")],
    ),
    "fmt": (
        "fmt [选项] [文件...]",
        "重新格式化文本段落",
        [("-w", "行宽"), ("-s", "只拆分长行"), ("-u", "统一空格")],
    ),
    "pr": (
        "pr [选项] [文件...]",
        "分页格式化文本",
        [("-t", "省略页眉页脚"), ("-n", "显示行号"), ("-w", "页面宽度"), ("-h", "页眉标题")],
    ),
    "column": (
        "column [选项] [文件...]",
        "将文本格式化为列",
        [("-t", "自动对齐表格"), ("-s", "字段分隔符"), ("-c", "输出宽度"), ("-x", "先填满行")],
    ),
    "expand": (
        "expand [选项] [文件...]",
        "把 Tab 转换为空格",
        [("-t", "Tab 宽度"), ("-i", "只转换行首 Tab")],
    ),
    "unexpand": (
        "unexpand [选项] [文件...]",
        "把空格转换为 Tab",
        [("-a", "转换所有空格"), ("-t", "Tab 宽度")],
    ),
    "split": (
        "split [选项] [文件 [前缀]]",
        "拆分文件",
        [
            ("-b", "按字节大小拆分"),
            ("-l", "按行数拆分"),
            ("-n", "拆分为指定块数"),
            ("-d", "使用数字后缀"),
            ("-a", "后缀长度"),
        ],
    ),
    "csplit": (
        "csplit [选项] <文件> <模式...>",
        "按模式拆分文件",
        [("-f", "输出前缀"), ("-b", "后缀格式"), ("-n", "后缀位数"), ("-k", "保留输出文件")],
    ),
    "shuf": (
        "shuf [选项] [文件]",
        "随机排列输入行",
        [
            ("-n", "输出行数"),
            ("-e", "把参数作为输入行"),
            ("-i", "使用数字范围"),
            ("-r", "允许重复"),
            ("-z", "NUL 分隔"),
        ],
    ),
    "tsort": ("tsort [文件]", "拓扑排序", []),
    "diff": (
        "diff [选项] <文件1> <文件2>",
        "比较文件差异",
        [
            ("-u", "统一格式"),
            ("-c", "上下文格式"),
            ("-r", "递归比较目录"),
            ("-i", "忽略大小写"),
            ("-w", "忽略空白"),
            ("-q", "只报告是否不同"),
            ("-N", "把缺失文件视为空"),
        ],
    ),
    "cmp": (
        "cmp [选项] <文件1> <文件2>",
        "逐字节比较文件",
        [("-l", "列出所有差异"), ("-s", "静默模式"), ("-b", "显示不同字节")],
    ),
    "patch": (
        "patch [选项] [文件]",
        "应用补丁",
        [("-p", "剥离路径层级"), ("-R", "反向应用"), ("-i", "补丁文件"), ("-N", "跳过已应用补丁"), ("-b", "备份原文件")],
    ),
    "zcat": ("zcat [文件...]", "查看 gzip 压缩文件", [("-f", "强制读取")]),
    "bzcat": ("bzcat [文件...]", "查看 bzip2 压缩文件", [("-f", "强制读取")]),
    "xzcat": ("xzcat [文件...]", "查看 xz 压缩文件", [("-f", "强制读取")]),
    "gzip": (
        "gzip [选项] [文件...]",
        "gzip 压缩或解压",
        [
            ("-d", "解压"),
            ("-k", "保留原文件"),
            ("-c", "输出到标准输出"),
            ("-f", "强制覆盖"),
            ("-r", "递归处理"),
            ("-9", "最大压缩"),
        ],
    ),
    "gunzip": (
        "gunzip [选项] [文件...]",
        "解压 gzip 文件",
        [("-k", "保留原文件"), ("-c", "输出到标准输出"), ("-f", "强制解压"), ("-r", "递归处理")],
    ),
    "bzip2": (
        "bzip2 [选项] [文件...]",
        "bzip2 压缩或解压",
        [("-d", "解压"), ("-k", "保留原文件"), ("-c", "输出到标准输出"), ("-f", "强制覆盖"), ("-9", "最大压缩")],
    ),
    "bunzip2": (
        "bunzip2 [选项] [文件...]",
        "解压 bzip2 文件",
        [("-k", "保留原文件"), ("-c", "输出到标准输出"), ("-f", "强制解压")],
    ),
    "xz": (
        "xz [选项] [文件...]",
        "xz 压缩或解压",
        [("-d", "解压"), ("-k", "保留原文件"), ("-c", "输出到标准输出"), ("-f", "强制覆盖"), ("-9", "最大压缩"), ("-T", "线程数")],
    ),
    "unxz": (
        "unxz [选项] [文件...]",
        "解压 xz 文件",
        [("-k", "保留原文件"), ("-c", "输出到标准输出"), ("-f", "强制解压")],
    ),
    "zip": (
        "zip [选项] <压缩包> <文件...>",
        "创建 zip 压缩包",
        [("-r", "递归目录"), ("-q", "静默"), ("-9", "最大压缩"), ("-e", "加密"), ("-d", "从压缩包删除")],
    ),
    "unzip": (
        "unzip [选项] <压缩包> [文件...]",
        "解压 zip 压缩包",
        [("-l", "列出内容"), ("-o", "覆盖已有文件"), ("-q", "静默"), ("-d", "解压目录"), ("-p", "输出到标准输出"), ("-t", "测试压缩包")],
    ),
    "tar": (
        "tar [选项] [文件...]",
        "创建或解包 tar 归档",
        [
            ("-c", "创建归档"),
            ("-x", "解包归档"),
            ("-t", "列出归档内容"),
            ("-z", "gzip 压缩"),
            ("-j", "bzip2 压缩"),
            ("-J", "xz 压缩"),
            ("-f", "指定归档文件"),
            ("-v", "显示处理过程"),
            ("-C", "切换目录"),
        ],
    ),
    "less": (
        "less [选项] [文件]",
        "分页查看文本",
        [("-N", "显示行号"), ("-S", "长行不折行"), ("-R", "显示颜色"), ("-i", "搜索忽略大小写"), ("-F", "内容短时直接退出"), ("-X", "退出时不清屏")],
    ),
    "more": (
        "more [选项] [文件]",
        "分页查看文本",
        [("-d", "显示提示"), ("-s", "压缩空行"), ("-n", "每屏行数")],
    ),
    "basename": (
        "basename [选项] <路径> [后缀]",
        "取路径的文件名部分",
        [("-a", "处理多个路径"), ("-s", "去除后缀"), ("-z", "NUL 分隔")],
    ),
    "dirname": (
        "dirname [选项] <路径...>",
        "取路径的目录部分",
        [("-z", "NUL 分隔")],
    ),
    "readlink": (
        "readlink [选项] <路径...>",
        "读取符号链接目标",
        [("-f", "递归解析"), ("-e", "目标必须存在"), ("-m", "允许缺失"), ("-n", "不输出换行")],
    ),
    "realpath": (
        "realpath [选项] <路径...>",
        "输出规范绝对路径",
        [("-e", "路径必须存在"), ("-m", "允许缺失"), ("-s", "不解析符号链接"), ("-z", "NUL 分隔")],
    ),
    "stat": (
        "stat [选项] <文件...>",
        "显示文件状态",
        [("-c", "自定义格式"), ("-f", "显示文件系统状态"), ("-L", "跟随符号链接"), ("-t", "简洁格式")],
    ),
    "file": (
        "file [选项] <文件...>",
        "识别文件类型",
        [("-b", "不显示文件名"), ("-i", "显示 MIME 类型"), ("-L", "跟随符号链接"), ("-s", "读取特殊文件")],
    ),
    "mktemp": (
        "mktemp [选项] [模板]",
        "创建临时文件或目录",
        [("-d", "创建目录"), ("-p", "指定父目录"), ("-t", "使用临时目录"), ("-u", "只生成名称")],
    ),
    "touch": (
        "touch [选项] <文件...>",
        "创建文件或更新时间戳",
        [("-a", "只改访问时间"), ("-m", "只改修改时间"), ("-c", "文件不存在时不创建"), ("-t", "指定时间"), ("-d", "日期字符串")],
    ),
    "unlink": ("unlink <文件>", "删除单个文件", []),
    "dos2unix": (
        "dos2unix [选项] [文件...]",
        "转换 CRLF 为 LF",
        [("-k", "保留时间戳"), ("-n", "写入新文件"), ("-q", "静默")],
    ),
    "unix2dos": (
        "unix2dos [选项] [文件...]",
        "转换 LF 为 CRLF",
        [("-k", "保留时间戳"), ("-n", "写入新文件"), ("-q", "静默")],
    ),
    "printf": (
        "printf <格式> [参数...]",
        "按格式输出文本",
        [("--help", "显示帮助"), ("--version", "显示版本")],
    ),
    "seq": (
        "seq [选项] [首数] [步长] <末数>",
        "生成数字序列",
        [("-s", "分隔符"), ("-f", "浮点格式"), ("-w", "等宽补零")],
    ),
    "expr": (
        "expr <表达式>",
        "计算表达式或处理字符串",
        [],
    ),
    "xargs": (
        "xargs [选项] [命令 [参数...]]",
        "从标准输入构造并执行命令",
        [
            ("-0", "NUL 分隔输入"),
            ("-n", "每次传入参数数"),
            ("-I", "替换字符串"),
            ("-d", "输入分隔符"),
            ("-r", "无输入时不执行"),
            ("-t", "执行前显示命令"),
            ("-P", "并行进程数"),
        ],
    ),
    "dd": (
        "dd [操作数...]",
        "按块复制并转换数据",
        [
            ("if=", "输入文件"),
            ("of=", "输出文件"),
            ("bs=", "块大小"),
            ("count=", "复制块数"),
            ("skip=", "跳过输入块"),
            ("seek=", "跳过输出块"),
            ("status=", "显示进度"),
            ("conv=", "转换选项"),
        ],
    ),
    "find": (
        "find [路径...] [表达式]",
        "查找文件",
        [
            ("-name", "按名称匹配"),
            ("-iname", "忽略大小写匹配"),
            ("-type", "按类型匹配"),
            ("-maxdepth", "最大深度"),
            ("-mindepth", "最小深度"),
            ("-size", "按大小匹配"),
            ("-mtime", "按修改时间匹配"),
            ("-exec", "执行命令"),
            ("-print", "输出路径"),
            ("-delete", "删除匹配项"),
        ],
    ),
}

_PIPE_PRIORITY = (
    "grep",
    "awk",
    "sed",
    "cut",
    "sort",
    "uniq",
    "tr",
    "tee",
    "head",
    "tail",
    "wc",
    "xargs",
    "cat",
    "nl",
    "tac",
    "rev",
    "paste",
    "join",
    "comm",
    "od",
)

PIPE_COMMANDS = _PIPE_PRIORITY + tuple(
    name for name in _PIPE_DEFINITIONS if name not in _PIPE_PRIORITY
)
PIPE_HELP = {
    name: (definition[0], definition[1])
    for name, definition in _PIPE_DEFINITIONS.items()
}


def _normalise_options(
    command: str,
    raw,
    *,
    option: bool,
) -> list[CompletionOption]:
    if not isinstance(raw, list):
        return []
    result: list[CompletionOption] = []
    seen: set[tuple[str, ...]] = set()
    for entry in raw:
        path: tuple[str, ...] = ()
        description = ""
        syntax = ""
        if isinstance(entry, str):
            path = tuple(entry.split())
        elif isinstance(entry, (list, tuple)):
            if not entry:
                continue
            path = tuple(str(entry[0]).split())
            if len(entry) > 1:
                description = str(entry[1])
            if len(entry) > 2:
                syntax = str(entry[2])
        elif isinstance(entry, dict):
            value = entry.get("path", entry.get("name", ""))
            if isinstance(value, list):
                path = tuple(str(part) for part in value if str(part).strip())
            else:
                path = tuple(str(value).split())
            description = str(entry.get("description", ""))
            syntax = str(entry.get("syntax", ""))
        if not path or path in seen:
            continue
        seen.add(path)
        if not syntax:
            syntax = " ".join((command, *path))
        result.append(
            CompletionOption(
                name=path[-1],
                path=path,
                syntax=syntax,
                description=description or ("选项" if option else "子命令"),
            )
        )
    return result


_DEFAULT_COMMANDS = {
    "pm": {
        "description": "包管理",
        "subcommands": [
            ("help", "显示 pm 帮助"),
            ("list", "列出包、权限、特性等"),
            ("list packages", "列出包名"),
            ("list permission-groups", "列出权限组"),
            ("list permissions", "列出权限"),
            ("list features", "列出系统特性"),
            ("list libraries", "列出共享库"),
            ("list users", "列出用户"),
            ("path", "显示应用 APK 路径"),
            ("install", "安装 APK"),
            ("install-existing", "为现有用户安装"),
            ("uninstall", "卸载应用"),
            ("clear", "清除应用数据"),
            ("enable", "启用应用"),
            ("disable", "禁用应用"),
            ("disable-user", "禁用用户应用"),
            ("enable-user", "启用用户应用"),
            ("hide", "隐藏应用"),
            ("unhide", "取消隐藏应用"),
            ("suspend", "暂停应用"),
            ("unsuspend", "恢复应用"),
            ("grant", "授予运行时权限"),
            ("revoke", "撤销运行时权限"),
            ("dump", "输出应用信息"),
            ("get-app-links", "读取应用链接"),
            ("set-app-links", "设置应用链接"),
            ("reset-app-links", "重置应用链接"),
            ("get-install-location", "读取安装位置"),
            ("set-install-location", "设置安装位置"),
            ("create-user", "创建用户"),
            ("remove-user", "删除用户"),
            ("get-max-users", "显示最大用户数"),
            ("trim-caches", "清理缓存"),
            ("compile", "编译应用"),
        ],
        "options": [
            ("--user", "指定用户 ID"),
            ("-d", "仅显示已禁用包"),
            ("-e", "仅显示已启用包"),
            ("-s", "仅显示系统包"),
            ("-3", "仅显示第三方包"),
            ("-f", "显示 APK 路径"),
            ("-i", "显示安装来源"),
            ("-u", "包含已卸载包"),
            ("-r", "替换已存在应用"),
        ],
        "package_arguments": [
            "install",
            "install-existing",
            "uninstall",
            "clear",
            "path",
            "list packages",
            "enable",
            "disable",
            "disable-user",
            "enable-user",
            "hide",
            "unhide",
            "suspend",
            "unsuspend",
            "grant",
            "revoke",
            "dump",
            "get-app-links",
            "set-app-links",
            "reset-app-links",
        ],
    },
    "am": {
        "description": "Activity 与服务管理",
        "subcommands": [
            ("start", "启动 Activity"),
            ("start-activity", "启动 Activity"),
            ("start-service", "启动 Service"),
            ("start-foreground-service", "启动前台 Service"),
            ("broadcast", "发送广播"),
            ("force-stop", "强制停止应用"),
            ("kill", "终止应用进程"),
            ("kill-all", "终止所有后台进程"),
            ("instrument", "运行 instrumentation"),
            ("profile", "性能分析"),
            ("dumpheap", "导出堆快照"),
            ("monitor", "监视应用"),
            ("restart", "重启应用"),
            ("set-debug-app", "设置调试应用"),
            ("clear-debug-app", "清除调试应用"),
            ("stack", "任务栈操作"),
            ("task", "任务操作"),
            ("move-task", "移动任务"),
            ("resize-task", "调整任务大小"),
            ("split-screen", "分屏"),
            ("stack-list", "列出任务栈"),
            ("task-list", "列出任务"),
        ],
        "options": [
            ("-n", "指定组件名"),
            ("-a", "指定 Action"),
            ("-d", "指定数据 URI"),
            ("-t", "指定 MIME 类型"),
            ("-c", "指定 Category"),
            ("-e", "附加字符串参数"),
            ("--es", "附加字符串参数"),
            ("--ei", "附加整数参数"),
            ("--ez", "附加布尔参数"),
            ("--user", "指定用户"),
            ("-W", "等待启动完成"),
            ("-S", "先停止目标应用"),
        ],
        "package_arguments": [
            "start",
            "start-activity",
            "start-service",
            "start-foreground-service",
            "broadcast",
            "force-stop",
            "kill",
            "instrument",
            "set-debug-app",
            "start -n",
            "start-activity -n",
        ],
    },
    "dumpsys": {
        "description": "读取系统服务状态",
        "subcommands": [
            ("-l", "列出可用服务"),
            ("--help", "显示帮助"),
            ("activity", "Activity 服务"),
            ("window", "窗口服务"),
            ("package", "包服务"),
            ("power", "电源服务"),
            ("battery", "电池服务"),
            ("display", "显示服务"),
            ("input", "输入服务"),
            ("meminfo", "内存信息"),
            ("cpuinfo", "CPU 信息"),
            ("gfxinfo", "图形信息"),
            ("surfaceflinger", "SurfaceFlinger"),
            ("audio", "音频服务"),
            ("media.session", "媒体会话"),
            ("wifi", "Wi-Fi 服务"),
            ("connectivity", "网络连接"),
            ("bluetooth_manager", "蓝牙服务"),
            ("notification", "通知服务"),
            ("statusbar", "状态栏服务"),
            ("clipboard", "剪贴板服务"),
            ("settings", "设置服务"),
            ("alarm", "闹钟服务"),
            ("jobscheduler", "任务调度"),
            ("usagestats", "使用统计"),
            ("diskstats", "磁盘统计"),
            ("thermalservice", "温度服务"),
            ("sensorservice", "传感器服务"),
        ],
        "package_arguments": ["package", "meminfo", "gfxinfo", "usagestats"],
    },
    "settings": {
        "description": "读写系统设置",
        "subcommands": [
            ("help", "显示帮助"),
            ("get", "读取设置"),
            ("put", "写入设置"),
            ("list", "列出设置"),
            ("delete", "删除设置"),
            ("get-global", "读取 Global 设置"),
            ("put-global", "写入 Global 设置"),
            ("list-global", "列出 Global 设置"),
            ("get-secure", "读取 Secure 设置"),
            ("put-secure", "写入 Secure 设置"),
            ("list-secure", "列出 Secure 设置"),
            ("get-system", "读取 System 设置"),
            ("put-system", "写入 System 设置"),
            ("list-system", "列出 System 设置"),
        ],
        "value_arguments": {
            "get": ["global", "secure", "system"],
            "put": ["global", "secure", "system"],
            "list": ["global", "secure", "system"],
            "delete": ["global", "secure", "system"],
        },
    },
    "svc": {
        "description": "切换系统开关",
        "subcommands": [
            ("help", "显示帮助"),
            ("power", "电源控制"),
            ("data", "移动数据"),
            ("wifi", "Wi-Fi"),
            ("bluetooth", "蓝牙"),
            ("usb", "USB"),
            ("nfc", "NFC"),
            ("location", "定位"),
            ("statusbar", "状态栏"),
            ("cpu", "CPU"),
            ("gpu", "GPU"),
            ("display", "显示"),
        ],
        "value_arguments": {
            "power": ["on", "off"],
            "data": ["on", "off"],
            "wifi": ["on", "off"],
            "bluetooth": ["on", "off"],
            "usb": ["on", "off"],
            "nfc": ["on", "off"],
            "location": ["on", "off"],
        },
    },
    "wm": {
        "description": "修改显示参数",
        "subcommands": [
            ("help", "显示帮助"),
            ("size", "设置分辨率"),
            ("density", "设置 DPI"),
            ("overscan", "设置过扫描"),
            ("scaling", "设置缩放"),
            ("user-rotation", "设置用户旋转"),
            ("fixed-to-user-rotation", "固定用户旋转"),
            ("reset", "恢复默认"),
        ],
    },
    "input": {
        "description": "注入按键、文本或触控",
        "subcommands": [
            ("help", "显示帮助"),
            ("text", "输入文本"),
            ("keyevent", "发送按键事件"),
            ("tap", "点击坐标"),
            ("swipe", "滑动"),
            ("draganddrop", "拖放"),
            ("press", "按压"),
            ("roll", "滚轮"),
            ("motionevent", "注入触摸事件"),
            ("keycombination", "组合按键"),
        ],
    },
    "cmd": {
        "description": "调用系统命令服务",
        "subcommands": [
            ("help", "显示帮助"),
            ("activity", "Activity 服务"),
            ("package", "包服务"),
            ("window", "窗口服务"),
            ("input", "输入服务"),
            ("settings", "设置服务"),
            ("wifi", "Wi-Fi 服务"),
            ("connectivity", "网络连接"),
            ("media", "媒体服务"),
            ("audio", "音频服务"),
            ("display", "显示服务"),
            ("power", "电源服务"),
            ("battery", "电池服务"),
            ("notification", "通知服务"),
            ("statusbar", "状态栏服务"),
            ("clipboard", "剪贴板服务"),
            ("alarm", "闹钟服务"),
            ("jobscheduler", "任务调度"),
            ("usagestats", "使用统计"),
            ("netstats", "网络统计"),
            ("deviceidle", "Doze 状态"),
            ("appops", "应用权限"),
            ("sensorservice", "传感器服务"),
            ("thermalservice", "温度服务"),
            ("bluetooth_manager", "蓝牙服务"),
            ("overlay", "Overlay 服务"),
            ("uimode", "UI 模式"),
            ("shortcut", "快捷方式"),
            ("role", "角色管理"),
            ("autofill", "自动填充"),
            ("mount", "挂载服务"),
            ("storaged", "存储服务"),
            ("vibrator", "振动服务"),
        ],
        "package_arguments": [
            "package install",
            "package uninstall",
            "package list packages",
            "package clear",
            "package path",
            "package enable",
            "package disable-user",
            "package force-stop",
            "activity start-activity",
            "activity force-stop",
        ],
    },
    "monkey": {
        "description": "向应用发送随机事件",
        "subcommands": [
            ("-p", "指定包名"),
            ("-v", "详细输出"),
            ("-s", "随机种子"),
            ("-c", "指定 Category"),
            ("--throttle", "事件间隔毫秒"),
            ("--pct-touch", "触摸事件百分比"),
            ("--pct-motion", "移动事件百分比"),
            ("--pct-nav", "导航事件百分比"),
            ("--pct-majornav", "主导航事件百分比"),
            ("--pct-syskeys", "系统按键百分比"),
            ("--pct-appswitch", "应用切换百分比"),
            ("--pct-anyevent", "任意事件百分比"),
            ("--ignore-crashes", "忽略崩溃"),
            ("--ignore-timeouts", "忽略超时"),
            ("--monitor-native-crashes", "监视原生崩溃"),
            ("--kill-process-after-error", "出错后结束进程"),
        ],
        "package_arguments": ["-p"],
    },
    "screencap": {
        "description": "截取设备屏幕",
        "subcommands": [
            ("-p", "PNG 格式"),
            ("-h", "显示帮助"),
            ("-d", "指定显示 ID"),
            ("-t", "指定时间戳"),
            ("-a", "包含 Alpha 通道"),
        ],
    },
    "screenrecord": {
        "description": "录制设备屏幕",
        "subcommands": [
            ("--size", "录制分辨率"),
            ("--bit-rate", "码率"),
            ("--time-limit", "时长限制"),
            ("--rotate", "旋转画面"),
            ("--verbose", "详细输出"),
            ("--bugreport", "附加信息"),
            ("--display-id", "指定显示 ID"),
            ("--output-format", "输出格式"),
        ],
    },
    "content": {
        "description": "访问内容提供器",
        "subcommands": [
            ("help", "显示帮助"),
            ("query", "查询"),
            ("insert", "插入"),
            ("update", "更新"),
            ("delete", "删除"),
            ("call", "调用方法"),
            ("read", "读取文件"),
            ("write", "写入文件"),
            ("gettype", "读取 MIME 类型"),
        ],
    },
    "appops": {
        "description": "管理应用权限",
        "subcommands": [
            ("help", "显示帮助"),
            ("get", "读取权限模式"),
            ("set", "设置权限模式"),
            ("reset", "重置权限"),
            ("reset-all", "重置所有权限"),
        ],
        "package_arguments": ["get", "set", "reset"],
    },
    "deviceidle": {
        "description": "控制 Doze 状态",
        "subcommands": [
            ("help", "显示帮助"),
            ("force-idle", "强制进入 Doze"),
            ("unforce", "退出 Doze"),
            ("disable", "禁用 Doze"),
            ("enable", "启用 Doze"),
            ("whitelist", "白名单管理"),
            ("except-idle", "临时例外"),
            ("get", "读取状态"),
            ("step", "推进状态"),
        ],
    },
    "top": {
        "description": "查看进程资源占用",
        "subcommands": [
            ("-n", "刷新次数"),
            ("-d", "刷新间隔"),
            ("-m", "显示进程数"),
            ("-s", "排序列"),
            ("-H", "显示线程"),
            ("-p", "指定进程"),
            ("-t", "显示线程"),
            ("-h", "显示帮助"),
        ],
    },
    "ps": {
        "description": "列出进程",
        "subcommands": [
            ("-A", "所有进程"),
            ("-a", "所有用户进程"),
            ("-d", "已停止进程"),
            ("-e", "所有进程"),
            ("-f", "完整格式"),
            ("-l", "长格式"),
            ("-o", "指定字段"),
            ("-p", "指定 PID"),
            ("-u", "指定用户"),
            ("-x", "无终端进程"),
        ],
    },
    "kill": {
        "description": "终止进程",
        "subcommands": [
            ("-9", "SIGKILL"),
            ("-15", "SIGTERM"),
            ("-SIGKILL", "强制终止"),
            ("-SIGTERM", "正常终止"),
            ("-l", "列出信号"),
        ],
    },
    "ls": {
        "description": "列出目录",
        "subcommands": [
            ("-l", "长格式"),
            ("-a", "包含隐藏文件"),
            ("-h", "人类可读大小"),
            ("-R", "递归"),
            ("-d", "目录本身"),
            ("-t", "按时间排序"),
            ("-r", "反向排序"),
            ("-S", "按大小排序"),
            ("-i", "显示 inode"),
            ("-n", "数字 UID/GID"),
            ("-p", "目录加斜杠"),
            ("-F", "附加类型标记"),
        ],
    },
    "cat": {
        "description": "输出文件内容",
        "subcommands": [
            ("-n", "显示行号"),
            ("-b", "非空行编号"),
            ("-s", "压缩空行"),
            ("-v", "显示不可见字符"),
            ("-E", "行尾显示 $"),
            ("-T", "Tab 显示为 ^I"),
        ],
    },
    "df": {
        "description": "查看磁盘空间",
        "subcommands": [
            ("-h", "人类可读"),
            ("-k", "KB"),
            ("-m", "MB"),
            ("-i", "inode"),
            ("-a", "所有文件系统"),
            ("-T", "显示文件系统类型"),
        ],
    },
    "du": {
        "description": "统计目录占用",
        "subcommands": [
            ("-h", "人类可读"),
            ("-s", "汇总"),
            ("-a", "包含文件"),
            ("-k", "KB"),
            ("-m", "MB"),
            ("-c", "总计"),
            ("-d", "深度"),
        ],
    },
    "find": {
        "description": "查找文件",
        "subcommands": [
            ("-name", "按名称匹配"),
            ("-iname", "忽略大小写匹配"),
            ("-type", "按类型匹配"),
            ("-maxdepth", "最大深度"),
            ("-mindepth", "最小深度"),
            ("-size", "按大小匹配"),
            ("-mtime", "按修改时间匹配"),
            ("-exec", "执行命令"),
            ("-print", "输出路径"),
            ("-delete", "删除匹配项"),
        ],
    },
    "grep": {
        "description": "文本过滤",
        "subcommands": [
            ("-i", "忽略大小写"),
            ("-v", "反向匹配"),
            ("-n", "显示行号"),
            ("-r", "递归"),
            ("-E", "扩展正则"),
            ("-F", "固定字符串"),
            ("-w", "全词匹配"),
            ("-c", "只输出计数"),
            ("-l", "只输出文件名"),
        ],
    },
    "reboot": {
        "description": "重启设备",
        "subcommands": [
            ("bootloader", "重启到 Bootloader"),
            ("recovery", "重启到 Recovery"),
            ("fastboot", "重启到 Fastboot"),
            ("sideload", "重启到 Sideload"),
            ("edl", "重启到 EDL"),
            ("download", "重启到下载模式"),
            ("userspace", "重启用户空间"),
            ("-p", "关机"),
        ],
    },
    "logcat": {
        "description": "读取设备日志",
        "subcommands": [
            ("-c", "清空日志"),
            ("-d", "输出后退出"),
            ("-f", "写入文件"),
            ("-g", "显示缓冲区信息"),
            ("-n", "轮转数量"),
            ("-r", "轮转大小"),
            ("-s", "静默标签"),
            ("-v", "日志格式"),
            ("-t", "最近条数"),
            ("-b", "指定缓冲区"),
            ("--pid", "指定 PID"),
            ("--regex", "正则过滤"),
        ],
    },
    "ping": {
        "description": "测试网络连通性",
        "subcommands": [
            ("-c", "发送次数"),
            ("-i", "间隔秒数"),
            ("-s", "包大小"),
            ("-W", "超时时间"),
            ("-w", "总超时"),
            ("-4", "IPv4"),
            ("-6", "IPv6"),
        ],
    },
    "ip": {
        "description": "查看或配置 IP",
        "subcommands": [
            ("help", "显示帮助"),
            ("addr", "地址管理"),
            ("route", "路由管理"),
            ("link", "链路管理"),
            ("rule", "规则管理"),
            ("neigh", "邻居表"),
            ("tunnel", "隧道"),
            ("maddress", "组播地址"),
            ("netns", "网络命名空间"),
        ],
    },
    "ifconfig": {
        "description": "查看或配置网络接口",
        "subcommands": [
            ("up", "启用接口"),
            ("down", "禁用接口"),
            ("netmask", "设置掩码"),
            ("broadcast", "设置广播地址"),
            ("mtu", "设置 MTU"),
            ("hw", "设置硬件地址"),
        ],
    },
    "service": {
        "description": "调用系统服务",
        "subcommands": [
            ("help", "显示帮助"),
            ("list", "列出服务"),
            ("call", "调用服务方法"),
        ],
    },
    "install": {
        "description": "安装 APK",
        "subcommands": [
            ("-r", "替换已存在应用"),
            ("-d", "允许降级安装"),
            ("-g", "授予所有运行时权限"),
            ("-t", "允许测试包"),
            ("-s", "安装到 SD 卡"),
            ("--user", "指定用户"),
            ("--abi", "指定 ABI"),
            ("--instant", "即时应用"),
            ("--no-streaming", "不使用流式安装"),
        ],
    },
    "uninstall": {
        "description": "卸载应用",
        "subcommands": [
            ("-k", "保留数据"),
            ("--user", "指定用户"),
            ("--versionCode", "指定版本"),
        ],
    },
    "forward": {
        "description": "建立端口转发",
        "subcommands": [
            ("--no-rebind", "不重新绑定"),
            ("tcp:", "TCP 端口"),
            ("udp:", "UDP 端口"),
            ("localabstract:", "抽象本地套接字"),
            ("localreserved:", "保留本地套接字"),
            ("localfilesystem:", "本地文件系统套接字"),
        ],
    },
    "reverse": {
        "description": "建立反向端口转发",
        "subcommands": [
            ("--no-rebind", "不重新绑定"),
            ("tcp:", "TCP 端口"),
            ("udp:", "UDP 端口"),
            ("localabstract:", "抽象本地套接字"),
        ],
    },
    "reconnect": {
        "description": "重连设备",
        "subcommands": [
            ("device", "重连在线设备"),
            ("offline", "重连离线设备"),
        ],
    },
}


# Pipeline helpers are part of the default shell command catalogue, but only
# the filters that make sense in the middle of a pipeline are listed first by
# the terminal after the user types "|".
for _pipe_name, (
    _pipe_syntax,
    _pipe_description,
    _pipe_options,
) in _PIPE_DEFINITIONS.items():
    if _pipe_name in _DEFAULT_COMMANDS:
        continue
    _DEFAULT_COMMANDS[_pipe_name] = {
        "description": _pipe_description,
        "subcommands": list(_pipe_options),
    }


_README = """adb-utils 命令补全配置

介绍
  终端按 Tab 时，会根据当前输入的命令加载对应补全项。
  例如在 shell 模式输入 `pm ` 后按 Tab，会列出 pm 的子命令；
  输入 `pm h` 会优先补全 `help`，不会再拿 `h` 去匹配包名。

目录
  commands.json   默认配置，可直接编辑。
  *.json          可以新增自己的配置文件；按文件名排序加载，
                  后加载的同名命令会覆盖前面的配置。

命令格式
  {
    "command": "pm",
    "description": "包管理",
    "subcommands": [
      "help",
      ["list packages", "列出包名", "pm list packages"],
      {"path": ["list", "permissions"], "description": "列出权限",
       "syntax": "pm list permissions"}
    ],
    "options": [
      ["--user", "指定用户 ID"],
      "-r"
    ],
    "package_arguments": [
      "install",
      "uninstall",
      "list packages"
    ],
    "value_arguments": {
      "get": ["global", "secure", "system"]
    }
  }

说明
  subcommands       子命令路径；支持空格分隔多级路径。
  options           命令选项，输入 - 开头时优先显示。
  package_arguments 这些子命令路径之后补全设备包名。
  value_arguments   这些子命令路径之后补全固定值。

  也支持在一个文件里写多个命令：
  {"commands": {"pm": {...}, "am": {...}}}

  保存后回到终端再次按 Tab 即可生效，无需重启。

管道补全
  在 shell 模式下输入 `|` 后按 Tab，会优先列出 grep、sed、awk、
  sort、uniq、head、tail、wc、xargs 等 Linux 管道工具；继续输入
  前缀可筛选，输入 `sort -` 等可继续补全该命令的选项。
  可以在本目录的 JSON 中继续补充命令或覆盖内置规则。
"""
