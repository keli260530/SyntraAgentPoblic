# -*- coding: utf-8 -*-
"""偵測安裝環境：作業系統、Python 版本、GPU、磁碟空間、外部工具、管理員權限。"""
from __future__ import annotations

import platform as _platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

MIN_PYTHON = (3, 9)


@dataclass
class Environment:
    platform: str  # sys.platform，例如 "win32"
    os_name: str  # 給人看的名稱，例如 "Windows 11"
    python_version: Tuple[int, int, int]
    python_executable: str
    gpu: Optional[str] = None  # 偵測到的獨立顯示卡名稱
    free_disk_mb: int = 0
    is_admin: bool = False
    has_node: bool = False
    has_wdk: bool = False
    in_git_checkout: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def is_windows(self) -> bool:
        return self.platform.startswith("win")

    @property
    def python_ok(self) -> bool:
        return self.python_version[:2] >= MIN_PYTHON


_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


def _run(cmd, timeout: float = 8.0) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW
        )
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


_INTEGRATED = ("microsoft basic", "intel(r) uhd", "intel(r) hd", "intel(r) iris")


def detect_gpu() -> Optional[str]:
    if shutil.which("nvidia-smi"):
        name = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).strip()
        if name:
            return name.splitlines()[0].strip()
    if sys.platform.startswith("win"):
        out = _run([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_VideoController).Name",
        ])
        for line in out.splitlines():
            name = line.strip()
            if name and not name.lower().startswith(_INTEGRATED):
                return name
    return None


def detect_admin() -> bool:
    try:
        if sys.platform.startswith("win"):
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        import os

        return os.geteuid() == 0
    except Exception:
        return False


def detect_wdk() -> bool:
    root = Path(r"C:\Program Files (x86)\Windows Kits\10\Include")
    try:
        return any((p / "km").is_dir() for p in root.iterdir())
    except OSError:
        return False


def detect(project_root: Path) -> Environment:
    try:
        free_mb = shutil.disk_usage(str(project_root)).free // (1024 * 1024)
    except OSError:
        free_mb = 0
    os_name = f"{_platform.system()} {_platform.release()}".strip()
    if sys.platform.startswith("win"):
        try:  # platform.release() 在 Windows 11 仍回傳 "10"，改用組建編號判斷
            if int(_platform.version().split(".")[2]) >= 22000:
                os_name = "Windows 11"
        except (IndexError, ValueError):
            pass
    return Environment(
        platform=sys.platform,
        os_name=os_name,
        python_version=tuple(sys.version_info[:3]),
        python_executable=sys.executable,
        gpu=detect_gpu(),
        free_disk_mb=int(free_mb),
        is_admin=detect_admin(),
        has_node=bool(shutil.which("node")),
        has_wdk=detect_wdk() if sys.platform.startswith("win") else False,
        in_git_checkout=(project_root / ".git").exists(),
    )
