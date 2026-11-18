import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional


class HistoryManager:
    """
    對話歷史紀錄管理器
    - 支援「永久保存區 (permanent)」與「暫存區 (temp)」
    - 暫存區超過 14 天（2週）無更新自動清理刪除
    - 支援拖曳 / 移動、標題重新命名、載入與儲存
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            self.storage_dir = Path(__file__).resolve().parent.parent / "data" / "chat_history"
        else:
            self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # 初始化時先自動清理過期 2 週之暫存紀錄
        self.clean_expired_temporary_sessions(days=14)

    def _get_session_path(self, session_id: str) -> Path:
        safe_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
        return self.storage_dir / f"{safe_id}.json"

    def clean_expired_temporary_sessions(self, days: int = 14) -> int:
        """
        超過指定天數（預設 14 天 / 2 週）沒有新對話更新的暫存區 session 自動刪除。
        永久保存區 (permanent) 與已釘選項目 (is_pinned) 不受影響。
        """
        threshold = time.time() - (days * 86400)
        deleted_count = 0
        try:
            for p in self.storage_dir.glob("*.json"):
                try:
                    with p.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    cat = data.get("category", "temp")
                    is_pinned = data.get("is_pinned", False)
                    updated_at = data.get("updated_at", data.get("created_at", 0))
                    # 暫存且未釘選且超期者清理
                    if cat == "temp" and not is_pinned and updated_at < threshold:
                        p.unlink(missing_ok=True)
                        deleted_count += 1
                except Exception:
                    continue
        except Exception:
            pass
        return deleted_count

    def save_session(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        title: Optional[str] = None,
        category: Optional[str] = None,
        is_pinned: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        儲存或更新對話 session
        """
        p = self._get_session_path(session_id)
        now = time.time()

        existing: Dict[str, Any] = {}
        if p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        created_at = existing.get("created_at", now)
        current_cat = category or existing.get("category", "temp")
        pinned_val = is_pinned if is_pinned is not None else existing.get("is_pinned", False)

        # 自動生成標題（若未指定）
        if not title:
            title = existing.get("title")
            if not title and messages:
                for m in messages:
                    if m.get("role") == "user":
                        text = m.get("text") or m.get("content") or ""
                        first_line = text.strip().split("\n")[0][:25]
                        if first_line:
                            title = first_line
                            break
            if not title:
                title = f"對話 {time.strftime('%m/%d %H:%M', time.localtime(created_at))}"

        data = {
            "id": session_id,
            "title": title,
            "category": current_cat,  # "permanent" or "temp"
            "is_pinned": pinned_val,
            "created_at": created_at,
            "updated_at": now,
            "messages": messages,
        }

        # 安全寫入
        temp_path = p.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(p)
        return data

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        p = self._get_session_path(session_id)
        if not p.exists():
            return None
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def list_sessions(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        列出所有對話，分為 permanent 與 temp 兩組
        兩邊都支援釘選 (is_pinned)，釘選者優先置頂，其次按 updated_at 倒序排列
        """
        permanent = []
        temp = []
        for p in self.storage_dir.glob("*.json"):
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = {
                    "id": data.get("id", p.stem),
                    "title": data.get("title", p.stem),
                    "category": data.get("category", "temp"),
                    "is_pinned": data.get("is_pinned", False),
                    "created_at": data.get("created_at", 0),
                    "updated_at": data.get("updated_at", 0),
                    "message_count": len(data.get("messages", [])),
                }
                if meta["category"] == "permanent":
                    permanent.append(meta)
                else:
                    temp.append(meta)
            except Exception:
                continue

        # 釘選項目永遠置頂 (is_pinned=True 優先)，其次看最後更新時間
        permanent.sort(key=lambda x: (not x.get("is_pinned", False), -x["updated_at"]))
        temp.sort(key=lambda x: (not x.get("is_pinned", False), -x["updated_at"]))
        return {"permanent": permanent, "temp": temp}

    def toggle_pin(self, session_id: str) -> bool:
        """切換釘選狀態 (兩邊皆可釘選)"""
        p = self._get_session_path(session_id)
        if not p.exists():
            return False
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            data["is_pinned"] = not data.get("is_pinned", False)
            data["updated_at"] = time.time()
            temp_path = p.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(p)
            return True
        except Exception:
            return False

    def duplicate_session(self, session_id: str) -> Optional[str]:
        """複製對話副本"""
        sess = self.get_session(session_id)
        if not sess:
            return None
        new_id = f"qt_sess_{int(time.time())}_{session_id[-4:]}"
        new_title = f"{sess.get('title', '對話')} (副本)"
        new_data = self.save_session(
            session_id=new_id,
            messages=sess.get("messages", []),
            title=new_title,
            category=sess.get("category", "temp"),
            is_pinned=sess.get("is_pinned", False),
        )
        return new_id

    def move_session(self, session_id: str, target_category: str) -> bool:
        """
        移動對話分類（例如將暫存區對話拖曳/轉移到永久保存區）
        target_category: 'permanent' 或 'temp'
        """
        p = self._get_session_path(session_id)
        if not p.exists():
            return False
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            data["category"] = target_category
            data["updated_at"] = time.time()
            temp_path = p.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(p)
            return True
        except Exception:
            return False

    def rename_session(self, session_id: str, new_title: str) -> bool:
        p = self._get_session_path(session_id)
        if not p.exists():
            return False
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            data["title"] = new_title.strip()
            temp_path = p.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.replace(p)
            return True
        except Exception:
            return False

    def delete_session(self, session_id: str) -> bool:
        p = self._get_session_path(session_id)
        try:
            p.unlink(missing_ok=True)
            return True
        except Exception:
            return False
