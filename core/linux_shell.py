# -*- coding: utf-8 -*-
"""
core/linux_shell.py
===================
在 Windows 上找一個能跑 Linux 指令（bash）的環境，並組出執行用的命令列。

優先順序（可用環境變數 SYNTRA_LINUX_SHELL=gitbash|wsl 強制指定）：
1. Git Bash（Git for Windows 內建的 bash.exe，直接看得到 Windows 路徑）
2. WSL（需要已安裝 Linux 發行版）
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

_CACHE: Optional[Tuple[str, str]] = None  # (kind, exe)

_GIT_BASH_CANDIDATES = [
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
]


def _find_git_bash() -> Optional[str]:
    for p in _GIT_BASH_CANDIDATES:
        if p and Path(p).is_file():
            return p
    git = shutil.which("git")
    if git:
        # ...\Git\cmd\git.exe → ...\Git\bin\bash.exe
        cand = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if cand.is_file():
            return str(cand)
    return None


def _wsl_has_distro() -> Optional[str]:
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return None
    try:
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        out = subprocess.run([wsl, "-l", "-q"], capture_output=True, timeout=8, creationflags=flags)
        # wsl -l 輸出是 UTF-16
        text = out.stdout.decode("utf-16-le", errors="ignore").replace("\x00", "").strip()
        if out.returncode == 0 and text and "wsl.exe --install" not in text:
            return wsl
    except Exception:
        pass
    return None


def find_linux_shell(refresh: bool = False) -> Optional[Tuple[str, str]]:
    """回傳 ("gitbash"|"wsl", 執行檔路徑)；找不到回傳 None"""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    pref = os.environ.get("SYNTRA_LINUX_SHELL", "").strip().lower()
    order = ["wsl", "gitbash"] if pref == "wsl" else ["gitbash", "wsl"]
    for kind in order:
        exe = _find_git_bash() if kind == "gitbash" else _wsl_has_distro()
        if exe:
            _CACHE = (kind, exe)
            return _CACHE
    return None


def describe_linux_shell() -> str:
    found = find_linux_shell()
    if not found:
        return "找不到 Linux 環境（請安裝 Git for Windows 或 WSL）"
    return "Git Bash" if found[0] == "gitbash" else "WSL"


def build_argv(command: str, cwd: Optional[str] = None) -> List[str]:
    """組出執行 Linux 指令的命令列；找不到環境時丟出 RuntimeError"""
    found = find_linux_shell()
    if not found:
        raise RuntimeError("找不到 Linux 環境：請安裝 Git for Windows（含 Git Bash）或 WSL")
    kind, exe = found
    if kind == "gitbash":
        # -l 載入登入環境（PATH 才有 ls/grep 等），--noprofile 避免使用者設定檔干擾
        return [exe, "--noprofile", "-lc", command]
    argv = [exe]
    if cwd:
        argv += ["--cd", cwd]
    return argv + ["--", "bash", "-lc", command]
