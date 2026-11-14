adb-utils 命令补全配置

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
