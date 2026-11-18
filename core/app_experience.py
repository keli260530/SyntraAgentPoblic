# -*- coding: utf-8 -*-
"""
成功經驗記憶（App Experience）：做成功一次就記住步驟，下次照著做。

每一輪對話結束時，如果
- 有操作某個軟體（要求或工具參數提到手冊裡的軟體，或用了開軟體／視窗操作工具），
- 每個工具都執行成功，而且模型有給出正常結論（不是步數用完），
就把「使用者要求 → 依序呼叫了哪些工具（參數已截短）」存進 data/app_experience/<app>.jsonl。

下次遇到相似要求（同一個軟體＋字詞相似度夠高），把最像的 1～2 筆放進提示詞當範例。
相似度用中文字元 bigram 的 Jaccard，不依賴嵌入模型，離線、毫秒級。
機密字串在寫入前會先經過 sanitize（由呼叫端傳入 security_guard.sanitize_secrets）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import app_playbooks

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "app_experience"
MAX_PER_APP = 40
MIN_SIMILARITY = 0.18
_APP_TOOLS = {
    "launch_application", "open_file_in_app", "write_text_file", "dispatch_ai_coding_prompt",
    "ui_invoke", "ui_type", "ui_click", "click_screen", "type_text", "computer_key",
    "inspect_accessibility_tree", "send_ide_feedback", "type_in_app",
}
# 純觀察類工具不必記進步驟（重播時模型自己會看）
_SKIP_IN_RECIPE = {"list_windows", "capture_desktop_screen", "inspect_accessibility_tree", "ocr_screen",
                   "list_installed_software", "app_howto", "learn_app_ui", "computer_wait",
                   # 查資料不算「操作軟體」：只上網搜尋／讀說明的回合不該被記成某軟體的成功做法
                   "web_search", "web_fetch", "read_app_help", "research_app_howto", "save_app_knowledge"}
_FAIL_MARKERS = ('"ok": false', "'ok': false", "❌", "error", "失敗", "找不到", "blocked_by", "拒絕")


def _bigrams(text: str) -> set:
    t = re.sub(r"\s+", "", (text or "").lower())
    return {t[i:i + 2] for i in range(len(t) - 1)} or ({t} if t else set())


def similarity(a: str, b: str) -> float:
    x, y = _bigrams(a), _bigrams(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def _clip_args(args: Dict[str, Any], n: int = 160) -> Dict[str, Any]:
    out = {}
    for k, v in (args or {}).items():
        if k.startswith("__"):
            continue
        s = v if isinstance(v, (int, float, bool)) or v is None else str(v)
        if isinstance(s, str) and len(s) > n:
            s = s[:n] + "…"
        out[k] = s
    return out


def _step_failed(step: Dict[str, Any]) -> bool:
    if step.get("failed"):
        return True
    if step.get("status") not in (None, "DONE"):
        return True
    prev = str(step.get("result_preview", ""))[:300].lower()
    return any(m.lower() in prev for m in _FAIL_MARKERS)


def detect_app(user_message: str, tool_steps: List[Dict[str, Any]]) -> Optional[str]:
    app = app_playbooks.find_app(user_message)
    if app:
        return app
    for st in tool_steps:
        app = app_playbooks.find_app(json.dumps(st.get("args", {}), ensure_ascii=False))
        if app:
            return app
    # 手冊以外的軟體（ChatGPT、OBS…）：用學習模組認（以前用過而登記的名稱、或這一輪工具參數裡的軟體名稱）
    try:
        from . import app_learning
        return app_learning.primary_app(user_message, tool_steps)
    except Exception:
        return None


def record_turn(user_message: str, tool_steps: List[Dict[str, Any]], final_ok: bool,
                sanitize: Callable[[str], str] = lambda s: s, data_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """一輪結束時呼叫；符合條件才記錄，回傳記下的那筆（或 None）。"""
    if not final_ok or not tool_steps:
        return None
    # 至少要有一個「真的動手操作」的步驟（只看視窗、讀結構樹不算）
    if not any(st.get("tool") in _APP_TOOLS and st.get("tool") not in _SKIP_IN_RECIPE for st in tool_steps):
        return None
    # 查資料／看畫面這類步驟失敗（例如搜尋暫時被限制）不影響「操作本身成功」
    if any(_step_failed(st) for st in tool_steps if st.get("tool") not in _SKIP_IN_RECIPE):
        return None
    app = detect_app(user_message, tool_steps)
    if not app:
        return None
    steps = [{"tool": st["tool"], "args": _clip_args(st.get("args", {}))}
             for st in tool_steps if st.get("tool") not in _SKIP_IN_RECIPE]
    if not steps:
        return None
    entry = {"app": app, "request": sanitize(user_message.strip())[:300],
             "steps": json.loads(sanitize(json.dumps(steps, ensure_ascii=False))),
             "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    d = data_dir or _DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{app}.jsonl"
    entries = load(app, d)
    # 幾乎一樣的要求只留最新一筆
    entries = [e for e in entries if similarity(e["request"], entry["request"]) < 0.85]
    entries.append(entry)
    entries = entries[-MAX_PER_APP:]
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
    return entry


def load(app: str, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = (data_dir or _DATA_DIR) / f"{app}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def find_similar(app: str, request: str, k: int = 2, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    scored = [(similarity(e["request"], request), e) for e in load(app, data_dir)]
    scored = [(s, e) for s, e in scored if s >= MIN_SIMILARITY]
    scored.sort(key=lambda x: -x[0])
    return [dict(e, similarity=round(s, 2)) for s, e in scored[:k]]


def render(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return ""
    lines = ["#### ✅ 以前成功過的做法（照這個順序做，參數依這次要求調整）"]
    for e in entries:
        lines.append(f"- 要求「{e['request'][:80]}」（{e['saved_at']}）：")
        for i, st in enumerate(e["steps"], 1):
            lines.append(f"  {i}. `{st['tool']}` {json.dumps(st['args'], ensure_ascii=False)}")
    return "\n".join(lines)


def forget(app: str, data_dir: Optional[Path] = None) -> int:
    path = (data_dir or _DATA_DIR) / f"{app}.jsonl"
    n = len(load(app, data_dir))
    if path.exists():
        path.unlink()
    return n
