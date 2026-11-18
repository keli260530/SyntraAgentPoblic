# -*- coding: utf-8 -*-
"""安裝狀態檔（manifest）與 pip 執行。

manifest 存在 <專案>/.syntra/install-manifest.json，只記錄「哪些模組已安裝、
當時各套件版本」，不含任何個人資料。只有內容真的改變時才會寫檔，
所以重複執行同一指令，結果與檔案內容都不變（idempotent）。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .planner import Plan, Requirement, installed_version

MANIFEST_REL = Path(".syntra") / "install-manifest.json"


def manifest_path(project_root: Path) -> Path:
    return project_root / MANIFEST_REL


def load_manifest(project_root: Path) -> Dict:
    path = manifest_path(project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("modules"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"schema": 1, "modules": {}}


def installed_modules(project_root: Path) -> List[str]:
    return list(load_manifest(project_root)["modules"])


def save_manifest(project_root: Path, data: Dict) -> bool:
    """寫入 manifest；內容沒變就不寫。回傳是否有寫檔。"""
    path = manifest_path(project_root)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def record(project_root: Path, plan: Plan, lookup=installed_version) -> bool:
    data = load_manifest(project_root)
    for item in plan.items:
        if item.status == "manual":
            continue
        pkgs = {}
        for spec in item.module.packages:
            req = Requirement(spec)
            if req.marker is not None and not req.marker.evaluate():
                continue
            pkgs[req.name] = lookup(req.name)
        data["modules"][item.module.id] = {"packages": pkgs}
    return save_manifest(project_root, data)


def pip_install(python: str, specs: List[str], force: bool = False,
                runner=subprocess.run) -> int:
    if not specs:
        return 0
    cmd = [python, "-m", "pip", "install", "--disable-pip-version-check"]
    if force:
        cmd.append("--force-reinstall")
    cmd += specs
    print("執行：" + " ".join(cmd), flush=True)
    return runner(cmd).returncode
