# -*- coding: utf-8 -*-
"""
把「npx -y <套件> 參數…」換成「node <已下載套件的進入點> 參數…」

透過 npx 啟動 MCP 伺服器會多出 cmd → npx(node) → cmd 三層外殼，實測多吃約 100MB 記憶體、啟動也較慢。
套件第一次由 npx 下載後會留在 %LOCALAPPDATA%\\npm-cache\\_npx\\<hash>\\node_modules，
之後直接用 node 執行即可。找不到快取（還沒下載過）就維持原本的 npx，讓它去下載。
"""
from __future__ import annotations

import glob
import json
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

_VALUE_FLAGS = {"-p", "--package", "-c", "--call"}


def _split_npx_args(args: List[str]) -> Tuple[Optional[str], List[str]]:
    """回傳 (套件規格, 傳給套件的參數)。遇到 -p / -c 這類較複雜的用法就放棄（回傳 None）。"""
    i = 0
    while i < len(args):
        a = args[i]
        if a in _VALUE_FLAGS:
            return None, args
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return None, args


def _package_name(spec: str) -> str:
    """'@scope/name@1.2.3' → '@scope/name'；'name@latest' → 'name'。"""
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec


def find_cached_entry(package: str, cache_root: Optional[Path] = None) -> Optional[Path]:
    root = cache_root or Path(os.environ.get("LOCALAPPDATA", "")) / "npm-cache" / "_npx"
    candidates = []
    for pj in glob.glob(str(root / "*" / "node_modules" / Path(package) / "package.json")):
        try:
            meta = json.loads(Path(pj).read_text(encoding="utf-8"))
        except Exception:
            continue
        bin_field = meta.get("bin")
        if isinstance(bin_field, str):
            rel = bin_field
        elif isinstance(bin_field, dict) and bin_field:
            short = package.split("/")[-1]
            rel = bin_field.get(short) or next(iter(bin_field.values()))
        else:
            continue
        entry = (Path(pj).parent / rel).resolve()
        if entry.exists():
            candidates.append((Path(pj).stat().st_mtime, entry))
    return max(candidates)[1] if candidates else None


def resolve(command: str, args: List[str], cache_root: Optional[Path] = None) -> Tuple[str, List[str], bool]:
    """回傳 (執行檔, 參數, 是否已改成直接用 node)。"""
    if Path(command).stem.lower() != "npx":
        return command, args, False
    spec, rest = _split_npx_args(args)
    node = shutil.which("node")
    if not spec or not node:
        return command, args, False
    entry = find_cached_entry(_package_name(spec), cache_root)
    if not entry:
        return command, args, False
    return node, [str(entry)] + rest, True
