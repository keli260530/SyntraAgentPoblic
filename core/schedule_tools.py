# -*- coding: utf-8 -*-
"""
自主排程工具（Schedule Tools）：讓代理根據使用者在輸入框的指令（「10分鐘後」「今天14:30」「明天早上9點」「每30分鐘」）
自主建立一次性或週期性排程任務。
"""
from __future__ import annotations

import datetime
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schedule_manager import ScheduleManager

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "create_schedule",
        "description": "當使用者要求「之後做某事、幾分鐘後、指定時間（如 14:30 / 明天 09:00）開始執行、或定期重複執行」時，自主建立排程任務。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "排程簡短標題"},
                "prompt": {"type": "string", "description": "時間到時要自動執行的完整指令"},
                "delay_minutes": {"type": "number", "description": "幾分鐘後開始（例如 10 或 0.5）；與 run_at 擇一"},
                "run_at": {"type": "string", "description": "指定開始時間，如 '2026-11-17 14:30'、'14:30'、'明天 09:00'"},
                "interval_minutes": {"type": "integer", "description": "若為重複排程，每次間隔分鐘數（預設 60）"},
                "one_shot": {"type": "boolean", "description": "是否為只執行一次的排程（預設 true；週期排程設 false）"},
            },
            "required": ["name", "prompt"],
        },
    },
    {
        "name": "list_schedules",
        "description": "查看目前已建立的所有排程任務（含下次執行時間、是否啟用）。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_schedule",
        "description": "依排程 ID 刪除不需要的排程任務。",
        "parameters": {
            "type": "object",
            "properties": {"sched_id": {"type": "string", "description": "要刪除的排程 ID"}},
            "required": ["sched_id"],
        },
    },
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}


def parse_run_at(run_at: str, now_dt: Optional[datetime.datetime] = None) -> Optional[float]:
    """將常見時間字串（'YYYY-MM-DD HH:MM', 'HH:MM', '明天 09:00'）轉為 Unix timestamp。"""
    raw = (run_at or "").strip()
    if not raw:
        return None
    now_dt = now_dt or datetime.datetime.now()

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.datetime.strptime(raw, fmt).timestamp()
        except ValueError:
            pass

    m_hm = re.search(r"(\d{1,2})\s*[:：點]\s*(\d{1,2})?", raw)
    if m_hm:
        hh = int(m_hm.group(1))
        mm = int(m_hm.group(2) or 0)
        if ("下午" in raw or "晚上" in raw or "pm" in raw.lower()) and hh < 12:
            hh += 12
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            target = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if "明天" in raw or "明日" in raw:
                target += datetime.timedelta(days=1)
            elif "後天" in raw:
                target += datetime.timedelta(days=2)
            elif target <= now_dt:
                target += datetime.timedelta(days=1)
            return target.timestamp()
    return None


async def run_tool(name: str, args: Dict[str, Any], manager: Optional[ScheduleManager] = None) -> Tuple[str, Optional[str]]:
    mgr = manager or ScheduleManager()
    args = args or {}

    if name == "list_schedules":
        items = mgr.list_schedules()
        return json.dumps({"ok": True, "schedules": items}, ensure_ascii=False), None

    if name == "delete_schedule":
        sid = str(args.get("sched_id") or "").strip()
        ok = mgr.delete_schedule(sid)
        return json.dumps({"ok": ok, "deleted_id": sid}, ensure_ascii=False), None

    if name == "create_schedule":
        title = str(args.get("name") or "排程任務").strip()
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return json.dumps({"ok": False, "error": "缺少要執行的任務內容 (prompt)"}, ensure_ascii=False), None

        one_shot = bool(args.get("one_shot", True))
        interval = max(1, int(args.get("interval_minutes") or 60))
        start_ts: Optional[float] = None

        if args.get("run_at"):
            start_ts = parse_run_at(str(args["run_at"]))
        elif args.get("delay_minutes") is not None:
            try:
                delay_sec = max(5.0, float(args["delay_minutes"]) * 60.0)
                start_ts = time.time() + delay_sec
            except Exception:
                pass

        if hasattr(mgr, "add_schedule"):
            try:
                task = mgr.add_schedule(
                    name=title,
                    prompt=prompt,
                    interval_minutes=interval,
                    start_at=start_ts,
                    one_shot=one_shot,
                )
            except TypeError:
                task = mgr.add_schedule(name=title, prompt=prompt, interval_minutes=interval)
        else:
            return json.dumps({"ok": False, "error": "排程管理器尚未就緒"}, ensure_ascii=False), None

        next_str = datetime.datetime.fromtimestamp(task.get("next_run", time.time())).strftime("%Y-%m-%d %H:%M:%S")
        return json.dumps({
            "ok": True,
            "schedule": task,
            "next_run_local": next_str,
            "one_shot": one_shot,
        }, ensure_ascii=False), None

    return json.dumps({"ok": False, "error": f"未知排程工具：{name}"}, ensure_ascii=False), None
