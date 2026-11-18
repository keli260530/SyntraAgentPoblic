"""
core/idle_autonomy_engine.py
============================
離席自治維護引擎 (Idle Autonomy Engine)
當用戶離開電腦或鎖定螢幕時，全職助手自動啟動背景維護任務：
- 檢查代碼庫變更 (Git status / uncommitted changes)
- 執行自動測試與安全靜態快篩
- 彙整今日工作日誌 (Daily Standup Digest)
- 當用戶重回電腦時立即解除重載，並彈出「回歸摘要」。
"""

import time
import os
import subprocess
import threading
from typing import Callable, List, Dict, Any, Optional
import win32api

class IdleAutonomyEngine:
    def __init__(
        self,
        idle_threshold_seconds: int = 180,  # 預設 3 分鐘無輸入視為離席
        check_interval: float = 2.0
    ):
        self.idle_threshold_seconds = idle_threshold_seconds
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_in_idle_mode = False
        self._custom_tasks: List[Callable[[], Any]] = []
        
        # 狀態紀錄
        self.last_idle_start = 0.0
        self.latest_digest: Dict[str, Any] = {}

    def get_idle_time(self) -> float:
        """獲取自上次鍵盤或滑鼠物理操作以來的秒數"""
        last_input_ms = win32api.GetLastInputInfo()
        current_tick = win32api.GetTickCount()
        return max(0.0, (current_tick - last_input_ms) / 1000.0)

    def register_idle_task(self, task_func: Callable[[], Any]):
        """註冊自訂離席自治任務"""
        self._custom_tasks.append(task_func)

    def start(self):
        """啟動離席監控常駐線程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止離席監控"""
        self._running = False

    def _monitor_loop(self):
        while self._running:
            try:
                idle_sec = self.get_idle_time()
                if idle_sec >= self.idle_threshold_seconds:
                    if not self._is_in_idle_mode:
                        self._on_enter_idle()
                else:
                    if self._is_in_idle_mode:
                        self._on_exit_idle()
            except Exception:
                pass
            time.sleep(self.check_interval)

    def _on_enter_idle(self):
        """進入離席狀態：啟動自治任務"""
        self._is_in_idle_mode = True
        self.last_idle_start = time.time()
        
        # 非同步執行離席自治作業
        threading.Thread(target=self._run_idle_routines, daemon=True).start()

    def _on_exit_idle(self):
        """用戶重回電腦：結算離席期間的工作成果"""
        duration = time.time() - self.last_idle_start
        self._is_in_idle_mode = False
        
        self.latest_digest["idle_duration_sec"] = round(duration, 1)
        self.latest_digest["resumed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def _run_idle_routines(self):
        """執行後台自律檢查"""
        digest = {
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "git_summary": self._check_git_status(),
            "tasks_executed": 0,
            "custom_results": []
        }

        # 執行外部註冊的自治維護工作
        for task in self._custom_tasks:
            if not self._is_in_idle_mode:
                break  # 用戶回來了，立即中斷
            try:
                res = task()
                digest["custom_results"].append(res)
                digest["tasks_executed"] += 1
            except Exception as e:
                digest["custom_results"].append({"error": str(e)})

        self.latest_digest = digest

    def _check_git_status(self) -> Dict[str, Any]:
        """檢測本專案或目前工作目錄的 Git 狀態"""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            if res.returncode == 0:
                lines = [l.strip() for l in res.stdout.strip().split("\n") if l.strip()]
                return {
                    "is_git_repo": True,
                    "uncommitted_files_count": len(lines),
                    "modified_files": lines[:10]  # 最多取前 10 筆
                }
            return {"is_git_repo": False}
        except Exception:
            return {"is_git_repo": False}

    def get_briefing(self) -> Dict[str, Any]:
        """供主介面或 Discord 獲取最新的主人回歸簡報"""
        return self.latest_digest


# 全域單例
idle_engine = IdleAutonomyEngine()
