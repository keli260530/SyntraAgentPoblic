# -*- coding: utf-8 -*-
"""
Process Utilities for Silent Background Execution
落實 OOP 與模組化：集中管理所有 Windows 子進程之後台靜默執行。
確保所有後台進程（網路防禦、安全排查、日誌審計、系統修復等）100% 靜默運行，
絕不在前端彈出任何命令提示字元 (cmd.exe / powershell.exe / conhost) 黑色視窗。
"""

import os
import subprocess
import sys
from typing import Any, Dict, List, Optional, Union


def get_silent_windows_flags() -> tuple[int, Optional[subprocess.STARTUPINFO]]:
    """
    返回徹底壓制 Windows 命令提示字元黑框的雙重保險旗標：
    1. CREATE_NO_WINDOW (0x08000000)
    2. STARTUPINFO (STARTF_USESHOWWINDOW + SW_HIDE)
    """
    creationflags = 0
    startupinfo = None

    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
        startupinfo = subprocess.STARTUPINFO()
        # STARTF_USESHOWWINDOW + STARTF_FORCEOFFFEEDBACK (0x80)：壓制黑框並避免滑鼠游標出現「忙碌藍圈」
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW | 0x00000080
        startupinfo.wShowWindow = 0  # SW_HIDE

    return creationflags, startupinfo


def silent_run(
    cmd: Union[str, List[str]],
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    check: bool = False,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    以完全靜默的背景模式執行命令，絕不彈出命令提示字元視窗。
    """
    c_flags, s_info = get_silent_windows_flags()

    # 如果傳入純字串且未顯式指定 shell，在 Windows 下使用列表避免多餘的 cmd 衍生
    kwargs: Dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "cwd": cwd,
        "env": env,
        "check": check,
        "input": input_text,
    }

    if sys.platform == "win32":
        kwargs["creationflags"] = c_flags
        kwargs["startupinfo"] = s_info

    return subprocess.run(cmd, **kwargs)


def silent_popen(
    cmd: Union[str, List[str]],
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    stdin: Any = None,
    text: bool = True,
    close_fds: bool = True,
) -> subprocess.Popen:
    """
    以完全靜默的背景模式啟動子進程。
    """
    c_flags, s_info = get_silent_windows_flags()

    kwargs: Dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdout": stdout,
        "stderr": stderr,
        "stdin": stdin,
        "close_fds": close_fds,
    }

    if text:
        kwargs["text"] = True
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"

    if sys.platform == "win32":
        kwargs["creationflags"] = c_flags
        kwargs["startupinfo"] = s_info

    return subprocess.Popen(cmd, **kwargs)
