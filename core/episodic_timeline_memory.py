"""
core/episodic_timeline_memory.py
================================
情境記憶與活動時空歷程引擎 (Episodic Timeline Memory)
追蹤前景活動視窗與焦點切換，記錄本機活動時間軸 (Timeline)，
支援本機 SQLite 持久化與關鍵字檢索。
讓桌面全職助手隨時掌握「你在何時做了什麼、瀏覽了哪個專案或網頁」，實現真正的上下文認知。
"""

import os
import time
import sqlite3
import threading
from typing import List, Dict, Any, Optional
import win32gui
import win32process
import psutil

class EpisodicTimelineMemory:
    def __init__(self, db_path: str = "data/episodic_timeline.db", sample_interval: float = 3.0):
        self.db_path = db_path
        self.sample_interval = sample_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_entry = {"title": "", "process_name": "", "pid": 0}
        self._lock = threading.Lock()
        
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    datetime_str TEXT,
                    window_title TEXT,
                    process_name TEXT,
                    process_id INTEGER,
                    duration_seconds REAL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON timeline(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_window_title ON timeline(window_title)")
            conn.commit()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _monitor_loop(self):
        last_switch_time = time.time()

        while self._running:
            try:
                hwnd = win32gui.GetForegroundWindow()
                if hwnd and win32gui.IsWindow(hwnd):
                    title = win32gui.GetWindowText(hwnd).strip()
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    
                    pname = ""
                    try:
                        pname = psutil.Process(pid).name()
                    except Exception:
                        pass

                    now = time.time()
                    if title and (title != self._last_entry["title"] or pname != self._last_entry["process_name"]):
                        # 視窗焦點切換，記錄前一個視窗的停留時間
                        if self._last_entry["title"]:
                            duration = now - last_switch_time
                            self._record_entry(
                                timestamp=last_switch_time,
                                window_title=self._last_entry["title"],
                                process_name=self._last_entry["process_name"],
                                pid=self._last_entry["pid"],
                                duration_seconds=round(duration, 2)
                            )

                        self._last_entry = {
                            "title": title,
                            "process_name": pname,
                            "pid": pid
                        }
                        last_switch_time = now
            except Exception:
                pass
            time.sleep(self.sample_interval)

    def _record_entry(self, timestamp: float, window_title: str, process_name: str, pid: int, duration_seconds: float):
        # 排除無意義的微小停留 (例如小於 1 秒)
        if duration_seconds < 1.0:
            return

        dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO timeline (timestamp, datetime_str, window_title, process_name, process_id, duration_seconds)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (timestamp, dt_str, window_title, process_name, pid, duration_seconds))
                    conn.commit()
            except Exception:
                pass

    def search_history(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """檢索歷程記錄：例如尋找包含某關鍵字的網頁標題或檔案"""
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT datetime_str, window_title, process_name, duration_seconds
                        FROM timeline
                        WHERE window_title LIKE ? OR process_name LIKE ?
                        ORDER BY id DESC
                        LIMIT ?
                    """, (f"%{query}%", f"%{query}%", limit))
                    rows = cursor.fetchall()
                    return [
                        {
                            "time": r[0],
                            "title": r[1],
                            "process": r[2],
                            "duration_sec": r[3]
                        }
                        for r in rows
                    ]
            except Exception:
                return []

    def get_recent_summary(self, hours: float = 2.0) -> List[Dict[str, Any]]:
        """獲取最近幾小時內的聚焦時間軸"""
        threshold = time.time() - (hours * 3600)
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT datetime_str, window_title, process_name, duration_seconds
                        FROM timeline
                        WHERE timestamp >= ?
                        ORDER BY id DESC
                    """, (threshold,))
                    rows = cursor.fetchall()
                    return [
                        {
                            "time": r[0],
                            "title": r[1],
                            "process": r[2],
                            "duration_sec": r[3]
                        }
                        for r in rows
                    ]
            except Exception:
                return []


# 全域單例
timeline_memory = EpisodicTimelineMemory()
