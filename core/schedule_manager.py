import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid


class ScheduleManager:
    """
    排程專區管理器
    - 支援週期性自動背景任務（如定時檢查代碼、定時 Git 檢查、自訂提問等）
    - 任務配置儲存於 data/schedules.json
    """

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            self.config_path = Path(__file__).resolve().parent.parent / "data" / "schedules.json"
        else:
            self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def _ensure_defaults(self):
        if not self.config_path.exists():
            default_tasks = [
                {
                    "id": "sched_check_code",
                    "name": "🔭 定時檢查寫程式視窗狀態",
                    "prompt": "請在背景檢查寫程式視窗（VS Code / Cursor / Antigravity），確認目前 AI 生成結果或編譯輸出是否有錯誤。",
                    "interval_minutes": 30,
                    "enabled": False,
                    "last_run": 0,
                    "next_run": time.time() + 1800,
                },
                {
                    "id": "sched_check_git",
                    "name": "🧪 定期工作目錄 Git 狀態巡檢",
                    "prompt": "請在背景檢查目前工作目錄的 Git 狀態與未提交變更，提醒需留意的程式檔案。",
                    "interval_minutes": 60,
                    "enabled": False,
                    "last_run": 0,
                    "next_run": time.time() + 3600,
                },
            ]
            self._save_all(default_tasks)

    def _load_all(self) -> List[Dict[str, Any]]:
        if not self.config_path.exists():
            return []
        try:
            with self.config_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_all(self, tasks: List[Dict[str, Any]]) -> None:
        temp_path = self.config_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        temp_path.replace(self.config_path)

    def list_schedules(self) -> List[Dict[str, Any]]:
        return self._load_all()

    def add_schedule(
        self,
        name: str,
        prompt: str,
        interval_minutes: int = 60,
        start_at: Optional[float] = None,
        one_shot: bool = False,
    ) -> Dict[str, Any]:
        tasks = self._load_all()
        now = time.time()
        first_run = float(start_at) if start_at is not None else (now + (max(1, interval_minutes) * 60))
        new_task = {
            "id": f"sched_{uuid.uuid4().hex[:8]}",
            "name": name.strip(),
            "prompt": prompt.strip(),
            "interval_minutes": max(1, interval_minutes),
            "one_shot": bool(one_shot),
            "enabled": True,
            "last_run": 0,
            "next_run": first_run,
        }
        tasks.append(new_task)
        self._save_all(tasks)
        return new_task

    def update_schedule(
        self,
        sched_id: str,
        name: Optional[str] = None,
        prompt: Optional[str] = None,
        interval_minutes: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        tasks = self._load_all()
        updated = False
        now = time.time()
        for t in tasks:
            if t["id"] == sched_id:
                if name is not None:
                    t["name"] = name.strip()
                if prompt is not None:
                    t["prompt"] = prompt.strip()
                if interval_minutes is not None:
                    t["interval_minutes"] = max(1, interval_minutes)
                    t["next_run"] = now + (t["interval_minutes"] * 60)
                if enabled is not None:
                    t["enabled"] = enabled
                    if enabled:
                        t["next_run"] = now + (t["interval_minutes"] * 60)
                updated = True
                break
        if updated:
            self._save_all(tasks)
        return updated

    def delete_schedule(self, sched_id: str) -> bool:
        tasks = self._load_all()
        new_tasks = [t for t in tasks if t["id"] != sched_id]
        if len(new_tasks) != len(tasks):
            self._save_all(new_tasks)
            return True
        return False

    def get_due_schedules(self) -> List[Dict[str, Any]]:
        """回傳目前已到達執行時間且啟用的排程"""
        tasks = self._load_all()
        now = time.time()
        due = []
        for t in tasks:
            if t.get("enabled", False) and t.get("next_run", 0) <= now:
                due.append(t)
        return due

    def mark_run(self, sched_id: str) -> None:
        """標記已執行，並排定下一次時間"""
        tasks = self._load_all()
        now = time.time()
        for t in tasks:
            if t["id"] == sched_id:
                t["last_run"] = now
                if t.get("one_shot"):
                    t["enabled"] = False
                else:
                    interval = t.get("interval_minutes", 30)
                    t["next_run"] = now + (interval * 60)
                break
        self._save_all(tasks)
