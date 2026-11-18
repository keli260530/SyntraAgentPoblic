"""
core/habit_sync_engine.py
=========================
用戶習慣與偏好快速同步引擎 (Habit & Persona Sync Engine)
透過兩種途徑極速萃取並同步你的個人習慣：
1. 本機 Chrome / Edge 零登入快照提取（免密碼、免 2FA，直接解析本機 SQLite 快照）
2. Google Workspace 雲端日曆/文件/郵件習慣深度萃取
自動產出 `data/user_habit_profile.json`，作為 Agent 決策的常駐認知背景。
"""

import os
import shutil
import sqlite3
import json
import time
from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional

class HabitSyncEngine:
    def __init__(
        self,
        profile_path: str = "data/user_habit_profile.json",
        snapshot_dir: str = "data/cache_snapshots"
    ):
        self.profile_path = profile_path
        self.snapshot_dir = snapshot_dir
        os.makedirs(self.snapshot_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)

    def _get_browser_history_path(self, browser: str = "chrome") -> Optional[str]:
        local_app = os.environ.get("LOCALAPPDATA", "")
        if browser.lower() == "chrome":
            path = os.path.join(local_app, "Google", "Chrome", "User Data", "Default", "History")
        elif browser.lower() == "edge":
            path = os.path.join(local_app, "Microsoft", "Edge", "User Data", "Default", "History")
        else:
            path = ""
        return path if os.path.exists(path) else None

    def sync_from_local_browser(self, browser: str = "chrome", limit_days: int = 14) -> Dict[str, Any]:
        """
        零登入同步：直接利用本機 Chrome/Edge 的歷史記錄快照分析個人高頻工具與作息。
        複製一份唯讀快照避開 Chrome 執行時的檔案鎖定 (database is locked)。
        """
        hist_file = self._get_browser_history_path(browser)
        if not hist_file:
            # 自動退回 edge
            hist_file = self._get_browser_history_path("edge")
            if not hist_file:
                return {"success": False, "error": "未找到本機 Chrome 或 Edge 歷史記錄檔"}

        snap_file = os.path.join(self.snapshot_dir, f"{browser}_history.db")
        try:
            shutil.copyfile(hist_file, snap_file)
        except Exception as e:
            return {"success": False, "error": f"複製瀏覽器歷史快照失敗: {e}"}

        profile_data = {
            "browser_source": browser,
            "top_domains": {},
            "google_workspace_usage": {"drive": 0, "docs": 0, "gmail": 0, "calendar": 0, "sheets": 0},
            "hourly_activity": {str(h): 0 for h in range(24)},
            "recent_search_keywords": []
        }

        try:
            with sqlite3.connect(snap_file) as conn:
                cursor = conn.cursor()
                
                # 1. 查詢訪問次數最高的網域 (Top Domains)
                cursor.execute("""
                    SELECT url, visit_count, last_visit_time
                    FROM urls
                    ORDER BY visit_count DESC
                    LIMIT 200
                """)
                rows = cursor.fetchall()

                for url, v_count, last_time in rows:
                    parsed = urlparse(url)
                    domain = parsed.netloc.lower()
                    if domain:
                        profile_data["top_domains"][domain] = profile_data["top_domains"].get(domain, 0) + v_count
                    
                    # 統計 Google 服務依賴度
                    if "mail.google.com" in domain:
                        profile_data["google_workspace_usage"]["gmail"] += v_count
                    elif "drive.google.com" in domain:
                        profile_data["google_workspace_usage"]["drive"] += v_count
                    elif "docs.google.com/document" in url:
                        profile_data["google_workspace_usage"]["docs"] += v_count
                    elif "docs.google.com/spreadsheets" in url:
                        profile_data["google_workspace_usage"]["sheets"] += v_count
                    elif "calendar.google.com" in domain:
                        profile_data["google_workspace_usage"]["calendar"] += v_count

                # 2. 查詢常搜關鍵字
                try:
                    cursor.execute("""
                        SELECT term FROM keyword_search_terms
                        ORDER BY id DESC
                        LIMIT 30
                    """)
                    profile_data["recent_search_keywords"] = [r[0] for r in cursor.fetchall()]
                except Exception:
                    pass

        except Exception as e:
            return {"success": False, "error": f"解析 SQLite 失敗: {e}"}
        finally:
            if os.path.exists(snap_file):
                try:
                    os.remove(snap_file)
                except Exception:
                    pass

        # 整理 Top 10 核心網域
        sorted_domains = sorted(profile_data["top_domains"].items(), key=lambda x: x[1], reverse=True)[:10]
        profile_data["top_domains"] = dict(sorted_domains)

        self._merge_and_save_profile({"browser_habits": profile_data})
        return {"success": True, "habits": profile_data}

    def sync_from_google_suite(self, google_suite) -> Dict[str, Any]:
        """
        從 Google Workspace 雲端提取工作習慣（日曆作息、近期專案文件、聯絡人）
        """
        if not google_suite.is_authenticated():
            return {"success": False, "error": "Google 帳號尚未授權，請先配置 credentials.json"}

        cloud_habits = {
            "upcoming_meetings_count": 0,
            "recent_drive_projects": [],
            "daily_meeting_density": {}
        }

        # 1. 抓取近期日曆事件推估上下班與開會習慣
        try:
            events = google_suite.gcalendar_list_events(days_ahead=7, max_results=20)
            cloud_habits["upcoming_meetings_count"] = len(events)
            cloud_habits["events_preview"] = [f"{e['start']} | {e['summary']}" for e in events[:5]]
        except Exception:
            pass

        # 2. 抓取雲端硬碟最近修改檔案
        try:
            files = google_suite.gdrive_search_files(max_results=10)
            cloud_habits["recent_drive_projects"] = [f["name"] for f in files]
        except Exception:
            pass

        self._merge_and_save_profile({"google_workspace_habits": cloud_habits})
        return {"success": True, "habits": cloud_habits}

    def _merge_and_save_profile(self, partial_data: Dict[str, Any]):
        """將新萃取的習慣與現有畫像合併保存"""
        current_profile = {}
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    current_profile = json.load(f)
            except Exception:
                current_profile = {}

        current_profile.update(partial_data)
        current_profile["last_synced_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(current_profile, f, ensure_ascii=False, indent=2)

    def load_prompt_context(self) -> str:
        """生成供 Agent 決策時載入的精煉個人習慣 Prompt"""
        if not os.path.exists(self.profile_path):
            return ""

        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            lines = ["\n### 使用者個人習慣與高頻工作流背景（已自動同步）："]
            b_habits = data.get("browser_habits", {})
            if b_habits.get("top_domains"):
                top_apps = ", ".join(list(b_habits["top_domains"].keys())[:5])
                lines.append(f"- **高頻存取服務**：{top_apps}")

            gw = b_habits.get("google_workspace_usage", {})
            active_gw = [k for k, v in gw.items() if v > 0]
            if active_gw:
                lines.append(f"- **常用的 Google 工具**：{', '.join(active_gw)}")

            g_habits = data.get("google_workspace_habits", {})
            if g_habits.get("recent_drive_projects"):
                lines.append(f"- **近期關注的雲端專案/文件**：{', '.join(g_habits['recent_drive_projects'][:3])}")

            return "\n".join(lines) + "\n"
        except Exception:
            return ""


# 全域單例
habit_sync_engine = HabitSyncEngine()
