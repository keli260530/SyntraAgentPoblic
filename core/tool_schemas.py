# -*- coding: utf-8 -*-
"""
從 AgentBrain.SYSTEM_PROMPT 的「可用工具清單」自動產生原生 tool calling 用的 JSON Schema。

清單每行格式：
    - `tool_name`: `{"參數": 範例值, ...}` -> 說明文字
型別由範例值推斷；ToolCallECC.TOOL_SCHEMAS 有定義的工具，以其 required / types 為準。
這樣只要維護 system prompt 一處，文字協議與原生協議的工具清單就永遠一致。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .tool_ecc import ToolCallECC

_LINE = re.compile(r"^- `(?P<name>[a-zA-Z_][\w]*)`: `(?P<example>\{.*\})` -> (?P<desc>.+)$")

_PY2JSON = {int: "integer", float: "number", bool: "boolean", str: "string", list: "array", dict: "object"}

# 只讀、不改變任何狀態的工具：同一回合多個時可以並行執行
READ_ONLY_TOOLS = {
    "list_windows", "inspect_accessibility_tree", "ui_read_text", "inspect_window_background",
    "capture_desktop_screen", "web_search", "web_fetch", "audit_system_security",
    "get_network_defense_status", "list_installed_skills", "browser_extract", "browser_screenshot",
    "list_installed_software",
    "get_file_integrity_status", "get_anti_takeover_status", "get_storm_defense_status",
    "get_self_defense_status", "gmail_list_messages", "gmail_read_message", "gdrive_search_files",
    "gcalendar_list_events",
}


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    for py, js in _PY2JSON.items():
        if isinstance(value, py):
            return js
    return "string"


def _param_schema(example: Any, forced_type=None) -> Dict[str, Any]:
    js_type = _PY2JSON.get(forced_type) if forced_type else _json_type(example)
    schema: Dict[str, Any] = {"type": js_type or "string"}
    if js_type == "array":
        item_t = _json_type(example[0]) if isinstance(example, list) and example else "string"
        schema["items"] = {"type": item_t}
    if js_type == "string" and isinstance(example, str):
        if "|" in example and " " not in example and len(example) < 60:
            schema["enum"] = example.split("|")
        else:
            schema["description"] = f"例：{example[:60]}"
    elif example not in (None, "", [], {}):
        schema["description"] = f"例：{json.dumps(example, ensure_ascii=False)[:60]}"
    return schema


def build_tool_specs(system_prompt: str) -> List[Dict[str, Any]]:
    """回傳中性格式 [{name, description, parameters}]，供 LLMClient 轉成各家格式。"""
    specs: List[Dict[str, Any]] = []
    seen = set()
    for raw in system_prompt.splitlines():
        m = _LINE.match(raw.strip())
        if not m or m["name"] in seen:
            continue
        name = m["name"]
        seen.add(name)
        desc = re.sub(r"\*\*|【[^】]*】", "", m["desc"]).strip()
        try:
            example = json.loads(m["example"])
            if not isinstance(example, dict):
                example = {}
            parse_ok = True
        except json.JSONDecodeError:
            example, parse_ok = {}, False

        ecc = ToolCallECC.TOOL_SCHEMAS.get(name, {})
        types = ecc.get("types", {})
        props = {k: _param_schema(v, types.get(k)) for k, v in example.items()}
        for k, t in types.items():  # ECC 有定義、但範例沒寫到的參數
            props.setdefault(k, {"type": _PY2JSON.get(t, "string")})
        required = [r for r in ecc.get("required", []) if r in props]

        params: Dict[str, Any] = {"type": "object", "properties": props}
        if required:
            params["required"] = required
        if not parse_ok:
            params["additionalProperties"] = True
        specs.append({"name": name, "description": desc[:900], "parameters": params})
    return specs
