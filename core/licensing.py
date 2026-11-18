"""
Syntra 客戶端離線授權驗章核心 (Ed25519 Public-Key Only)
僅內建官方發行商公鑰，絕不包含私鑰。
"""

import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

OFFICIAL_ED25519_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEACV7QSxKa+QXmTwL5Fme2rzaPgKOngLE3naJKJMl5U1g=
-----END PUBLIC KEY-----"""


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode((segment + pad).encode("ascii"))


def _load_public_key(public_key_pem: Optional[str] = None):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pem = (public_key_pem or OFFICIAL_ED25519_PUBLIC_KEY_PEM).strip()
    pub = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not isinstance(pub, Ed25519PublicKey):
        raise ValueError("Invalid Ed25519 public key")
    return pub


def verify_license_token(
    token: str,
    required_dlc_id: Optional[str] = None,
    public_key_pem: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any], str]:
    """驗證兩段式 Ed25519 授權 Token (<payload_b64>.<sig_b64>)。"""
    raw = str(token or "").strip()
    if not raw or "." not in raw:
        return False, {}, "授權憑證格式錯誤（須為兩段式簽章 Token）"

    parts = raw.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False, {}, "授權憑證結構不完整"

    payload_b64, sig_b64 = parts
    try:
        pub = _load_public_key(public_key_pem)
        sig_bytes = _b64url_decode(sig_b64)
        pub.verify(sig_bytes, payload_b64.encode("ascii"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False, {}, "授權憑證數位簽章驗證失敗（可能遭竄改或非官方簽發）"

    if not isinstance(payload, dict):
        return False, {}, "授權內容格式無效"

    if required_dlc_id:
        licensed_dlc = str(payload.get("dlc_id") or "").strip()
        if licensed_dlc not in (required_dlc_id, "all", "*"):
            return False, payload, f"授權模組不符（需要 {required_dlc_id}，憑證為 {licensed_dlc or '未知'}）"

    return True, payload, "授權驗證通過"


def get_stored_dlc_tokens(settings_manager: Any = None) -> Dict[str, str]:
    tokens: Dict[str, str] = {}
    if settings_manager is not None:
        try:
            all_cfg = settings_manager.get_all(mask_secrets=False)
            raw_map = all_cfg.get("dlc_licenses")
            if isinstance(raw_map, dict):
                for k, v in raw_map.items():
                    if isinstance(v, str) and v.strip():
                        tokens[str(k)] = v.strip()
        except Exception:
            pass

    license_file = Path(__file__).resolve().parent.parent / "data" / "dlc_licenses.json"
    if license_file.exists():
        try:
            data = json.loads(license_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, str) and v.strip():
                        tokens.setdefault(str(k), v.strip())
        except Exception:
            pass
    return tokens


def save_dlc_license_token(
    dlc_id: str,
    token: str,
    settings_manager: Any = None,
    public_key_pem: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any], str]:
    ok, payload, msg = verify_license_token(token, required_dlc_id=dlc_id, public_key_pem=public_key_pem)
    if not ok:
        return False, payload, msg

    clean_token = str(token).strip()
    if settings_manager is not None:
        try:
            all_cfg = settings_manager.get_all(mask_secrets=False)
            cur = dict(all_cfg.get("dlc_licenses") or {})
            cur[dlc_id] = clean_token
            settings_manager.update_settings({"dlc_licenses": cur})
        except Exception:
            pass

    license_file = Path(__file__).resolve().parent.parent / "data" / "dlc_licenses.json"
    license_file.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, str] = {}
    if license_file.exists():
        try:
            existing = json.loads(license_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing[dlc_id] = clean_token
    license_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, payload, "授權已驗章並安全寫入本機"


def has_valid_dlc_license(
    settings_manager: Any = None,
    dlc_id: str = "syntra.dlc.security_shield",
    public_key_pem: Optional[str] = None,
) -> Tuple[bool, str]:
    tokens = get_stored_dlc_tokens(settings_manager)
    token = tokens.get(dlc_id) or tokens.get("all") or ""
    if not token:
        return False, "尚未匯入有效授權憑證"
    ok, _payload, msg = verify_license_token(token, required_dlc_id=dlc_id, public_key_pem=public_key_pem)
    return ok, msg


def _content_keys_file() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "dlc_content_keys.json"


def save_dlc_content_key(dlc_id: str, key_b64: str, settings_manager: Any = None) -> None:
    """儲存由後端核銷驗證後下發的 DLC 解密金鑰。"""
    clean_k = str(key_b64 or "").strip()
    if not clean_k:
        return
    if settings_manager is not None:
        try:
            all_cfg = settings_manager.get_all(mask_secrets=False)
            cur = dict(all_cfg.get("dlc_content_keys") or {})
            cur[dlc_id] = clean_k
            settings_manager.update_settings({"dlc_content_keys": cur})
        except Exception:
            pass
    kf = _content_keys_file()
    kf.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, str] = {}
    if kf.exists():
        try:
            loaded = json.loads(kf.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass
    data[dlc_id] = clean_k
    kf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_dlc_content_key(dlc_id: str, settings_manager: Any = None) -> str:
    if settings_manager is not None:
        try:
            cfg = settings_manager.get_all(mask_secrets=False)
            val = (cfg.get("dlc_content_keys") or {}).get(dlc_id)
            if val:
                return str(val).strip()
        except Exception:
            pass
    kf = _content_keys_file()
    if kf.exists():
        try:
            data = json.loads(kf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get(dlc_id):
                return str(data[dlc_id]).strip()
        except Exception:
            pass
    return ""
