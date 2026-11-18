# -*- coding: utf-8 -*-
"""
工具呼叫防呆 (Tool Guard) — 原生 function calling 路徑的校正層

舊的文字協議有 ToolCallECC 幫忙修名稱與型別，原生路徑卻是模型給什麼就執行什麼。
本機小模型常見的失誤在這裡先攔下來，能修的直接修，不能修的回一段「看得懂怎麼改」的說明：

1. 工具名稱：別名、大小寫、連字號、`functions.` 前綴、拼錯一兩個字 → 自動改成正確名稱；
   完全對不上 → 不執行，列出最接近的幾個名稱。
2. 參數：依工具定義 (JSON Schema) 修正鍵名（maxResults → max_results）、轉型（"5" → 5、"true" → True）、
   enum 大小寫；缺必填參數 → 不執行，回傳該工具的正確參數格式。
3. 空轉：同一個工具、同樣參數、連續得到同樣結果，還要再呼叫 → 不執行，請模型換做法或直接回覆。

只依賴標準庫與 ToolCallECC 的別名表。
"""
from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .tool_ecc import ToolCallECC

# 連續重複幾次（且結果相同）之後擋下
REPEAT_LIMIT = 2
# 這些工具本來就會連續重複（等待、按鍵、捲動、重新截圖），放寬
REPEAT_LIMIT_RELAXED = 5
_RELAXED = {
    "computer_wait", "computer_key", "computer_scroll", "click_screen", "wait_subagents",
    "capture_desktop_screen", "browser_screenshot", "ocr_screen",
}

_AUTO_FIX_CUTOFF = 0.84   # 相似度高於此值才自動改名
_SUGGEST_CUTOFF = 0.5


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _tokens(name: str) -> frozenset:
    return frozenset(t for t in re.split(r"[^a-z0-9]+", str(name).lower()) if t)


def _signature(name: str, args: Dict[str, Any]) -> str:
    try:
        return name + "|" + json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return name + "|" + repr(args)


def _brief_schema(spec: Dict[str, Any]) -> str:
    """把工具定義濃縮成一行給模型看：name(必填 a: string, 選填 b: integer)"""
    params = spec.get("parameters") or {}
    props = params.get("properties") or {}
    required = set(params.get("required") or [])
    parts = []
    for k, p in props.items():
        t = p.get("type", "string")
        if p.get("enum"):
            t = "|".join(map(str, p["enum"]))
        parts.append(f"{'必填' if k in required else '選填'} {k}: {t}")
    return f"{spec.get('name')}({', '.join(parts)})"


def _coerce(value: Any, schema: Dict[str, Any]) -> Tuple[Any, bool]:
    """依 schema 型別轉型。回傳 (新值, 是否有改)。轉不了就原樣回傳。"""
    t = schema.get("type")
    try:
        if t == "integer" and not isinstance(value, bool):
            if isinstance(value, int):
                return value, False
            if isinstance(value, float):
                return int(round(value)), True
            if isinstance(value, str):
                v = value.strip()
                return (int(v, 16) if v.lower().startswith("0x") else int(round(float(v)))), True
        elif t == "number" and not isinstance(value, bool):
            if isinstance(value, (int, float)):
                return value, False
            if isinstance(value, str):
                return float(value.strip()), True
        elif t == "boolean":
            if isinstance(value, bool):
                return value, False
            if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "yes", "no"):
                return value.strip().lower() in ("true", "1", "yes"), True
            if isinstance(value, int):
                return bool(value), True
        elif t == "string":
            if isinstance(value, str):
                return value, False
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return str(value), True
        elif t == "array":
            if isinstance(value, list):
                return value, False
            if isinstance(value, str):
                v = value.strip()
                if v.startswith("["):
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return parsed, True
                return [value], True
        elif t == "object":
            if isinstance(value, dict):
                return value, False
            if isinstance(value, str) and value.strip().startswith("{"):
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed, True
    except (ValueError, TypeError):
        pass
    return value, False


class ToolGuard:
    """一個使用者回合用一個。specs 要給「完整」工具清單（不是篩選後給模型看的那份）。"""

    def __init__(self, specs: List[Dict[str, Any]]):
        self.specs: Dict[str, Dict[str, Any]] = {s["name"]: s for s in specs or [] if s.get("name")}
        self._by_norm = {_norm(n): n for n in self.specs}
        self._last_sig: Optional[str] = None
        self._last_out: Optional[str] = None
        self._streak = 0

    # ------------------------------------------------------------ 名稱
    def resolve_name(self, name: str) -> Tuple[Optional[str], List[str]]:
        """回傳 (正確名稱或 None, 建議名稱清單)。沒有工具清單時不做任何判斷。"""
        if not self.specs or name in self.specs or name in ToolCallECC.TOOL_SCHEMAS:
            return name, []     # 內建工具表認得的也放行（有些工具能執行但不在這次的定義清單裡）
        raw = str(name or "").strip()
        for prefix in ("functions.", "function.", "tools.", "tool."):
            if raw.lower().startswith(prefix):
                raw = raw[len(prefix):]
        if raw in self.specs:
            return raw, []
        alias = ToolCallECC.TOOL_ALIASES.get(raw.lower())
        if alias in self.specs:
            return alias, []
        hit = self._by_norm.get(_norm(raw))
        if hit:
            return hit, []
        # 單字順序顛倒（search_web → web_search）：單字組合唯一相同就直接改
        tokens = _tokens(raw)
        same = [n for n in self.specs if _tokens(n) == tokens]
        if tokens and len(same) == 1:
            return same[0], []
        close = difflib.get_close_matches(raw.lower(), list(self.specs), n=4, cutoff=_SUGGEST_CUTOFF)
        if close:
            best = difflib.SequenceMatcher(None, raw.lower(), close[0]).ratio()
            second = difflib.SequenceMatcher(None, raw.lower(), close[1]).ratio() if len(close) > 1 else 0.0
            if best >= _AUTO_FIX_CUTOFF and best - second >= 0.05:
                return close[0], []
        # 建議清單再補上「有共同單字」的工具（send_gmail → gmail_send_message）
        shared = sorted((n for n in self.specs if n not in close and tokens & _tokens(n)),
                        key=lambda n: -len(tokens & _tokens(n)))
        return None, (close + shared)[:4]

    # ------------------------------------------------------------ 參數
    def fix_args(self, name: str, args: Any) -> Tuple[Dict[str, Any], List[str], str]:
        """回傳 (修正後參數, 修正紀錄, 錯誤訊息)。錯誤訊息非空代表不該執行。"""
        notes: List[str] = []
        if not isinstance(args, dict):
            args = {}
            notes.append("參數不是物件，已改成空物件")
        spec = self.specs.get(name)
        if not spec:
            return args, notes, ""
        params = spec.get("parameters") or {}
        props: Dict[str, Dict[str, Any]] = params.get("properties") or {}
        if not props:
            return args, notes, ""

        fixed: Dict[str, Any] = {}
        prop_norm = {_norm(k): k for k in props}
        for k, v in args.items():
            key = k
            if k not in props:
                cand = prop_norm.get(_norm(k))
                if cand and cand not in args:
                    key = cand
                    notes.append(f"參數名稱修正：{k} → {cand}")
            fixed[key] = v

        problems: List[str] = []
        for k, schema in props.items():
            if k not in fixed:
                continue
            v, changed = _coerce(fixed[k], schema)
            if changed:
                notes.append(f"參數 {k} 型別修正：{fixed[k]!r} → {v!r}")
                fixed[k] = v
            enum = schema.get("enum")
            if enum and v not in enum:
                match = next((e for e in enum if str(e).lower() == str(v).strip().lower()), None)
                if match is not None:
                    fixed[k] = match
                    notes.append(f"參數 {k} 修正：{v!r} → {match!r}")
                else:
                    problems.append(f"參數 {k} 的值 {v!r} 不在允許範圍（{' / '.join(map(str, enum))}）")

        missing = [r for r in (params.get("required") or [])
                   if r not in fixed or fixed[r] is None or (isinstance(fixed[r], str) and not fixed[r].strip())]
        if missing:
            problems.insert(0, f"缺少必填參數：{', '.join(missing)}")
        if problems:
            return fixed, notes, (f"❌ 工具 `{name}` 沒有執行，因為{'；'.join(problems)}。\n"
                                  f"正確格式：{_brief_schema(spec)}\n請補齊或修正參數後重新呼叫。")
        return fixed, notes, ""

    # ------------------------------------------------------------ 對外
    def prepare(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """執行前檢查一批呼叫。回傳新的 call 清單：名稱與參數已修正；
        不該執行的會帶 `guard_error`（上層直接把它當工具結果回給模型）。"""
        out: List[Dict[str, Any]] = []
        for c in calls:
            c = dict(c)
            notes = list(c.get("ecc_corrections") or [])
            args = c.get("args")
            if isinstance(args, dict) and "__raw_arguments__" in args:
                out.append(c)      # 參數連 JSON 都不是：上層已有專門的錯誤訊息
                continue
            name, suggestions = self.resolve_name(c.get("name", ""))
            if name is None:
                hint = f"最接近的工具：{', '.join(suggestions)}。" if suggestions else ""
                c["guard_error"] = (f"❌ 沒有名為 `{c.get('name')}` 的工具，所以沒有執行。{hint}"
                                    "請從工具定義中挑一個正確的名稱重新呼叫。")
                c["args"] = args if isinstance(args, dict) else {}
                out.append(c)
                continue
            if name != c.get("name"):
                notes.append(f"工具名稱修正：{c.get('name')} → {name}")
                c["name"] = name
            c["args"], arg_notes, err = self.fix_args(name, args)
            notes.extend(arg_notes)
            if not err:
                limit = REPEAT_LIMIT_RELAXED if name in _RELAXED else REPEAT_LIMIT
                if self._streak >= limit and _signature(name, c["args"]) == self._last_sig:
                    err = (f"🔁 你已經連續 {self._streak} 次用完全相同的參數呼叫 `{name}`，每次結果都一樣，"
                           "這次沒有再執行。請改用不同的參數或別的工具；"
                           "如果資料已經足夠，就直接用繁體中文回覆使用者。")
            if err:
                c["guard_error"] = err
            if notes:
                c["ecc_corrections"] = notes
            out.append(c)
        return out

    def record(self, call: Dict[str, Any], output: str) -> None:
        """工具真的執行完之後呼叫，用來偵測「同樣呼叫、同樣結果」的空轉。"""
        sig = _signature(call.get("name", ""), call.get("args") or {})
        if sig == self._last_sig and output == self._last_out:
            self._streak += 1
        else:
            self._last_sig, self._last_out, self._streak = sig, output, 1
