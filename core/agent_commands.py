# -*- coding: utf-8 -*-
"""
core/agent_commands.py
======================
輸入框裡的「Linux 風格」代理管理指令。只有整行完全符合格式才會被當成指令，
其他文字照常送給 AI。

    ps / jobs              列出所有代理
    new [名稱]             新增代理
    cd <編號>              切換到某個代理
    kill <編號>            關閉代理（主控不能關）
    rename <編號> <名稱>   幫代理改名
    stop [編號]            停止代理正在跑的這一輪
    !<bash 指令>           直接執行 Linux 指令並顯示結果（例如 !ls -la）
    remote                 顯示 Linux 終端機遙控的連線方式
    help                   顯示這份說明
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

HELP_TEXT = """可用的代理指令（整行只打指令才會生效）：
  ps                    列出所有代理（編號、名稱、狀態）
  new [名稱]            新增代理
  cd <編號>             切換到某個代理
  kill <編號>           關閉代理（主控 #1 不能關）
  rename <編號> <名稱>  幫代理改名
  stop [編號]           停止代理正在跑的這一輪（不填編號＝目前這個）
  !<Linux 指令>         直接用 bash 執行，例如：!ls -la、!grep -rn TODO .
  remote                顯示從 Linux 終端機遙控 Syntra 的方法
  help                  顯示這份說明"""

_PATTERNS = [
    (re.compile(r"^(?:ps|jobs)$", re.I), "ps"),
    (re.compile(r"^new(?:\s+(?P<name>.{1,40}))?$", re.I), "new"),
    (re.compile(r"^(?:cd|switch)\s+#?(?P<no>\d{1,3})$", re.I), "cd"),
    (re.compile(r"^(?:kill|close)\s+#?(?P<no>\d{1,3})$", re.I), "kill"),
    (re.compile(r"^rename\s+#?(?P<no>\d{1,3})\s+(?P<name>.{1,40})$", re.I), "rename"),
    (re.compile(r"^stop(?:\s+#?(?P<no>\d{1,3}))?$", re.I), "stop"),
    (re.compile(r"^remote$", re.I), "remote"),
    (re.compile(r"^(?:help|man|\?)$", re.I), "help"),
]


def parse_agent_command(text: str) -> Optional[Tuple[str, dict]]:
    """回傳 (指令, 參數)；不是指令就回傳 None"""
    s = (text or "").strip()
    if not s or "\n" in s:
        return None
    if s.startswith("!"):
        cmd = s[1:].strip()
        return ("sh", {"command": cmd}) if cmd else None
    for pat, name in _PATTERNS:
        m = pat.match(s)
        if m:
            args = {k: v for k, v in m.groupdict().items() if v is not None}
            if "no" in args:
                args["no"] = int(args["no"])
            if "name" in args:
                args["name"] = args["name"].strip()
            return name, args
    return None
