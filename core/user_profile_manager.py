# -*- coding: utf-8 -*-
"""
core/user_profile_manager.py
============================
使用者個資與個人化資料夾隔離與雲端漫遊管理器 (User Profile & Privacy Vault Manager)

核心職責：
1. 獨立隔離資料夾：預設存放於專案根目錄下的 `user_profile/`（與一般執行期 `data/` 隔離），
   並可由使用者自訂掛載至本機雲端硬碟資料夾（如 Google Drive / OneDrive 本機同步目錄）。
2. 防上傳隱私保護 (Anti-Upload Guard)：
   - 內建路徑保護判定 `is_protected_profile_path()`，禁止一般外部上傳工具與 Shell 指令將此資料夾檔案外傳。
   - 雲端備份打包時自動脫敏（剔除 API Keys、PIN 雜湊、Bot Token 等機敏憑證）。
3. 登入後雲端詢問與連回 (Cloud Roaming & Restore on Login)：
   - 登入 Google 帳號後自動檢查雲端 `Syntra_User_Profile/syntra_personal_profile.json`。
   - 經使用者詢問確認後，將雲端上的個人化設定、長期記憶、習慣畫像、排程安全連回本機並即時生效。
"""
from __future__ import annotations

import datetime
import io
import json
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CLOUD_FOLDER_NAME = "Syntra_User_Profile"
CLOUD_BACKUP_FILENAME = "syntra_personal_profile.json"

# 敏感字串正則（防止意外寫入個人化備份）
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"DPAPI:[A-Za-z0-9+/=]+"),
]


def _scrub_secrets_in_obj(obj: Any) -> Any:
    """遞迴遮罩物件中疑似 API Key 或 DPAPI 密文的字串"""
    if isinstance(obj, str):
        res = obj
        for pat in _SECRET_PATTERNS:
            res = pat.sub("[REDACTED_SECRET]", res)
        return res
    if isinstance(obj, list):
        return [_scrub_secrets_in_obj(x) for x in obj]
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(
                s in k_lower
                for s in ("pin_hash", "pin_salt", "bot_token", "api_key", "refresh_token", "client_secret")
            ):
                continue
            cleaned[k] = _scrub_secrets_in_obj(v)
        return cleaned
    return obj


class UserProfileManager:
    """集中管理使用者個資、個人化記憶與雲端連回同步"""

    def __init__(self, base_dir: Optional[Path] = None, profile_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.legacy_data_dir = self.base_dir / "data"
        self.mount_config_file = self.legacy_data_dir / "user_profile_mount.json"

        # 決定個人資料夾實際位置（支援自訂掛載雲端同步資料夾）
        if profile_dir is not None:
            self.profile_dir = Path(profile_dir)
        else:
            self.profile_dir = self._resolve_profile_dir()

        self._ensure_structure()
        self._migrate_legacy_files()

    def _resolve_profile_dir(self) -> Path:
        default_dir = self.base_dir / "user_profile"
        if self.mount_config_file.exists():
            try:
                cfg = json.loads(self.mount_config_file.read_text(encoding="utf-8"))
                custom_path = cfg.get("custom_profile_dir", "").strip()
                if custom_path:
                    p = Path(custom_path)
                    p.mkdir(parents=True, exist_ok=True)
                    return p
            except Exception:
                pass
        return default_dir

    def _ensure_structure(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        (self.profile_dir / "chat_history").mkdir(parents=True, exist_ok=True)

        # 寫入防上傳隱私聲明標記檔
        guard_file = self.profile_dir / ".privacy_guard"
        if not guard_file.exists():
            try:
                guard_file.write_text(
                    "SYNTRA_PRIVACY_VAULT=1\n"
                    "此資料夾包含使用者個人資料與個人化記憶，禁止 Git 提交與未授權外部上傳。\n",
                    encoding="utf-8",
                )
            except Exception:
                pass

        # 確保 personal_info.json 存在
        if not self.personal_info_path.exists():
            default_info = {
                "nickname": "",
                "role": "",
                "preferred_language": "zh_TW",
                "custom_instructions": "",
                "favorite_projects": [],
                "privacy_protection_enabled": True,
                "cloud_auto_prompt_on_login": True,
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            self._atomic_write_json(self.personal_info_path, default_info)

    # ---- 標準個資與個人化檔案路徑 -----------------------------------------------
    @property
    def personal_info_path(self) -> Path:
        return self.profile_dir / "personal_info.json"

    @property
    def long_term_memory_path(self) -> Path:
        return self.profile_dir / "long_term_memory.json"

    @property
    def habit_profile_path(self) -> Path:
        return self.profile_dir / "user_habit_profile.json"

    @property
    def schedules_path(self) -> Path:
        return self.profile_dir / "schedules.json"

    @property
    def chat_history_dir(self) -> Path:
        return self.profile_dir / "chat_history"

    @property
    def preferences_path(self) -> Path:
        return self.profile_dir / "user_preferences.json"

    @property
    def workspace_path(self) -> Path:
        return self.profile_dir / "agent_workspace.json"

    # ---- 舊版 data/ 自動遷移至 user_profile/ ------------------------------------
    def _migrate_legacy_files(self) -> None:
        migrations = [
            (self.legacy_data_dir / "long_term_memory.json", self.long_term_memory_path),
            (self.legacy_data_dir / "user_habit_profile.json", self.habit_profile_path),
            (self.legacy_data_dir / "schedules.json", self.schedules_path),
            (self.legacy_data_dir / "agent_workspace.json", self.workspace_path),
        ]
        for old_path, new_path in migrations:
            if old_path.exists() and not new_path.exists():
                try:
                    shutil.copy2(old_path, new_path)
                except Exception:
                    pass

        old_hist = self.legacy_data_dir / "chat_history"
        if old_hist.exists() and old_hist.is_dir():
            for f in old_hist.glob("*.json"):
                target = self.chat_history_dir / f.name
                if not target.exists():
                    try:
                        shutil.copy2(f, target)
                    except Exception:
                        pass

    # ---- 隱私防上傳檢查 (Anti-Upload Guard) --------------------------------------
    def is_protected_profile_path(self, target_path: str | os.PathLike) -> bool:
        """
        檢查目標路徑是否位於受保護的使用者個資資料夾內。
        供本地工具或上傳模組呼叫，攔截未經授權的個資上傳。
        """
        try:
            resolved_target = Path(target_path).resolve()
            resolved_profile = self.profile_dir.resolve()
            if resolved_target == resolved_profile or resolved_profile in resolved_target.parents:
                return True
        except Exception:
            pass
        norm = str(target_path).replace("\\", "/").lower()
        return (
            "user_profile/" in norm
            or norm.endswith("/user_profile")
            or norm == "user_profile"
            or ".privacy_guard" in norm
        )

    # ---- 個資與個人化設定讀寫 ---------------------------------------------------
    @staticmethod
    def _atomic_write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def get_personal_info(self) -> Dict[str, Any]:
        return self._read_json(self.personal_info_path, {})

    def update_personal_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_personal_info()
        allowed_keys = (
            "nickname",
            "role",
            "preferred_language",
            "custom_instructions",
            "favorite_projects",
            "privacy_protection_enabled",
            "cloud_auto_prompt_on_login",
        )
        for k in allowed_keys:
            if k in payload:
                current[k] = _scrub_secrets_in_obj(payload[k])
        current["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self._atomic_write_json(self.personal_info_path, current)
        return current

    def as_prompt_context(self) -> str:
        """將使用者的個人化資訊轉為 Agent 系統提示背景"""
        info = self.get_personal_info()
        lines = []
        if info.get("nickname"):
            lines.append(f"- 使用者稱呼：{info['nickname']}")
        if info.get("role"):
            lines.append(f"- 使用者角色/專業：{info['role']}")
        if info.get("favorite_projects"):
            projs = info["favorite_projects"]
            if isinstance(projs, list) and projs:
                lines.append(f"- 常用專案/路徑：{', '.join(str(x) for x in projs[:5])}")
        if info.get("custom_instructions"):
            lines.append(f"- 個人化偏好指示：{info['custom_instructions']}")
        if not lines:
            return ""
        return "[個人化畫像]\n" + "\n".join(lines)

    # ---- 本機雲端資料夾掛載 / 變更路徑 ------------------------------------------
    def set_custom_profile_dir(self, new_dir: str, copy_existing: bool = True) -> Dict[str, Any]:
        """
        讓使用者把個資資料夾直接設在自己的本機雲端同步資料夾（如 Google Drive / OneDrive 資料夾），
        或還原為預設的 `user_profile/`。
        """
        new_path = Path(new_dir).resolve() if new_dir.strip() else (self.base_dir / "user_profile")
        new_path.mkdir(parents=True, exist_ok=True)

        has_remote_data = (
            (new_path / "long_term_memory.json").exists()
            or (new_path / "personal_info.json").exists()
            or (new_path / "user_habit_profile.json").exists()
        )

        old_path = self.profile_dir
        if copy_existing and old_path.resolve() != new_path.resolve() and not has_remote_data:
            for item in (
                "personal_info.json",
                "long_term_memory.json",
                "user_habit_profile.json",
                "schedules.json",
                "user_preferences.json",
            ):
                src = old_path / item
                dst = new_path / item
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)

        self.legacy_data_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write_json(
            self.mount_config_file,
            {
                "custom_profile_dir": str(new_path) if new_dir.strip() else "",
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            },
        )
        self.profile_dir = new_path
        self._ensure_structure()
        self.sync_runtime_instances()
        return {
            "ok": True,
            "profile_dir": str(self.profile_dir),
            "found_existing_profile": has_remote_data,
        }

    def sync_runtime_instances(self) -> None:
        """讓執行期單例的路徑即時指向目前的 user_profile 資料夾"""
        try:
            from core import long_term_memory as ltm_mod
            if ltm_mod._default is not None:
                ltm_mod._default.path = self.long_term_memory_path
        except Exception:
            pass
        try:
            from core.habit_sync_engine import habit_sync_engine
            habit_sync_engine.profile_path = str(self.habit_profile_path)
        except Exception:
            pass

    # ---- 雲端打包匯出與連回匯入 (Cloud Bundle Export / Import) -------------------
    def export_cloud_bundle(self, settings_manager: Optional[Any] = None) -> Dict[str, Any]:
        """
        將個人化資訊、長期記憶、習慣畫像、排程與非機敏偏好設定打包為單一脫敏 JSON Bundle，
        準備上傳至使用者個人的雲端硬碟。
        """
        personal_info = _scrub_secrets_in_obj(self.get_personal_info())
        memories = _scrub_secrets_in_obj(self._read_json(self.long_term_memory_path, []))
        habits = _scrub_secrets_in_obj(self._read_json(self.habit_profile_path, {}))
        schedules = _scrub_secrets_in_obj(self._read_json(self.schedules_path, []))

        prefs: Dict[str, Any] = {}
        if settings_manager is not None:
            raw_settings = settings_manager.get_all(mask_secrets=True)
            for k in ("language", "selected_model", "custom_opencode_paths", "dnd", "supervisor", "permissions"):
                if k in raw_settings:
                    prefs[k] = _scrub_secrets_in_obj(raw_settings[k])
            self._atomic_write_json(self.preferences_path, prefs)
        else:
            prefs = _scrub_secrets_in_obj(self._read_json(self.preferences_path, {}))

        # 只同步標記為「永久保存 (permanent)」或「已釘選 (is_pinned)」的重要對話紀錄（最多 20 筆）
        pinned_sessions = []
        if self.chat_history_dir.exists():
            for p in sorted(self.chat_history_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                data = self._read_json(p, {})
                if isinstance(data, dict) and (data.get("category") == "permanent" or data.get("is_pinned")):
                    pinned_sessions.append(_scrub_secrets_in_obj(data))
                    if len(pinned_sessions) >= 20:
                        break

        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        enabled_addons = _scrub_secrets_in_obj(self._read_json(self.profile_dir / "enabled_addons.json", {}))
        addon_data = {
            "finance_ledger": _scrub_secrets_in_obj(self._read_json(self.profile_dir / "finance" / "ledger.json", [])),
            "research_library": _scrub_secrets_in_obj(self._read_json(self.profile_dir / "research" / "library.json", [])),
            "health_records": _scrub_secrets_in_obj(self._read_json(self.profile_dir / "health" / "records.json", [])),
        }
        return {
            "schema_version": "1.1",
            "exported_at": now_iso,
            "device_name": platform.node() or "Unknown-PC",
            "summary": {
                "nickname": personal_info.get("nickname", ""),
                "memory_count": len(memories) if isinstance(memories, list) else 0,
                "has_habits": bool(habits),
                "schedules_count": len(schedules) if isinstance(schedules, list) else 0,
                "saved_sessions_count": len(pinned_sessions),
            },
            "payload": {
                "personal_info": personal_info,
                "long_term_memory": memories if isinstance(memories, list) else [],
                "user_habit_profile": habits if isinstance(habits, dict) else {},
                "schedules": schedules if isinstance(schedules, list) else [],
                "user_preferences": prefs,
                "pinned_sessions": pinned_sessions,
                "enabled_addons": enabled_addons if isinstance(enabled_addons, dict) else {},
                "addon_data": addon_data,
            },
        }

    def import_cloud_bundle(
        self,
        bundle: Dict[str, Any],
        merge: bool = True,
        settings_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        將從使用者雲端連回的個人化資料 Bundle 匯入至本機 `user_profile/`。
        merge=True 時會保留本機獨有的記憶與對話並與雲端合併；merge=False 則以雲端覆蓋。
        """
        payload = bundle.get("payload") if isinstance(bundle, dict) else None
        if not isinstance(payload, dict):
            return {"success": False, "error": "雲端備份格式無效（缺少 payload）"}

        restored_counts = {"memories": 0, "habits": False, "schedules": 0, "sessions": 0}

        # 1. 個人基本資訊
        cloud_info = payload.get("personal_info")
        if isinstance(cloud_info, dict):
            if merge:
                local_info = self.get_personal_info()
                for k, v in cloud_info.items():
                    if v or k not in local_info:
                        local_info[k] = v
                self._atomic_write_json(self.personal_info_path, local_info)
            else:
                self._atomic_write_json(self.personal_info_path, cloud_info)

        # 2. 長期記憶 (Long-Term Memory)
        cloud_mem = payload.get("long_term_memory")
        if isinstance(cloud_mem, list):
            if merge:
                local_mem = self._read_json(self.long_term_memory_path, [])
                if not isinstance(local_mem, list):
                    local_mem = []
                existing_norms = {
                    "".join(str(m.get("text", "")).lower().split()) for m in local_mem if isinstance(m, dict)
                }
                for item in cloud_mem:
                    if isinstance(item, dict) and item.get("text"):
                        norm_txt = "".join(str(item["text"]).lower().split())
                        if norm_txt and norm_txt not in existing_norms:
                            local_mem.append(item)
                            existing_norms.add(norm_txt)
                self._atomic_write_json(self.long_term_memory_path, local_mem[-200:])
                restored_counts["memories"] = len(local_mem)
            else:
                self._atomic_write_json(self.long_term_memory_path, cloud_mem[-200:])
                restored_counts["memories"] = len(cloud_mem)

        # 3. 個人習慣畫像 (User Habit Profile)
        cloud_habits = payload.get("user_habit_profile")
        if isinstance(cloud_habits, dict) and cloud_habits:
            if merge:
                local_habits = self._read_json(self.habit_profile_path, {})
                if not isinstance(local_habits, dict):
                    local_habits = {}
                local_habits.update(cloud_habits)
                self._atomic_write_json(self.habit_profile_path, local_habits)
            else:
                self._atomic_write_json(self.habit_profile_path, cloud_habits)
            restored_counts["habits"] = True

        # 4. 排程任務 (Schedules)
        cloud_sched = payload.get("schedules")
        if isinstance(cloud_sched, list) and cloud_sched:
            if merge:
                local_sched = self._read_json(self.schedules_path, [])
                if not isinstance(local_sched, list):
                    local_sched = []
                by_id = {s.get("id"): s for s in local_sched if isinstance(s, dict) and s.get("id")}
                for s in cloud_sched:
                    if isinstance(s, dict) and s.get("id"):
                        by_id[s["id"]] = s
                merged_sched = list(by_id.values())
                self._atomic_write_json(self.schedules_path, merged_sched)
                restored_counts["schedules"] = len(merged_sched)
            else:
                self._atomic_write_json(self.schedules_path, cloud_sched)
                restored_counts["schedules"] = len(cloud_sched)

        # 5. 使用者偏好設定 (User Preferences)
        cloud_prefs = payload.get("user_preferences")
        if isinstance(cloud_prefs, dict) and cloud_prefs:
            self._atomic_write_json(self.preferences_path, cloud_prefs)
            if settings_manager is None:
                try:
                    from core.settings_manager import SettingsManager
                    settings_manager = SettingsManager()
                except Exception:
                    settings_manager = None
            if settings_manager is not None:
                try:
                    settings_manager.update_settings(cloud_prefs)
                except Exception:
                    pass

        # 6. 永久/釘選對話紀錄
        cloud_sessions = payload.get("pinned_sessions")
        if isinstance(cloud_sessions, list):
            for sess in cloud_sessions:
                if isinstance(sess, dict) and sess.get("id"):
                    safe_id = "".join(c for c in str(sess["id"]) if c.isalnum() or c in ("-", "_"))
                    if safe_id:
                        target_sess = self.chat_history_dir / f"{safe_id}.json"
                        if not merge or not target_sess.exists():
                            self._atomic_write_json(target_sess, sess)
                            restored_counts["sessions"] += 1

        # 7. 選配 DLC 模組啟用狀態與專屬資料
        cloud_addons = payload.get("enabled_addons")
        if isinstance(cloud_addons, dict) and cloud_addons:
            self._atomic_write_json(self.profile_dir / "enabled_addons.json", cloud_addons)
        addon_data = payload.get("addon_data")
        if isinstance(addon_data, dict):
            for key_name, rel_path in (
                ("finance_ledger", Path("finance") / "ledger.json"),
                ("research_library", Path("research") / "library.json"),
                ("health_records", Path("health") / "records.json"),
            ):
                items = addon_data.get(key_name)
                if isinstance(items, list) and items:
                    target_f = self.profile_dir / rel_path
                    if not merge or not target_f.exists():
                        self._atomic_write_json(target_f, items)

        self.sync_runtime_instances()
        try:
            from core.addon_module_manager import addon_module_manager
            addon_module_manager.refresh_agent_tool_registry()
        except Exception:
            pass
        return {
            "success": True,
            "exported_at": bundle.get("exported_at", ""),
            "device_name": bundle.get("device_name", ""),
            "restored": restored_counts,
        }

    # ---- Google Drive 雲端輔助方法（相容任何 GoogleWorkspaceSuite 實例）----------
    @staticmethod
    def _gdrive_ensure_folder(google_suite: Any, folder_name: str = CLOUD_FOLDER_NAME) -> str:
        service = google_suite._get_service("drive", "v3")
        q = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        res = service.files().list(q=q, pageSize=5, fields="files(id, name)").execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        created = service.files().create(body=meta, fields="id").execute()
        return created["id"]

    @classmethod
    def _gdrive_find_profile_backup(
        cls,
        google_suite: Any,
        folder_name: str = CLOUD_FOLDER_NAME,
        filename: str = CLOUD_BACKUP_FILENAME,
    ) -> Optional[Dict[str, Any]]:
        service = google_suite._get_service("drive", "v3")
        q_folder = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        f_res = service.files().list(q=q_folder, pageSize=5, fields="files(id)").execute()
        folders = f_res.get("files", [])
        if folders:
            folder_id = folders[0]["id"]
            q_file = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        else:
            q_file = f"name = '{filename}' and trashed = false"
        res = (
            service.files()
            .list(
                q=q_file,
                pageSize=5,
                orderBy="modifiedTime desc",
                fields="files(id, name, modifiedTime, size)",
            )
            .execute()
        )
        items = res.get("files", [])
        return items[0] if items else None

    @classmethod
    def _gdrive_download_json(cls, google_suite: Any, file_id: str) -> Dict[str, Any]:
        service = google_suite._get_service("drive", "v3")
        raw = service.files().get_media(fileId=file_id).execute()
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = str(raw)
        return json.loads(text)

    @classmethod
    def _gdrive_upload_profile_backup(
        cls,
        google_suite: Any,
        content: str,
        folder_name: str = CLOUD_FOLDER_NAME,
        filename: str = CLOUD_BACKUP_FILENAME,
    ) -> Dict[str, Any]:
        from core.google_workspace_suite import _google

        service = google_suite._get_service("drive", "v3")
        folder_id = cls._gdrive_ensure_folder(google_suite, folder_name)
        existing = cls._gdrive_find_profile_backup(google_suite, folder_name, filename)
        media = _google().MediaInMemoryUpload(
            content.encode("utf-8"), mimetype="application/json", resumable=False
        )
        if existing and existing.get("id"):
            updated = (
                service.files()
                .update(
                    fileId=existing["id"],
                    media_body=media,
                    fields="id, name, modifiedTime",
                )
                .execute()
            )
            return {"id": updated.get("id"), "folder_id": folder_id, "updated": True}
        else:
            meta = {"name": filename, "parents": [folder_id], "mimeType": "application/json"}
            created = (
                service.files()
                .create(
                    body=meta,
                    media_body=media,
                    fields="id, name, modifiedTime",
                )
                .execute()
            )
            return {"id": created.get("id"), "folder_id": folder_id, "updated": False}

    # ---- Google Drive 雲端同步與登入後連回 ---------------------------------------
    def check_cloud_profile(self, google_suite: Any) -> Dict[str, Any]:
        """
        登入後檢查使用者 Google Drive 是否已有個人化資料備份。
        不會自動覆蓋本機，而是回傳摘要資訊供 UI 詢問使用者是否連回。
        """
        if not google_suite or not google_suite.is_authenticated():
            return {"found": False, "reason": "not_authenticated"}
        try:
            meta = self._gdrive_find_profile_backup(
                google_suite,
                folder_name=CLOUD_FOLDER_NAME,
                filename=CLOUD_BACKUP_FILENAME,
            )
            if not meta:
                return {"found": False}
            bundle = self._gdrive_download_json(google_suite, meta["id"])
            summary = bundle.get("summary", {}) if isinstance(bundle, dict) else {}
            return {
                "found": True,
                "file_id": meta["id"],
                "modified_time": meta.get("modifiedTime", ""),
                "exported_at": bundle.get("exported_at", meta.get("modifiedTime", "")),
                "device_name": bundle.get("device_name", "雲端裝置"),
                "summary": summary,
            }
        except Exception as e:
            return {"found": False, "error": str(e)}

    def sync_to_cloud(self, google_suite: Any, settings_manager: Optional[Any] = None) -> Dict[str, Any]:
        """將本機 `user_profile/` 內的個人化資料脫敏打包並上傳至使用者自己的 Google Drive"""
        if not google_suite or not google_suite.is_authenticated():
            return {"success": False, "error": "尚未登入 Google 帳號，請先完成登入授權"}
        try:
            bundle = self.export_cloud_bundle(settings_manager=settings_manager)
            res = self._gdrive_upload_profile_backup(
                google_suite,
                content=json.dumps(bundle, ensure_ascii=False, indent=2),
                folder_name=CLOUD_FOLDER_NAME,
                filename=CLOUD_BACKUP_FILENAME,
            )
            return {
                "success": True,
                "file_id": res.get("id"),
                "folder_id": res.get("folder_id"),
                "exported_at": bundle["exported_at"],
                "summary": bundle["summary"],
            }
        except Exception as e:
            return {"success": False, "error": f"上傳個人化資料至雲端失敗：{e}"}

    def restore_from_cloud(
        self,
        google_suite: Any,
        merge: bool = True,
        settings_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """經使用者同意後，從 Google Drive 下載個人化資料備份並連回本機"""
        if not google_suite or not google_suite.is_authenticated():
            return {"success": False, "error": "尚未登入 Google 帳號"}
        try:
            meta = self._gdrive_find_profile_backup(
                google_suite,
                folder_name=CLOUD_FOLDER_NAME,
                filename=CLOUD_BACKUP_FILENAME,
            )
            if not meta:
                return {"success": False, "error": "雲端硬碟中尚未找到先前的個人化資料備份"}
            bundle = self._gdrive_download_json(google_suite, meta["id"])
            if not isinstance(bundle, dict):
                return {"success": False, "error": "雲端個人化備份內容格式無法解析"}
            return self.import_cloud_bundle(bundle, merge=merge, settings_manager=settings_manager)
        except Exception as e:
            return {"success": False, "error": f"從雲端連回個人化資料失敗：{e}"}

    def get_status(self) -> Dict[str, Any]:
        """回傳目前個人化資料夾狀態摘要"""
        memories = self._read_json(self.long_term_memory_path, [])
        habits = self._read_json(self.habit_profile_path, {})
        schedules = self._read_json(self.schedules_path, [])
        info = self.get_personal_info()
        return {
            "profile_dir": str(self.profile_dir),
            "privacy_protected": True,
            "personal_info": info,
            "memory_count": len(memories) if isinstance(memories, list) else 0,
            "has_habits": bool(habits),
            "schedules_count": len(schedules) if isinstance(schedules, list) else 0,
        }


# 全域單例
user_profile_manager = UserProfileManager()


# ==============================================================================
# 執行期無縫掛鉤 (Runtime Hooks)：
# 確保即使在防毒核心鎖檔保護 (SelfDefenseImmortal) 開啟狀態下，
# 所有模組與工具皆自動切換至 `user_profile/` 並強制啟用防上傳隱私攔截。
# ==============================================================================
_HOOKS_INSTALLED = False


def install_runtime_hooks() -> None:
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    _HOOKS_INSTALLED = True

    # 1. LongTermMemory 指向 user_profile/long_term_memory.json 並注入個人畫像
    try:
        from core import long_term_memory as ltm_mod

        orig_ltm_init = ltm_mod.LongTermMemory.__init__
        orig_ltm_as_prompt = ltm_mod.LongTermMemory.as_prompt

        def _patched_ltm_init(self, path=None, sanitize=None):
            self._uses_default_profile = path is None
            if path is None:
                path = user_profile_manager.long_term_memory_path
            orig_ltm_init(self, path=path, sanitize=sanitize)

        def _patched_ltm_as_prompt(self) -> str:
            base_prompt = orig_ltm_as_prompt(self)
            if getattr(self, "_uses_default_profile", False):
                persona = user_profile_manager.as_prompt_context()
                if persona:
                    if base_prompt:
                        return base_prompt + "\n" + persona
                    return "[長期記憶：以下是使用者先前要你記住的事，請自然地遵守，不必複述]\n" + persona
            return base_prompt

        ltm_mod.LongTermMemory.__init__ = _patched_ltm_init
        ltm_mod.LongTermMemory.as_prompt = _patched_ltm_as_prompt
        if ltm_mod._default is not None:
            ltm_mod._default.path = user_profile_manager.long_term_memory_path
            ltm_mod._default._uses_default_profile = True
    except Exception:
        pass

    # 2. HabitSyncEngine 指向 user_profile/user_habit_profile.json
    try:
        from core import habit_sync_engine as hse_mod

        orig_hse_init = hse_mod.HabitSyncEngine.__init__

        def _patched_hse_init(self, profile_path=None, snapshot_dir="data/cache_snapshots"):
            if profile_path is None or profile_path == "data/user_habit_profile.json":
                profile_path = str(user_profile_manager.habit_profile_path)
            orig_hse_init(self, profile_path=profile_path, snapshot_dir=snapshot_dir)

        hse_mod.HabitSyncEngine.__init__ = _patched_hse_init
        hse_mod.habit_sync_engine.profile_path = str(user_profile_manager.habit_profile_path)
    except Exception:
        pass

    # 3. HistoryManager 指向 user_profile/chat_history
    try:
        from core import history_manager as hm_mod

        orig_hm_init = hm_mod.HistoryManager.__init__

        def _patched_hm_init(self, storage_dir=None):
            if storage_dir is None:
                storage_dir = user_profile_manager.chat_history_dir
            orig_hm_init(self, storage_dir=storage_dir)

        hm_mod.HistoryManager.__init__ = _patched_hm_init
    except Exception:
        pass

    # 4. ScheduleManager 指向 user_profile/schedules.json
    try:
        from core import schedule_manager as sm_mod

        orig_sm_init = sm_mod.ScheduleManager.__init__

        def _patched_sm_init(self, config_path=None):
            if config_path is None:
                config_path = user_profile_manager.schedules_path
            orig_sm_init(self, config_path=config_path)

        sm_mod.ScheduleManager.__init__ = _patched_sm_init
    except Exception:
        pass

    # 5. GoogleWorkspaceSuite 加上個資資料夾防上傳攔截 + 雲端備份輔助方法
    try:
        from core import google_workspace_suite as gws_mod

        orig_upload_local = gws_mod.GoogleWorkspaceSuite.gdrive_upload_local_file

        def _guarded_upload_local(self, local_path: str, remote_filename: Optional[str] = None):
            if user_profile_manager.is_protected_profile_path(local_path):
                raise PermissionError(
                    "🔒 隱私保護攔截：禁止將受保護的個資資料夾 (user_profile) 檔案直接上傳。"
                    "若需備份個人化設定至您的雲端，請使用「個人雲端同步」功能。"
                )
            return orig_upload_local(self, local_path, remote_filename)

        gws_mod.GoogleWorkspaceSuite.gdrive_upload_local_file = _guarded_upload_local
        gws_mod.GoogleWorkspaceSuite.gdrive_find_profile_backup = (
            lambda self, folder_name=CLOUD_FOLDER_NAME, filename=CLOUD_BACKUP_FILENAME: UserProfileManager._gdrive_find_profile_backup(
                self, folder_name, filename
            )
        )
        gws_mod.GoogleWorkspaceSuite.gdrive_download_json = (
            lambda self, file_id: UserProfileManager._gdrive_download_json(self, file_id)
        )
        gws_mod.GoogleWorkspaceSuite.gdrive_upload_profile_backup = (
            lambda self, content, folder_name=CLOUD_FOLDER_NAME, filename=CLOUD_BACKUP_FILENAME: UserProfileManager._gdrive_upload_profile_backup(
                self, content, folder_name, filename
            )
        )
    except Exception:
        pass

    # 6. CommandPolicy 攔截任何試圖外傳或存取 user_profile 的 Shell 指令
    try:
        from core import command_policy as cp_mod

        orig_classify = cp_mod.classify_command

        def _guarded_classify(command: str) -> Tuple[str, str]:
            cmd_lower = (command or "").lower().replace("\\", "/")
            if "user_profile" in cmd_lower or ".privacy_guard" in cmd_lower:
                return cp_mod.DESTRUCTIVE, "存取或操作受保護的使用者個資資料夾 (user_profile)"
            return orig_classify(command)

        cp_mod.classify_command = _guarded_classify
    except Exception:
        pass

    # 7. 掛載主 Agent 內建日常工具與使用者選配 DLC 模組工具
    try:
        from core.addon_module_manager import addon_module_manager
        addon_module_manager.refresh_agent_tool_registry()
    except Exception:
        pass

    # 8. 掛載本機應用程式自動掃描、Google 預設權限規則、智慧啟動器與 UIA 視窗互動強化
    try:
        from core.app_discovery_and_launcher import install_app_and_uia_hooks
        install_app_and_uia_hooks()
    except Exception:
        pass


install_runtime_hooks()
