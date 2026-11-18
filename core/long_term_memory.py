# -*- coding: utf-8 -*-
"""
長期記憶：跨對話記住使用者的偏好與重要事實（只存在本機 data/long_term_memory.json）。

- 模型可用三個工具：memory_save（記住）、memory_forget（忘掉）、memory_list（列出）。
- 每一輪對話開始時，把記憶以「[長期記憶]」區塊附在使用者訊息前，讓新對話也知道。
- 存檔前會先過一次金鑰 / 密碼遮罩，避免把機密寫進記憶。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_ITEMS = 200
PROMPT_MAX_CHARS = 2_000

TOOL_SPECS: List[Dict[str, Any]] = [
    {"name": "memory_save",
     "description": "把一件需要長期記住的事存進長期記憶（跨對話有效）。只在使用者明確要你記住、"
                    "或表達穩定偏好（例如稱呼、語言、常用專案路徑、做事習慣）時使用；不要存一次性的內容或任何密碼金鑰。",
     "parameters": {"type": "object", "properties": {
         "fact": {"type": "string", "description": "要記住的事，一句話寫清楚，例如：使用者偏好用繁體中文、回答要簡短"}},
         "required": ["fact"]}},
    {"name": "memory_forget",
     "description": "刪除一筆長期記憶。id 可從 memory_list 取得；也可以給一段文字，刪除內容包含它的記憶。",
     "parameters": {"type": "object", "properties": {
         "id": {"type": "string", "description": "記憶 id 或要比對的文字"}}, "required": ["id"]}},
    {"name": "memory_list",
     "description": "列出目前所有長期記憶（含 id）。",
     "parameters": {"type": "object", "properties": {}}},
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}
READ_ONLY = {"memory_list"}


def _norm(s: str) -> str:
    return "".join(s.lower().split())


class LongTermMemory:
    def __init__(self, path: Optional[Path] = None, sanitize: Optional[Callable[[str], str]] = None):
        self.path = path or (Path(__file__).resolve().parent.parent / "data" / "long_term_memory.json")
        self.sanitize = sanitize or (lambda s: s)
        self._lock = threading.Lock()

    def _load(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self, items: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._load()

    def add(self, fact: str, source: str = "agent") -> Tuple[bool, str]:
        fact = self.sanitize((fact or "").strip())[:500]
        if not fact:
            return False, "內容是空的，沒有存。"
        with self._lock:
            items = self._load()
            if any(_norm(i["text"]) == _norm(fact) for i in items):
                return False, "這件事已經記住了。"
            items.append({"id": uuid.uuid4().hex[:8], "text": fact, "source": source,
                          "created": time.strftime("%Y-%m-%d %H:%M")})
            self._save(items[-MAX_ITEMS:])
        return True, f"已記住：{fact}"

    def remove(self, key: str) -> Tuple[int, List[str]]:
        key = (key or "").strip()
        with self._lock:
            items = self._load()
            keep, gone = [], []
            for i in items:
                if key and (i["id"] == key or _norm(key) in _norm(i["text"])):
                    gone.append(i["text"])
                else:
                    keep.append(i)
            if gone:
                self._save(keep)
        return len(gone), gone

    def as_prompt(self) -> str:
        items = self.list()
        if not items:
            return ""
        lines, used = [], 0
        for i in reversed(items):  # 新的優先
            line = f"- {i['text']}"
            if used + len(line) > PROMPT_MAX_CHARS:
                break
            lines.append(line)
            used += len(line)
        return "[長期記憶：以下是使用者先前要你記住的事，請自然地遵守，不必複述]\n" + "\n".join(reversed(lines))

    # ---- 給 agent 迴圈用 -------------------------------------------------------
    def run_tool(self, name: str, args: Dict[str, Any]) -> str:
        if name == "memory_save":
            ok, msg = self.add(str(args.get("fact", "")))
            return ("✅ " if ok else "ℹ️ ") + msg
        if name == "memory_forget":
            n, gone = self.remove(str(args.get("id", "")))
            return f"✅ 已刪除 {n} 筆：" + "；".join(gone) if n else "ℹ️ 找不到符合的記憶。"
        if name == "memory_list":
            items = self.list()
            return json.dumps(items, ensure_ascii=False, indent=1) if items else "（目前沒有長期記憶）"
        return f"❌ 未知的記憶工具：{name}"


_default: Optional[LongTermMemory] = None


def get_memory(sanitize: Optional[Callable[[str], str]] = None) -> LongTermMemory:
    global _default
    if _default is None:
        _default = LongTermMemory(sanitize=sanitize)
    elif sanitize is not None:
        _default.sanitize = sanitize
    return _default
