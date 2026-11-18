import datetime
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.permissions import default_permissions


class SettingsManager:
    """
    管理 Agent 的本機設定、資安 PIN 碼雜湊驗證、Discord Bot 設定與 OpenCode 自訂路徑。
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.data_dir = data_dir or (self.base_dir / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.data_dir / "settings.json"
        self.audit_log_file = self.data_dir / "audit_log.jsonl"
        self.session_token = secrets.token_urlsafe(24)
        self._settings: Dict[str, Any] = self._load()

    def _default_settings(self) -> Dict[str, Any]:
        # 預設交易安全 PIN 為 "0000" 的雜湊，提示使用者可在 UI 修改
        default_salt = secrets.token_hex(8)
        default_pin_hash = self._hash_pin("0000", default_salt)
        return {
            "language": "zh_TW",
            "selected_model": "",
            "custom_opencode_paths": [],
            "custom_providers": [],
            "discord": {
                "enabled": False,
                "bot_token": "",
                "channel_id": "",
                "webhook_url": "",
                "notify_on_web": True,
                "notify_on_supervision": True,
                "notify_on_security": True,
            },
            "security": {
                "pin_salt": default_salt,
                "pin_hash": default_pin_hash,
                "pin_is_default": True,
                "redact_sensitive_windows": True,
                "strict_transaction_block": True,
                "trusted_domains": [
                    "github.com",
                    "stackoverflow.com",
                    "docs.python.org",
                    "developer.mozilla.org",
                    "pypi.org",
                    "npmjs.com",
                    "google.com",
                    "bing.com",
                    "duckduckgo.com",
                ],
            },
            "dnd": {
                "auto_detect_game": True,
                "auto_detect_video": True,
                "protect_homework_focus": True,
                "user_idle_Wait_seconds": 4.0,
                "manual_dnd": False,
            },
            "supervisor": {
                "max_consecutive_failures": 3,
                "poll_interval_seconds": 5.0,
                "auto_send_feedback": True,
            },
            "autostart_enabled": True,
            "permissions": default_permissions(),
        }

    def _hash_pin(self, pin: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{pin.strip()}".encode("utf-8")).hexdigest()

    def _load(self) -> Dict[str, Any]:
        defaults = self._default_settings()
        if self.settings_file.exists():
            try:
                loaded = json.loads(self.settings_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for k, v in loaded.items():
                        if isinstance(v, dict) and isinstance(defaults.get(k), dict):
                            defaults[k].update(v)
                        else:
                            defaults[k] = v
            except Exception:
                pass
        self._save_dict(defaults)
        return defaults

    def _save_dict(self, data: Dict[str, Any]):
        self.settings_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save(self):
        self._save_dict(self._settings)

    def get_all(self, mask_secrets: bool = True) -> Dict[str, Any]:
        data = json.loads(json.dumps(self._settings))
        if mask_secrets:
            sec = data.get("security", {})
            sec.pop("pin_hash", None)
            sec.pop("pin_salt", None)
            disc = data.get("discord", {})
            token = disc.get("bot_token", "")
            disc["has_bot_token"] = bool(token)
            disc["bot_token_masked"] = (
                f"{token[:6]}...{token[-4:]}" if len(token) > 12 else ("已設定" if token else "")
            )
            disc.pop("bot_token", None)
        return data

    def get_raw(self) -> Dict[str, Any]:
        return self._settings

    def get(self, key: str, default: Any = None) -> Any:
        """安全取得單一設定項"""
        return self._settings.get(key, default)

    def set(self, key: str, value: Any):
        """安全設定並即時持久化單一設定項"""
        self._settings[key] = value
        self.save()

    def get_language(self) -> str:
        return self._settings.get("language", "zh_TW")

    def set_language(self, lang: str):
        self._settings["language"] = str(lang)
        self.save()

    def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if "language" in payload and str(payload["language"]).strip():
            self._settings["language"] = str(payload["language"]).strip()
        if "selected_model" in payload:
            self._settings["selected_model"] = str(payload["selected_model"])
        if "custom_opencode_paths" in payload and isinstance(payload["custom_opencode_paths"], list):
            self._settings["custom_opencode_paths"] = [
                str(p).strip() for p in payload["custom_opencode_paths"] if str(p).strip()
            ]
        if "custom_providers" in payload and isinstance(payload["custom_providers"], list):
            self._settings["custom_providers"] = payload["custom_providers"]

        if "discord" in payload and isinstance(payload["discord"], dict):
            d_in = payload["discord"]
            for k in ("enabled", "channel_id", "webhook_url", "notify_on_web", "notify_on_supervision", "notify_on_security"):
                if k in d_in:
                    self._settings["discord"][k] = d_in[k]
            if "bot_token" in d_in and d_in["bot_token"] and "..." not in str(d_in["bot_token"]):
                self._settings["discord"]["bot_token"] = str(d_in["bot_token"]).strip()

        if "dnd" in payload and isinstance(payload["dnd"], dict):
            self._settings["dnd"].update(payload["dnd"])

        if "supervisor" in payload and isinstance(payload["supervisor"], dict):
            self._settings["supervisor"].update(payload["supervisor"])

        if "permissions" in payload and isinstance(payload["permissions"], dict):
            perms = self._settings.setdefault("permissions", default_permissions())
            for section in ("google_scopes", "agent", "features", "apps"):
                if isinstance(payload["permissions"].get(section), dict):
                    perms.setdefault(section, {}).update(payload["permissions"][section])

        if "security" in payload and isinstance(payload["security"], dict):
            s_in = payload["security"]
            for k in ("redact_sensitive_windows", "strict_transaction_block", "trusted_domains"):
                if k in s_in:
                    self._settings["security"][k] = s_in[k]
            if "new_pin" in s_in and str(s_in["new_pin"]).strip():
                self.set_pin(str(s_in["new_pin"]).strip())

        self.save()
        return self.get_all(mask_secrets=True)

    def set_pin(self, new_pin: str):
        salt = secrets.token_hex(8)
        self._settings["security"]["pin_salt"] = salt
        self._settings["security"]["pin_hash"] = self._hash_pin(new_pin, salt)
        self._settings["security"]["pin_is_default"] = False
        self.save()

    def verify_pin(self, pin: str) -> bool:
        sec = self._settings.get("security", {})
        salt = sec.get("pin_salt", "")
        expected = sec.get("pin_hash", "")
        if not salt or not expected:
            return False
        return secrets.compare_digest(self._hash_pin(pin, salt), expected)

    def append_audit_log(self, event_type: str, detail: Dict[str, Any]):
        import datetime

        record = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "type": event_type,
            **detail,
        }
        try:
            with self.audit_log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_recent_audit_logs(self, limit: int = 50, filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.audit_log_file.exists():
            return []
        lines = self.audit_log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        results = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if filter_type and item.get("type") != filter_type:
                    continue
                results.append(item)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results
