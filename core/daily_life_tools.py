# -*- coding: utf-8 -*-
"""
core/daily_life_tools.py
========================
直接內建於主 Agent 的日常電腦生活助手工具集：
1. daily_organize_files  ：智慧整理桌面 (Desktop) 或下載區 (Downloads)，依副檔名與用途自動分類歸檔，並記錄復原清單。
2. daily_undo_organize   ：一鍵還原最近一次自動整理的檔案回原位。
3. daily_switch_scene    ：一鍵切換日常用電腦情境模式（work 專注工作 / meeting 開會簡報 / entertainment 娛樂追劇 / rest 護眼休息）。
4. daily_wellbeing_report：結合 EpisodicTimelineMemory 分析今日電腦使用時間分佈與用眼健康報告。
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.user_profile_manager import user_profile_manager

DAILY_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "daily_organize_files",
        "description": "整理桌面 (desktop) 或下載資料夾 (downloads) 散落的檔案，自動按類別（圖片與截圖、文件與帳單、壓縮檔、安裝包、影音、程式碼）歸檔至子資料夾，並支援 dry_run 預覽與事後一鍵還原。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "要整理的目標：'downloads'（下載區）、'desktop'（桌面）或自訂資料夾路徑",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "True 代表只預覽會怎麼搬移而不實際移動；False 代表立即執行整理（預設 False）",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "daily_undo_organize",
        "description": "一鍵復原最近一次 daily_organize_files 搬移的所有檔案回原本位置。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "daily_switch_scene",
        "description": "切換日常用電腦情境模式：'work'（專注工作）、'meeting'（開會簡報，開啟勿擾）、'entertainment'（下班娛樂/遊戲，開啟防打擾）、'rest'（護眼休息提醒）。"
                       "注意：meeting／entertainment／rest 會開啟免打擾，之後 Syntra 不能再操作視窗、滑鼠、鍵盤，直到使用者關掉。"
                       "只有使用者明確說要切換情境（例如「切到休息模式」）才用，不要自己判斷使用者累了就切。",
        "parameters": {
            "type": "object",
            "properties": {
                "scene": {
                    "type": "string",
                    "description": "情境代號：'work' | 'meeting' | 'entertainment' | 'rest'",
                }
            },
            "required": ["scene"],
        },
    },
    {
        "name": "daily_wellbeing_report",
        "description": "統計並回報使用者今日在電腦上各類軟體（工作開發、瀏覽器、娛樂、通訊）的使用時間分佈與護眼健康建議。",
        "parameters": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "統計過去幾小時內的活動，預設 12 小時",
                }
            },
        },
    },
]

DAILY_TOOL_NAMES = {t["name"] for t in DAILY_TOOL_SPECS}
DAILY_READ_ONLY = {"daily_wellbeing_report"}

_CATEGORY_MAP: Dict[str, Tuple[str, ...]] = {
    "圖片與截圖": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico", ".heic"),
    "文件與帳單": (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".txt", ".md", ".odt"),
    "壓縮與封存": (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"),
    "安裝包與執行檔": (".msi", ".exe", ".iso", ".Appx", ".msix"),
    "影音媒體": (".mp4", ".mkv", ".mov", ".avi", ".mp3", ".wav", ".flac", ".m4a"),
    "程式碼與資料": (".py", ".js", ".ts", ".json", ".yaml", ".yml", ".sql", ".html", ".css"),
}


def _classify_extension(ext: str) -> Optional[str]:
    ext_l = ext.lower()
    for folder_name, exts in _CATEGORY_MAP.items():
        if ext_l in exts:
            return folder_name
    return None


def _history_log_path() -> Path:
    return user_profile_manager.profile_dir / "file_organize_history.json"


def organize_directory(target: str, dry_run: bool = False) -> Dict[str, Any]:
    t_low = (target or "downloads").strip().lower()
    if t_low == "downloads":
        folder = Path.home() / "Downloads"
    elif t_low == "desktop":
        folder = Path.home() / "Desktop"
    else:
        folder = Path(target).expanduser().resolve()

    if not folder.exists() or not folder.is_dir():
        return {"ok": False, "error": f"目標資料夾不存在：{folder}"}

    if user_profile_manager.is_protected_profile_path(folder):
        return {"ok": False, "error": "安全攔截：不允許對 user_profile 個資保護夾執行自動歸檔"}

    moves: List[Dict[str, str]] = []
    skipped = 0

    for item in folder.iterdir():
        if not item.is_file():
            continue
        # 略過捷徑與隱藏系統檔
        if item.name.startswith(".") or item.suffix.lower() in (".lnk", ".url", ".ini"):
            skipped += 1
            continue
        cat = _classify_extension(item.suffix)
        if not cat:
            skipped += 1
            continue

        dest_dir = folder / f"Syntra整理_{cat}"
        dest_path = dest_dir / item.name
        if dest_path.exists():
            stem, suf = item.stem, item.suffix
            dest_path = dest_dir / f"{stem}_{int(time.time())}{suf}"

        moves.append({"src": str(item), "dst": str(dest_path), "category": cat, "name": item.name})

    if not dry_run and moves:
        actual_moves = []
        for m in moves:
            try:
                dst_p = Path(m["dst"])
                dst_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(m["src"], m["dst"])
                actual_moves.append(m)
            except Exception:
                pass
        moves = actual_moves
        if moves:
            log_file = _history_log_path()
            history = []
            if log_file.exists():
                try:
                    history = json.loads(log_file.read_text(encoding="utf-8"))
                except Exception:
                    history = []
            history.append({
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "target": str(folder),
                "moves": moves,
            })
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text(json.dumps(history[-10:], ensure_ascii=False, indent=2), encoding="utf-8")

    by_cat: Dict[str, int] = {}
    for m in moves:
        by_cat[m["category"]] = by_cat.get(m["category"], 0) + 1

    return {
        "ok": True,
        "dry_run": dry_run,
        "folder": str(folder),
        "total_moved": len(moves),
        "skipped": skipped,
        "by_category": by_cat,
        "preview": [f"{m['name']} -> Syntra整理_{m['category']}/" for m in moves[:15]],
    }


def undo_last_organize() -> Dict[str, Any]:
    log_file = _history_log_path()
    if not log_file.exists():
        return {"ok": False, "error": "目前沒有可還原的整理紀錄"}
    try:
        history = json.loads(log_file.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "讀取整理紀錄失敗"}
    if not history:
        return {"ok": False, "error": "目前沒有可還原的整理紀錄"}

    last_batch = history.pop()
    restored = 0
    for m in reversed(last_batch.get("moves", [])):
        src_p = Path(m["src"])
        dst_p = Path(m["dst"])
        if dst_p.exists() and not src_p.exists():
            try:
                src_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst_p), str(src_p))
                restored += 1
            except Exception:
                pass
    log_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "restored_count": restored, "target": last_batch.get("target", "")}


def _minimize_distracting_windows() -> List[str]:
    """在進入工作或開會模式時，自動將前景/可見的娛樂視窗最小化（非破壞性，隨時可從工作列點開）"""
    minimized: List[str] = []
    try:
        import win32con
        import win32gui

        distraction_keywords = (
            "steam",
            "netflix",
            "youtube",
            "twitch",
            "bilibili",
            "potplayer",
            "vlc media player",
            "disney+",
        )

        def _enum_cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return
            t_low = title.lower()
            if any(k in t_low for k in distraction_keywords):
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                    minimized.append(title)
                except Exception:
                    pass

        win32gui.EnumWindows(_enum_cb, None)
    except Exception:
        pass
    return minimized


def switch_workspace_scene(
    scene: str,
    settings_manager: Optional[Any] = None,
    minimize_distractions: bool = True,
) -> Dict[str, Any]:
    s_key = (scene or "work").strip().lower()
    scenes = {
        "work": {
            "title": "💻 專注工作模式",
            "manual_dnd": False,
            "protect_homework_focus": True,
            "desc": "已開啟專注保護、自動收起娛樂干擾視窗，適合寫程式與處理文件。",
        },
        "meeting": {
            "title": "🎤 開會簡報模式",
            "manual_dnd": True,
            "protect_homework_focus": True,
            "desc": "已開啟全面勿擾模式 (DND) 與敏感視窗遮罩，暫停背景彈窗並收起無關娛樂視窗。",
        },
        "entertainment": {
            "title": "🎮 下班娛樂與追劇模式",
            "manual_dnd": True,
            "protect_homework_focus": False,
            "desc": "已開啟娛樂勿擾模式，背景監督自動降載，不打斷全螢幕遊戲或影片播放。",
        },
        "rest": {
            "title": "🌿 護眼休息模式",
            "manual_dnd": True,
            "protect_homework_focus": False,
            "desc": "已進入休息狀態，暫停代理干擾，建議離開螢幕遠眺 5 分鐘並補充水分。",
        },
    }
    cfg = scenes.get(s_key, scenes["work"])
    minimized_wins: List[str] = []
    if minimize_distractions and s_key in ("work", "meeting"):
        minimized_wins = _minimize_distracting_windows()

    if settings_manager is None:
        try:
            from core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        except Exception:
            settings_manager = None

    if settings_manager is not None:
        try:
            payload: Dict[str, Any] = {
                "dnd": {
                    "manual_dnd": cfg["manual_dnd"],
                    "protect_homework_focus": cfg["protect_homework_focus"],
                }
            }
            if s_key == "meeting":
                payload["security"] = {"redact_sensitive_windows": True}
            settings_manager.update_settings(payload)
        except Exception:
            pass
    # 同步記錄到 user_profile
    try:
        state_file = user_profile_manager.profile_dir / "current_scene.json"
        state_file.write_text(
            json.dumps(
                {
                    "scene": s_key,
                    "title": cfg["title"],
                    "minimized_windows": minimized_wins,
                    "switched_at": datetime.datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    return {
        "ok": True,
        "scene": s_key,
        "title": cfg["title"],
        "description": cfg["desc"],
        "minimized_windows": minimized_wins,
    }


def generate_wellbeing_report(hours: int = 12, db_path: str = "data/episodic_timeline.db") -> Dict[str, Any]:
    hours = max(1, min(int(hours or 12), 168))
    since_ts = time.time() - hours * 3600
    buckets = {"開發與工作": 0.0, "瀏覽器與查詢": 0.0, "通訊與協作": 0.0, "影音與娛樂": 0.0, "其他日常": 0.0}
    top_apps: Dict[str, float] = {}

    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT process_name, window_title, SUM(duration_seconds) FROM timeline WHERE timestamp >= ? GROUP BY process_name, window_title",
                    (since_ts,),
                )
                for proc, title, dur in cur.fetchall():
                    dur_val = float(dur or 0.0)
                    p_low = (proc or "").lower()
                    t_low = (title or "").lower()
                    top_apps[proc or "unknown"] = top_apps.get(proc or "unknown", 0.0) + dur_val

                    if any(k in p_low for k in ("code", "pycharm", "idea", "cursor", "devenv", "powershell", "wt", "cmd")):
                        buckets["開發與工作"] += dur_val
                    elif any(k in p_low for k in ("discord", "slack", "teams", "line", "telegram", "zoom")):
                        buckets["通訊與協作"] += dur_val
                    elif any(k in p_low for k in ("steam", "spotify", "vlc", "potplayer")) or any(
                        k in t_low for k in ("youtube", "netflix", "twitch", "bilibili")
                    ):
                        buckets["影音與娛樂"] += dur_val
                    elif any(k in p_low for k in ("chrome", "msedge", "firefox", "brave")):
                        buckets["瀏覽器與查詢"] += dur_val
                    else:
                        buckets["其他日常"] += dur_val
        except Exception:
            pass

    total_sec = sum(buckets.values())
    total_min = round(total_sec / 60.0, 1)
    sorted_apps = sorted(top_apps.items(), key=lambda x: x[1], reverse=True)[:5]

    advice = "目前用眼時長適中，維持良好節奏！"
    if total_min >= 180:
        advice = "⚠️ 您近期累計高強度使用電腦已超過 3 小時，建議起身活動筋骨、遠眺 20 秒並補充水分。"
    elif total_min >= 50:
        advice = "💡 已連續使用電腦一段時間，記得眨眼保濕並微調坐姿。"

    return {
        "ok": True,
        "hours_window": hours,
        "total_active_minutes": total_min,
        "category_minutes": {k: round(v / 60.0, 1) for k, v in buckets.items()},
        "top_processes": [{"process": k, "minutes": round(v / 60.0, 1)} for k, v in sorted_apps],
        "health_advice": advice,
    }


def run_daily_tool(name: str, args: Dict[str, Any], brain=None) -> str:
    settings_mgr = getattr(brain, "settings_manager", None) if brain else None
    if name == "daily_organize_files":
        res = organize_directory(
            target=str(args.get("target", "downloads")),
            dry_run=bool(args.get("dry_run", False)),
        )
        return json.dumps(res, ensure_ascii=False, indent=2)
    if name == "daily_undo_organize":
        res = undo_last_organize()
        return json.dumps(res, ensure_ascii=False, indent=2)
    if name == "daily_switch_scene":
        res = switch_workspace_scene(str(args.get("scene", "work")), settings_manager=settings_mgr)
        if isinstance(res, dict) and str(args.get("scene", "work")).strip().lower() in ("meeting", "entertainment", "rest"):
            res["dnd_notice"] = ("已開啟免打擾：Syntra 仍可正常實作與執行任務，但會全程在背景靜默運作，不會搶奪或佔用你的前端畫面。"
                                 "要恢復前景操作請說「切回工作模式」，或在右上角 ⚙️ 選單點「免打擾」。")
        return json.dumps(res, ensure_ascii=False, indent=2)
    if name == "daily_wellbeing_report":
        res = generate_wellbeing_report(hours=int(args.get("hours") or 12))
        return json.dumps(res, ensure_ascii=False, indent=2)
    return f"❌ 未知的日常工具：{name}"
