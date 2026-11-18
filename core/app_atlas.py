# -*- coding: utf-8 -*-
"""
軟體功能地圖（App Atlas）：自動探索任何軟體的按鈕、選單與快捷鍵。

做法：透過 Windows 無障礙 API（UIA）唯讀走訪視窗的控制項，記下
選單項目、按鈕、分頁、工具列的名稱與快捷鍵（AcceleratorKey / AccessKey），
存成 data/app_atlas/<程式名>.json。下次操作同一個軟體時，把地圖重點放進提示詞，
模型就知道「另存新檔在檔案選單、快捷鍵 Ctrl+Shift+S」，不必截圖亂找。

只讀取、不點擊、不展開選單，因此不會改變任何軟體狀態。
是否允許讀取視窗內容，由呼叫端（app_skills.run_tool）先經過使用者的權限設定把關。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "app_atlas"

# 有操作意義的控制項類型
_ACTION_TYPES = {
    "MenuItemControl": "menu", "ButtonControl": "button", "SplitButtonControl": "button",
    "TabItemControl": "tab", "HyperlinkControl": "link", "CheckBoxControl": "toggle",
    "RadioButtonControl": "toggle", "ComboBoxControl": "combo", "EditControl": "input",
    "ListItemControl": "item", "TreeItemControl": "item", "MenuBarControl": "menubar",
    "ToolBarControl": "toolbar",
}
_MAX_NODES = 600
_MAX_DEPTH = 12
_MAX_SECONDS = 6.0


def _safe_name(process_name: str) -> str:
    base = os.path.splitext((process_name or "unknown").lower())[0]
    return re.sub(r"[^a-z0-9_\-]+", "_", base) or "unknown"


def atlas_path(process_name: str, data_dir: Optional[Path] = None) -> Path:
    return (data_dir or _DATA_DIR) / f"{_safe_name(process_name)}.json"


def _walk_uia(hwnd: int) -> List[Dict[str, Any]]:
    """唯讀走訪 UIA 樹，回傳有名稱的可操作控制項。"""
    import uiautomation as auto

    root = auto.ControlFromHandle(int(hwnd))
    if root is None:
        return []
    found: List[Dict[str, Any]] = []
    seen = set()
    start = time.monotonic()
    stack = [(root, 0, "")]
    visited = 0
    while stack and visited < _MAX_NODES and time.monotonic() - start < _MAX_SECONDS:
        ctrl, depth, parent_path = stack.pop()
        visited += 1
        try:
            ctype = ctrl.ControlTypeName
            name = (ctrl.Name or "").strip()
        except Exception:
            continue
        kind = _ACTION_TYPES.get(ctype)
        path = parent_path
        if kind and name and len(name) <= 80:
            accel = ""
            access = ""
            try:
                accel = (ctrl.AcceleratorKey or "").strip()
                access = (ctrl.AccessKey or "").strip()
            except Exception:
                pass
            key = (kind, name, parent_path)
            if key not in seen and kind not in ("menubar", "toolbar"):
                seen.add(key)
                found.append({"kind": kind, "name": name, "where": parent_path,
                              "shortcut": accel, "access_key": access})
            if kind in ("menubar", "toolbar", "menu", "tab"):
                path = f"{parent_path} > {name}" if parent_path else name
        if depth >= _MAX_DEPTH:
            continue
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for ch in reversed(children):
            stack.append((ch, depth + 1, path))
    return found


def learn_window(hwnd: int, process_name: str, title: str = "",
                 data_dir: Optional[Path] = None, walker=None) -> Dict[str, Any]:
    """探索一個視窗並把結果合併進該程式的功能地圖。walker 可注入假資料供測試。"""
    controls = (walker or _walk_uia)(hwnd)
    path = atlas_path(process_name, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atlas = load(process_name, data_dir) or {"process": process_name.lower(), "controls": [], "windows": []}
    existing = {(c["kind"], c["name"], c.get("where", "")) for c in atlas["controls"]}
    added = 0
    for c in controls:
        k = (c["kind"], c["name"], c.get("where", ""))
        if k not in existing:
            atlas["controls"].append(c)
            existing.add(k)
            added += 1
    if title and title not in atlas["windows"]:
        atlas["windows"] = (atlas["windows"] + [title])[-10:]
    atlas["controls"] = atlas["controls"][-1500:]
    atlas["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path.write_text(json.dumps(atlas, ensure_ascii=False, indent=1), encoding="utf-8")
    with_shortcut = sum(1 for c in atlas["controls"] if c.get("shortcut"))
    return {"ok": True, "process": process_name, "found_now": len(controls), "added": added,
            "total": len(atlas["controls"]), "with_shortcut": with_shortcut, "saved_to": str(path)}


def load(process_name: str, data_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = atlas_path(process_name, data_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def known_processes(data_dir: Optional[Path] = None) -> List[str]:
    d = data_dir or _DATA_DIR
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def summarize(process_name: str, query: str = "", limit: int = 25, data_dir: Optional[Path] = None) -> str:
    """把功能地圖整理成精簡文字；有 query 時優先列出名稱相關的項目。"""
    atlas = load(process_name, data_dir)
    if not atlas or not atlas.get("controls"):
        return ""
    controls = atlas["controls"]
    q = (query or "").lower()
    terms = [w for w in re.split(r"[\s，,。]+", q) if w]

    def score(c):
        n = (c["name"] + " " + c.get("where", "")).lower()
        s = sum(2 for w in terms if w and w in n)
        s += 1 if c.get("shortcut") else 0
        s += 1 if c["kind"] == "menu" else 0
        return -s

    picked = sorted(controls, key=score)[:limit]
    lines = [f"#### 🗺️ {atlas.get('process', process_name)} 功能地圖（自動探索，{len(controls)} 項，更新於 {atlas.get('updated_at', '?')}）"]
    for c in picked:
        where = f"［{c['where']}］" if c.get("where") else ""
        sc = f" 快捷鍵 `{c['shortcut']}`" if c.get("shortcut") else ""
        lines.append(f"- {c['kind']}：{c['name']}{where}{sc}")
    return "\n".join(lines)
