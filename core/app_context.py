# -*- coding: utf-8 -*-
"""
前後文：使用者這句沒講軟體名稱時，推斷他指的是「剛剛在用的那個軟體」。

例：上一句「打開 word」，這一句「新增檔案並輸入 Syntra 測試成功，不要儲存」
   → 指的是在 Word 裡開新文件打字，而不是在專案資料夾建立檔案。

推斷來源（由近到遠）：最近幾輪的工具呼叫（launch_application / open_file_in_app / type_in_app 的 app）
→ 最近幾則使用者訊息裡提到的軟體。注意：使用者在 Syntra 打字時前景視窗是 Syntra 自己，所以不看前景視窗。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import app_playbooks

# 「在軟體裡動手做」的動作詞（沒有這些詞的句子，例如閒聊或問問題，不套用前後文）
_IN_APP_ACTION_RE = re.compile(
    r"新增|開新|建立|輸入|打字|寫入|寫上|打上|貼上|插入|刪除|刪掉|選取|全選|複製|剪下|"
    r"粗體|斜體|底線|字體|字型|置中|存檔|儲存|另存|關閉|關掉|復原|取消|列印|"
    r"new|type|insert|paste|delete|select|save|close|undo",
    re.IGNORECASE)
_APP_ARG_TOOLS = ("launch_application", "open_file_in_app", "type_in_app", "app_howto", "learn_app_ui")
MAX_LOOKBACK = 8


def _app_from_tool_call(name: str, args: Any) -> Optional[str]:
    if name not in _APP_ARG_TOOLS:
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return None
    if not isinstance(args, dict):
        return None
    for k in ("app", "target"):
        v = str(args.get(k) or "")
        key = app_playbooks.find_app(v) or _bare_key(v)
        if key:
            return key
    return None


def _bare_key(text: str) -> Optional[str]:
    """「Word」「Excel」這種單獨的軟體名（手冊別名比較嚴格，這裡補抓）。"""
    t = (text or "").strip().lower()
    for key, pb in app_playbooks.PLAYBOOKS.items():
        if t == key or t == pb.get("name", "").lower():
            return key
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", t):
            return key
    return None


def _apps_in_text(text: str) -> List[str]:
    apps = app_playbooks.find_apps(text)
    if not apps and re.search(r"[一-鿿]", text or ""):
        k = _bare_key(text)
        if k:
            apps = [k]
    return apps


def infer_active_app(history: List[Dict[str, Any]], user_message: str) -> Optional[str]:
    """這句沒講軟體、而且是「動手做」的要求時，回傳最近在用的軟體 key；否則 None。"""
    if _apps_in_text(user_message):
        return None  # 使用者自己講了軟體，不用猜
    if not _IN_APP_ACTION_RE.search(user_message or ""):
        return None
    seen_user = 0
    for msg in reversed(history[-MAX_LOOKBACK * 3:]):
        role = msg.get("role")
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or tc
            key = _app_from_tool_call(fn.get("name", ""), fn.get("arguments", fn.get("args")))
            if key:
                return key
        content = msg.get("content")
        if isinstance(content, str) and role in ("user", "assistant"):
            text = content[-600:] if role == "user" else content[:400]
            apps = _apps_in_text(text)
            if apps:
                return apps[0]
        if role == "user":
            seen_user += 1
            if seen_user > 3:
                break
    return None


def context_note(app_key: str) -> str:
    name = (app_playbooks.PLAYBOOKS.get(app_key) or {}).get("name", app_key)
    return (f"[前後文：使用者前一輪用的是 {name}。這則要求沒有指定軟體，指的是「在 {name} 裡」操作"
            f"（例如「新增檔案」＝在 {name} 開新文件），不是在專案資料夾建立檔案。"
            f"請用 type_in_app（app=\"{app_key}\"）直接在 {name} 視窗操作；使用者沒說要存檔就不要存檔。]\n")
