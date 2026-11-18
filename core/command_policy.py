# -*- coding: utf-8 -*-
"""
Shell 指令風險分級（取代原本只有 11 條規則的黑名單）

分三級：
- READ_ONLY   ：確定只讀的指令（列目錄、讀檔、git status、跑測試…）→ 任何模式都直接放行
- DESTRUCTIVE ：會刪改檔案、殺行程、改系統設定、安裝套件、下載執行… → 除了 Turbo 模式都要你按批准
- UNKNOWN     ：判斷不了的其他指令 → Default / 嚴格審查模式要批准；Auto 模式放行；Turbo 放行

指令會先依 ; | && || 換行 拆成多段，每一段都要是 READ_ONLY 整條才算 READ_ONLY；
任一段命中破壞性規則就是 DESTRUCTIVE。
"""
from __future__ import annotations

import re
from typing import List, Tuple

READ_ONLY = "READ_ONLY"
DESTRUCTIVE = "DESTRUCTIVE"
UNKNOWN = "UNKNOWN"

# ---- 破壞性規則：(正則, 說明) ----------------------------------------------------
_DESTRUCTIVE_RULES: List[Tuple[str, str]] = [
    (r"(?<![\w-])(remove-item|rm|del|erase|rd|rmdir|ri)(?![\w-])", "刪除檔案或資料夾"),
    (r"(?<![\w-])(move-item|mv|move|rename-item|ren|rni)(?![\w-])", "搬移或改名檔案"),
    (r"(?<![\w-])(set-content|add-content|out-file|clear-content|clc|new-item|ni|mkdir|md|copy-item|cp|copy|xcopy|robocopy)(?![\w-])", "建立或改寫檔案"),
    # 2>&1、2>$null、>$null、>nul 不會寫檔，不算
    (r"(?<![<>=-])\d?>{1,2}(?![>=])(?!\s*(?:&\d|\$null\b|nul\b))", "把輸出寫入檔案（>、>>）"),
    (r"(?<![\w-])(stop-process|kill|spps|taskkill|tskill)(?![\w-])", "結束其他程式"),
    (r"(?<![\w-])(stop-service|restart-service|set-service|start-service|new-service|sc(\.exe)?\s+(stop|delete|config|create))(?![\w-])", "變更系統服務"),
    (r"(?<![\w-])(shutdown|restart-computer|stop-computer|logoff)(?![\w-])", "關機、重開或登出"),
    (r"(?<![\w-])(set-executionpolicy|set-itemproperty|new-itemproperty|remove-itemproperty|sp)(?![\w-])", "修改系統或登錄檔設定"),
    (r"(?<![\w-])reg(\.exe)?\s+(add|delete|import|copy|restore|load)", "修改登錄檔"),
    (r"(?<![\w-])(bcdedit|diskpart|format|format-volume|clear-disk|initialize-disk|cipher|manage-bde|vssadmin|wbadmin)(?![\w-])", "磁碟或開機設定"),
    (r"(?<![\w-])(icacls|takeown|attrib|cacls)(?![\w-])", "修改檔案權限或屬性"),
    (r"(?<![\w-])net(\.exe)?\s+(user|localgroup|share|use|stop|start)", "帳號、共用或服務設定"),
    (r"(?<![\w-])(netsh|schtasks|register-scheduledtask|unregister-scheduledtask|set-netfirewallrule|new-netfirewallrule)(?![\w-])", "網路、防火牆或排程設定"),
    (r"(?<![\w-])(winget|choco|scoop)\s+(install|uninstall|upgrade|remove)", "安裝或移除軟體"),
    (r"(?<![\w-])(pip3?|python(3)?\s+-m\s+pip|uv\s+pip|conda)\s+(install|uninstall|remove)", "安裝或移除 Python 套件"),
    (r"(?<![\w-])(npm|pnpm|yarn)\s+(install|i|add|uninstall|remove|rm|update|publish)(?![\w-])", "安裝、移除或發佈 npm 套件"),
    (r"(?<![\w-])git\s+(push|pull|fetch|clone|reset|clean|checkout|restore|rebase|merge|commit|stash|rm|mv|branch\s+-[dD]|tag\s+-d|filter-branch|gc|prune)(?![\w-])", "改變 Git 版本庫或與遠端同步"),
    (r"(?<![\w-])(invoke-expression|iex)(?![\w-])", "執行動態產生的程式碼"),
    (r"(?<![\w-])(invoke-webrequest|iwr|invoke-restmethod|irm|curl|wget|start-bitstransfer|certutil)(?![\w-])", "從網路下載或上傳"),
    (r"(?<![\w-])start-process\b.*-verb\s+runas", "要求系統管理員權限"),
    (r"-(enc|encodedcommand|e|ec)\s+[a-z0-9+/=]{16,}", "執行編碼混淆過的指令"),
    (r"(?<![\w-])(python3?|py|node|deno|bun|ruby|perl)\s+(-c|-e|--eval)(?![\w-])", "執行內嵌程式碼"),
    (r"(?<![\w-])(powershell|pwsh|cmd)(\.exe)?\s+(/c|-c|-command|/k)", "另開殼層執行指令"),
    (r"(?<![\w-])(set-mppreference|add-mppreference|remove-mppreference)(?![\w-])", "變更 Defender 設定"),
    # ---- Linux（bash）常見的破壞性指令 ----
    (r"(?<![\w-])(chmod|chown|chgrp|ln|touch|truncate|dd|shred|tee|install|unlink|mkfs(\.\w+)?|mount|umount|crontab|systemctl|service|useradd|userdel|usermod|passwd|sudo|su|apt(-get)?|yum|dnf|pacman|brew|snap)(?![\w-])", "修改檔案、權限或系統（Linux）"),
    (r"(?<![\w-])sed\s+(-[a-z]*i|--in-place)", "直接改寫檔案內容（sed -i）"),
    (r"(?<![\w-])find\s.*\s-(delete|exec|execdir|ok)(?![\w-])", "find 搭配刪除或執行其他指令"),
    (r"(?<![\w-])(xargs|nohup|eval|exec|source|bash|sh|zsh)(?![\w-])", "另開殼層或間接執行指令"),
    (r"(?<![\w-])(scp|rsync|ssh|nc|ncat|telnet|ftp|sftp)(?![\w-])", "遠端連線或傳輸檔案"),
]
# 指令名稱前後不能緊鄰路徑或副檔名字元，避免 README.md 的「md」、C:\move 的「move」被誤判
_B, _E = r"(?<![\w.\\/:$-])", r"(?![\w.\\/:-])"
_DESTRUCTIVE = [
    (re.compile(p.replace(r"(?<![\w-])", _B).replace(r"(?![\w-])", _E), re.IGNORECASE), why)
    for p, why in _DESTRUCTIVE_RULES
]

# ---- 只讀白名單（每一段的開頭）----------------------------------------------------
_READ_ONLY_HEADS = [
    r"get-[\w-]+", r"(dir|ls|gci|gi|gp|gc|cat|type|more|tree|pwd|gl|cd|sl|set-location|push-location|pop-location)",
    r"select-string|sls|findstr|find|where(\.exe)?|where-object|\?|select-object|select|sort-object|sort|group-object|measure-object|measure",
    r"format-(table|list|wide)|ft|fl|out-string|out-host|write-output|write-host|echo|convertto-json|convertfrom-json|foreach-object|%",
    r"test-path|resolve-path|split-path|join-path|test-connection|compare-object",
    r"whoami|hostname|ipconfig|systeminfo|tasklist|ver|date|time|ping|nslookup|tracert|netstat|route\s+print|arp\s+-a",
    r"git\s+(status|log|diff|show|blame|branch|remote|rev-parse|ls-files|describe|shortlog|config\s+--get|tag)",
    r"(python3?|py|node|npm|pip3?|git|dotnet|java|cargo|rustc|go)\s+(--version|-v|version)",
    r"pip3?\s+(list|show|freeze|check)", r"npm\s+(ls|list|outdated|view|test|run\s+test)", r"cargo\s+(test|check|build)",
    r"(python3?|py)\s+-m\s+(pytest|unittest|pyflakes|py_compile|mypy|ruff\s+check)", r"pytest", r"ruff\s+check",
    # ---- Linux（bash）常見的只讀指令 ----
    r"head|tail|wc|grep|egrep|fgrep|rg|less|file|stat|du|df|uname|basename|dirname|realpath|readlink",
    r"uniq|cut|tr|column|nl|diff|cmp|id|uptime|free|ps|which|type|ll|la|true|false|printf",
]
_READ_ONLY = re.compile(r"^\s*(&\s*)?(" + "|".join(_READ_ONLY_HEADS) + r")(?![\w-])", re.IGNORECASE)

_SPLIT = re.compile(r"\s*(?:;|\|\||&&|\||\r?\n)\s*")


def split_segments(command: str) -> List[str]:
    return [s for s in _SPLIT.split(command or "") if s.strip()]


def classify_command(command: str) -> Tuple[str, str]:
    """回傳 (等級, 原因)。"""
    cmd = (command or "").strip()
    if not cmd:
        return READ_ONLY, "空指令"
    for rx, why in _DESTRUCTIVE:
        if rx.search(cmd):
            return DESTRUCTIVE, why
    segs = split_segments(cmd)
    if segs and all(_READ_ONLY.match(s) for s in segs):
        return READ_ONLY, "只讀查詢指令"
    return UNKNOWN, "無法確認是否只讀的指令"


def needs_approval(level: str, execution_mode: str) -> bool:
    """依你在輸入框選的執行模式決定要不要跳批准視窗。"""
    mode = (execution_mode or "default").lower()
    if level == READ_ONLY:
        return False
    if mode == "turbo":
        return False
    if mode == "auto":
        return level == DESTRUCTIVE
    return True  # default / request_review：只要不是確定只讀就問
