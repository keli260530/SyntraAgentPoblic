# -*- coding: utf-8 -*-
"""
Syntra 星樞 · 官方密碼學簽章驗證與零停機熱更新引擎 (Hot-Update & Signed DLC/DLL Verifier)

核心能力：
1. 自家更新檔與 DLC / DLL 數位簽章認證 (Ed25519 非對稱公私鑰 + HMAC-SHA256 雙重防護)：
   - 每個官方熱更新包 (`update_bundle.json` / 資料夾) 與每個選配 DLC 模組 (`modules/<id>/signature.json`)
     均包含清單內所有 `.py`、`.json`、`.dll`、`.pyd` 檔案的 SHA-256 雜湊與官方簽章。
   - 嚴格防止未簽章代碼、竄改後的模組、或惡意側載 (DLL Hijacking / 未列管 `.dll`/`.py`) 被載入。
2. 不關閉主程式的零停機熱更新 (`apply_hot_update` / `hot_reload_module`)：
   - 驗證官方簽章通過後 -> 暫時與 `SelfDefenseImmortal` 協調解鎖目標核心檔案 -> 建立原子級回滾快照 ->
     寫入更新檔 -> 使用 `importlib.reload` 與動態方法重綁定 (Method Re-binding) 即時更新記憶體中的 Agent 邏輯 ->
     重新上鎖核心檔案並更新共生基因膠囊 (`syntra_gene.capsule`)，全程不關閉視窗、不中斷對話。
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import importlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
KEYS_DIR = BASE_DIR / "data" / ".publisher_keys"
BACKUP_DIR = BASE_DIR / "data" / ".hot_update_backups"

# 受簽章列管的敏感執行檔與模組副檔名（若資料夾內出現未列管之此類檔案，一律視為側載攻擊拒絕載入）
VERIFIED_EXTENSIONS = {".py", ".json", ".dll", ".pyd", ".so", ".exe", ".bat", ".ps1"}

# 禁止任何熱更新覆寫的使用者個資與機密金鑰路徑
FORBIDDEN_UPDATE_PREFIXES = (
    "user_profile/",
    "data/api_providers.json",
    "data/settings.json",
    ".env",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class SyntraSignatureAuthority:
    """
    Syntra 官方發行商簽章與驗證中心：
    優先採用 Ed25519 非對稱數位簽章（若環境具備 cryptography），並同時附上本機強化金鑰衍生之 HMAC-SHA256 雙因子簽章。
    """

    PUBLISHER_ID = "Syntra-Official-Publisher-v1"

    def __init__(self, keys_dir: Optional[Path] = None):
        self.keys_dir = Path(keys_dir) if keys_dir else KEYS_DIR
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        self._priv_key_path = self.keys_dir / "publisher_ed25519.key"
        self._pub_key_path = self.keys_dir / "publisher_ed25519.pub"
        self._hmac_secret_path = self.keys_dir / "publisher_hmac.secret"
        self._ensure_keys()

    def _ensure_keys(self) -> None:
        if not self._hmac_secret_path.exists():
            import secrets
            seed = secrets.token_bytes(32)
            self._hmac_secret_path.write_bytes(seed.hex().encode("ascii"))

        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ed25519

            if not self._priv_key_path.exists() or not self._pub_key_path.exists():
                priv = ed25519.Ed25519PrivateKey.generate()
                pub = priv.public_key()
                self._priv_key_path.write_bytes(
                    priv.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
                self._pub_key_path.write_bytes(
                    pub.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                )
        except Exception:
            pass

    def get_public_key_fingerprint(self) -> str:
        if self._pub_key_path.exists():
            return _sha256_bytes(self._pub_key_path.read_bytes())[:16]
        return _sha256_bytes(self._hmac_secret_path.read_bytes())[:16]

    def sign_payload(self, payload_dict: Dict[str, Any]) -> Dict[str, str]:
        raw = _canonical_json(payload_dict)
        secret = bytes.fromhex(self._hmac_secret_path.read_text(encoding="ascii").strip())
        hmac_sig = hmac.new(secret, raw, hashlib.sha256).hexdigest()

        ed_sig_hex = ""
        scheme = "HMAC-SHA256"
        try:
            from cryptography.hazmat.primitives import serialization
            if self._priv_key_path.exists():
                priv = serialization.load_pem_private_key(self._priv_key_path.read_bytes(), password=None)
                ed_sig_hex = priv.sign(raw).hex()
                scheme = "Ed25519+HMAC-SHA256"
        except Exception:
            pass

        return {
            "publisher": self.PUBLISHER_ID,
            "scheme": scheme,
            "key_fingerprint": self.get_public_key_fingerprint(),
            "ed25519_signature": ed_sig_hex,
            "hmac_sha256": hmac_sig,
        }

    def verify_payload(self, payload_dict: Dict[str, Any], sig_block: Dict[str, Any]) -> Tuple[bool, str]:
        if not isinstance(sig_block, dict):
            return False, "缺少數位簽章區塊 (signature_block)"
        if sig_block.get("publisher") != self.PUBLISHER_ID:
            return False, f"發行商身分不符：{sig_block.get('publisher')}"

        raw = _canonical_json(payload_dict)

        # 1. 驗證 HMAC-SHA256
        expected_hmac = ""
        try:
            secret = bytes.fromhex(self._hmac_secret_path.read_text(encoding="ascii").strip())
            expected_hmac = hmac.new(secret, raw, hashlib.sha256).hexdigest()
        except Exception as e:
            return False, f"讀取驗證金鑰失敗：{e}"

        actual_hmac = str(sig_block.get("hmac_sha256") or "")
        if not actual_hmac or not hmac.compare_digest(expected_hmac, actual_hmac):
            return False, "HMAC-SHA256 數位簽章驗證失敗（檔案可能遭竄改或非自家官方簽發）"

        # 2. 若本機具備官方 Ed25519 公鑰，一律強制校驗非對稱簽章（禁止降級為純 HMAC）
        ed_sig_hex = str(sig_block.get("ed25519_signature") or "")
        if self._pub_key_path.exists():
            if not ed_sig_hex:
                return False, "缺少 Ed25519 非對稱數位簽章，拒絕降級驗證"
            try:
                from cryptography.hazmat.primitives import serialization
                pub = serialization.load_pem_public_key(self._pub_key_path.read_bytes())
                pub.verify(bytes.fromhex(ed_sig_hex), raw)
            except Exception as e:
                return False, f"Ed25519 非對稱公鑰簽章驗證未通過：{e}"

        return True, f"✅ 官方數位簽章驗證通過 ({sig_block.get('scheme', 'HMAC-SHA256')}, Key={sig_block.get('key_fingerprint')})"


class HotUpdateManager:
    """
    不關閉視窗之零停機熱更新與 DLC / DLL 簽章認證管理器
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else BASE_DIR
        self.authority = SyntraSignatureAuthority()
        self.backup_dir = BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.update_history_path = self.base_dir / "data" / "hot_update_history.json"
        self._security_guard = None

    def bind_security_guard(self, security_guard: Any) -> None:
        self._security_guard = security_guard

    # ------------------------------------------------------------------
    # 1. 簽署與驗證 DLC 選配模組（含 .py / .json / .dll / .pyd）
    # ------------------------------------------------------------------
    def sign_dlc_directory(self, dlc_dir: Path | str, version: str = "1.0.0") -> Dict[str, Any]:
        """
        對整個 DLC 模組資料夾（含 module.json、所有 .py 腳本與 .dll/.pyd 原生擴充庫）計算雜湊並簽發官方 `signature.json`。
        """
        folder = Path(dlc_dir).resolve()
        if not folder.is_dir():
            return {"ok": False, "error": f"找不到模組資料夾：{folder}"}

        mod_json = folder / "module.json"
        if not mod_json.exists():
            return {"ok": False, "error": f"模組資料夾缺少 module.json：{folder}"}

        try:
            meta = json.loads(mod_json.read_text(encoding="utf-8"))
            mod_id = str(meta.get("id") or folder.name)
            version = str(meta.get("version") or version)
        except Exception as e:
            return {"ok": False, "error": f"module.json 解析失敗：{e}"}

        files_hashes: Dict[str, str] = {}
        dll_list: List[str] = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
            for fname in sorted(files):
                if fname == "signature.json" or fname.endswith(".pyc"):
                    continue
                fpath = Path(root) / fname
                ext = fpath.suffix.lower()
                if ext in VERIFIED_EXTENSIONS:
                    rel = str(fpath.relative_to(folder)).replace("\\", "/")
                    files_hashes[rel] = _sha256_file(fpath)
                    if ext in (".dll", ".pyd", ".so"):
                        dll_list.append(rel)

        payload = {
            "package_type": "syntra_dlc_module",
            "module_id": mod_id,
            "version": version,
            "files_sha256": files_hashes,
            "native_binaries": dll_list,
        }
        sig_block = self.authority.sign_payload(payload)
        sig_doc = {
            "payload": payload,
            "signature_block": sig_block,
            "signed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        sig_file = folder / "signature.json"
        sig_file.write_text(json.dumps(sig_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "module_id": mod_id,
            "version": version,
            "signed_files_count": len(files_hashes),
            "native_binaries": dll_list,
            "key_fingerprint": sig_block["key_fingerprint"],
            "signature_file": str(sig_file),
        }

    def verify_dlc_directory(self, dlc_dir: Path | str) -> Dict[str, Any]:
        """
        強制驗證 DLC 模組（含其中的 .py 與 .dll/.pyd）是否具備自家官方有效簽章且未被竄改或塞入未列管檔案。
        """
        folder = Path(dlc_dir).resolve()
        sig_file = folder / "signature.json"
        if not sig_file.exists():
            return {
                "ok": False,
                "verified": False,
                "error": f"DLC 模組「{folder.name}」缺少官方簽章檔 (signature.json)，拒絕載入！",
            }

        try:
            sig_doc = json.loads(sig_file.read_text(encoding="utf-8"))
            payload = sig_doc.get("payload") or {}
            sig_block = sig_doc.get("signature_block") or {}
        except Exception as e:
            return {"ok": False, "verified": False, "error": f"讀取 signature.json 失敗：{e}"}

        # 1. 先驗證密碼學簽章
        sig_ok, sig_msg = self.authority.verify_payload(payload, sig_block)
        if not sig_ok:
            return {"ok": False, "verified": False, "error": sig_msg}

        expected_hashes: Dict[str, str] = payload.get("files_sha256") or {}

        # 2. 掃描實際磁碟檔案，檢查是否有任何竄改、遺失或惡意側載之未列管 .py / .dll / .pyd
        actual_files: Dict[str, str] = {}
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
            for fname in sorted(files):
                if fname == "signature.json" or fname.endswith(".pyc"):
                    continue
                fpath = Path(root) / fname
                ext = fpath.suffix.lower()
                if ext in VERIFIED_EXTENSIONS:
                    rel = str(fpath.relative_to(folder)).replace("\\", "/")
                    actual_files[rel] = _sha256_file(fpath)

        for rel, exp_hash in expected_hashes.items():
            act_hash = actual_files.get(rel)
            if not act_hash:
                return {"ok": False, "verified": False, "error": f"DLC 簽章驗證失敗：缺少列管檔案 `{rel}`"}
            if act_hash != exp_hash:
                return {"ok": False, "verified": False, "error": f"DLC 簽章驗證失敗：檔案 `{rel}` 內容已被修改（雜湊不符）！"}

        for rel in actual_files:
            if rel not in expected_hashes:
                return {
                    "ok": False,
                    "verified": False,
                    "error": f"DLC 安全攔截：偵測到未經官方簽章列管的可疑檔案或 DLL `{rel}`（防止 DLL 側載攻擊）！",
                }

        return {
            "ok": True,
            "verified": True,
            "module_id": payload.get("module_id", folder.name),
            "version": payload.get("version", "1.0.0"),
            "verified_files_count": len(actual_files),
            "native_binaries": payload.get("native_binaries", []),
            "scheme": sig_block.get("scheme", "HMAC-SHA256"),
            "key_fingerprint": sig_block.get("key_fingerprint", ""),
            "message": sig_msg,
        }

    # ------------------------------------------------------------------
    # 2. 簽署、驗證與套用「不關閉主程式」之熱更新包 (Hot-Update Bundle)
    # ------------------------------------------------------------------
    def create_signed_hot_update_bundle(
        self,
        files_map: Dict[str, str],
        version: str = "1.1.0",
        description: str = "Syntra 官方熱更新套件",
        output_path: Optional[Path | str] = None,
    ) -> Dict[str, Any]:
        """
        將欲熱更新的檔案集合 `{相對路徑: 完整程式碼或 hex 二進位}` 打包並附上官方 Ed25519 + HMAC-SHA256 數位簽章。
        支援 `.py`、`.json` 以及二進位 `.dll`/`.pyd`（以 `HEX:` 前綴表示二進位內容）。
        """
        normalized_files: Dict[str, str] = {}
        files_sha256: Dict[str, str] = {}

        for rel_path, content in files_map.items():
            clean_rel = rel_path.replace("\\", "/").lstrip("/")
            if ".." in clean_rel.split("/") or any(clean_rel.startswith(p) for p in FORBIDDEN_UPDATE_PREFIXES):
                return {"ok": False, "error": f"禁止將受保護或越權路徑納入更新包：{clean_rel}"}
            if content.startswith("HEX:"):
                raw_bytes = bytes.fromhex(content[4:])
            else:
                raw_bytes = content.encode("utf-8")
            normalized_files[clean_rel] = content
            files_sha256[clean_rel] = _sha256_bytes(raw_bytes)

        payload = {
            "package_type": "syntra_hot_update",
            "version": version,
            "description": description,
            "files_sha256": files_sha256,
        }
        sig_block = self.authority.sign_payload(payload)
        bundle = {
            "payload": payload,
            "files_content": normalized_files,
            "signature_block": sig_block,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if output_path:
            out_p = Path(output_path).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "bundle": bundle,
            "version": version,
            "files_count": len(files_sha256),
            "key_fingerprint": sig_block["key_fingerprint"],
        }

    def verify_hot_update_bundle(self, bundle: Dict[str, Any]) -> Tuple[bool, str]:
        """驗證熱更新包之數位簽章與所有內含檔案/DLL 的 SHA-256 完整性。"""
        if not isinstance(bundle, dict):
            return False, "更新包格式無效"
        payload = bundle.get("payload") or {}
        sig_block = bundle.get("signature_block") or {}
        files_content = bundle.get("files_content") or {}

        if payload.get("package_type") != "syntra_hot_update":
            return False, "非有效的 syntra_hot_update 更新包類型"

        sig_ok, sig_msg = self.authority.verify_payload(payload, sig_block)
        if not sig_ok:
            return False, sig_msg

        expected_hashes: Dict[str, str] = payload.get("files_sha256") or {}
        if set(expected_hashes.keys()) != set(files_content.keys()):
            return False, "更新包檔案清單與實際內容鍵值不符"

        for rel_path, exp_hash in expected_hashes.items():
            clean_rel = rel_path.replace("\\", "/").lstrip("/")
            if ".." in clean_rel.split("/") or any(clean_rel.startswith(p) for p in FORBIDDEN_UPDATE_PREFIXES):
                return False, f"更新包含有禁止修改的敏感路徑：{clean_rel}"
            content = files_content[rel_path]
            raw_bytes = bytes.fromhex(content[4:]) if isinstance(content, str) and content.startswith("HEX:") else str(content).encode("utf-8")
            if _sha256_bytes(raw_bytes) != exp_hash:
                return False, f"更新包內檔案 `{rel_path}` 的 SHA-256 雜湊與簽章不符（疑似遭竄改）"

        return True, sig_msg

    def _unlock_target_files(self, target_paths: List[Path]) -> None:
        """在官方簽章驗證通過後，暫時解除目標檔案的核心防刪鎖以便寫入更新。"""
        sg = self._security_guard
        if sg and hasattr(sg, "self_defense"):
            try:
                sg.self_defense.unlock_all_self_files()
            except Exception:
                pass
        if sg and hasattr(sg, "file_integrity"):
            for p in target_paths:
                try:
                    sg.file_integrity.unlock_file(str(p), mode="kernel")
                except Exception:
                    pass

    def _relock_and_reseal(self) -> None:
        """熱更新寫入完成後，立即重新鎖定核心檔案並更新共生基因膠囊。"""
        sg = self._security_guard
        if sg and hasattr(sg, "self_defense"):
            try:
                if getattr(sg.self_defense, "_active", False) or (
                    sg.self_defense.settings_manager and sg.self_defense.settings_manager.get("enable_self_file_lock", False)
                ):
                    sg.self_defense.lock_all_self_files()
            except Exception:
                pass
        if sg and hasattr(sg, "symbiotic_guardian"):
            try:
                sg.symbiotic_guardian.pack_and_distribute_gene_capsules()
            except Exception:
                pass

    @staticmethod
    def _hot_reload_python_module(rel_path: str) -> Tuple[bool, str]:
        """
        在不關閉行程的情況下，將更新後的 `.py` 模組動態重新載入 (`importlib.reload`)，
        並將新類別的方法同步更新至現有類別定義，達成零停機熱更新。
        """
        clean_rel = rel_path.replace("\\", "/")
        if not clean_rel.endswith(".py"):
            return True, f"非 Python 模組 ({clean_rel}) 已落盤更新"

        mod_name = clean_rel[:-3].replace("/", ".")
        try:
            if mod_name in sys.modules:
                old_mod = sys.modules[mod_name]
                # 先保存舊模組中的 class 參照，reload 後把新方法綁回舊 class 實例上，使運行中的物件立即生效
                old_classes = {
                    k: v for k, v in vars(old_mod).items() if isinstance(v, type)
                }
                reloaded = importlib.reload(old_mod)
                for cls_name, old_cls in old_classes.items():
                    new_cls = getattr(reloaded, cls_name, None)
                    if isinstance(new_cls, type) and new_cls is not old_cls:
                        for attr_k, attr_v in new_cls.__dict__.items():
                            if attr_k in ("__dict__", "__weakref__", "__doc__"):
                                continue
                            try:
                                setattr(old_cls, attr_k, attr_v)
                            except Exception:
                                pass
            else:
                importlib.import_module(mod_name)

            # 重新確保執行期 Hooks 與工具註冊表保持同步
            try:
                from core.user_profile_manager import install_runtime_hooks
                install_runtime_hooks()
            except Exception:
                pass
            return True, f"已動態熱重載模組 `{mod_name}`"
        except Exception as e:
            return False, f"熱重載 `{mod_name}` 失敗：{e}"

    def apply_hot_update(self, bundle_or_path: Dict[str, Any] | str | Path) -> Dict[str, Any]:
        """
        執行完整零停機熱更新閉環：
        1. 驗證官方簽章與 SHA-256（未通過立即阻斷）
        2. 協調解除目標檔案防篡改鎖
        3. 建立原子級回滾快照
        4. 寫入新檔案並對 `.py` 執行記憶體熱重載 (`importlib.reload` + class method sync)
        5. 若重載失敗自動從快照無損回滾；成功則重新上鎖並刷新基因膠囊
        """
        if isinstance(bundle_or_path, (str, Path)):
            p = Path(bundle_or_path).resolve()
            if not p.is_file():
                return {"ok": False, "error": f"找不到熱更新包檔案：{p}"}
            try:
                bundle = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                return {"ok": False, "error": f"解析熱更新包 JSON 失敗：{e}"}
        else:
            bundle = bundle_or_path

        ok_sig, sig_msg = self.verify_hot_update_bundle(bundle)
        if not ok_sig:
            return {"ok": False, "blocked_by_signature": True, "error": f"❌ 熱更新遭安全攔截：{sig_msg}"}

        payload = bundle["payload"]
        version = str(payload.get("version") or "hotfix")
        files_content: Dict[str, str] = bundle["files_content"]

        base_resolved = self.base_dir.resolve()
        target_paths: List[Path] = []
        for rel in files_content:
            clean_rel = str(rel).replace("\\", "/").lstrip("/")
            cand = (base_resolved / clean_rel).resolve()
            if not cand.is_relative_to(base_resolved):
                return {"ok": False, "blocked_by_security": True, "error": f"❌ 熱更新路徑越界攔截：{rel}"}
            target_paths.append(cand)
        snap_dir = self.backup_dir / f"v_{version}_{int(time.time() * 1000)}"
        snap_dir.mkdir(parents=True, exist_ok=True)
        existed_before: Dict[str, bool] = {}

        # 1. 協調暫時解鎖
        self._unlock_target_files(target_paths)

        try:
            # 2. 備份舊檔以供原子回滾
            for rel in files_content:
                clean_rel = rel.replace("\\", "/")
                src_p = self.base_dir / clean_rel
                existed_before[clean_rel] = src_p.exists()
                if src_p.exists():
                    bak_p = snap_dir / clean_rel
                    bak_p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_p, bak_p)

            # 3. 寫入新檔案與動態熱重載
            reloaded_notes: List[str] = []
            for rel, content in files_content.items():
                clean_rel = rel.replace("\\", "/")
                dst_p = self.base_dir / clean_rel
                dst_p.parent.mkdir(parents=True, exist_ok=True)
                raw_bytes = (
                    bytes.fromhex(content[4:])
                    if isinstance(content, str) and content.startswith("HEX:")
                    else str(content).encode("utf-8")
                )
                dst_p.write_bytes(raw_bytes)

            for rel in files_content:
                clean_rel = rel.replace("\\", "/")
                if clean_rel.endswith(".py"):
                    r_ok, r_msg = self._hot_reload_python_module(clean_rel)
                    if not r_ok:
                        raise RuntimeError(r_msg)
                    reloaded_notes.append(r_msg)

            # 若更新涉及 modules/ 下的 DLC，自動重新簽署或刷新 DLC 工具表
            try:
                from core.addon_module_manager import addon_module_manager
                addon_module_manager.refresh_agent_tool_registry()
            except Exception:
                pass

            self._record_update_history(version, list(files_content.keys()), sig_msg)
            return {
                "ok": True,
                "version": version,
                "updated_files": list(files_content.keys()),
                "reloaded": reloaded_notes,
                "signature_status": sig_msg,
                "backup_snapshot": str(snap_dir),
                "message": f"⚡ 已在不關閉程式的情況下完成 v{version} 簽章驗證與熱更新（共更新 {len(files_content)} 個檔案）！",
            }
        except Exception as e:
            # 原子級自動回滾
            for rel, existed in existed_before.items():
                dst_p = self.base_dir / rel
                bak_p = snap_dir / rel
                try:
                    if existed and bak_p.exists():
                        shutil.copy2(bak_p, dst_p)
                        if rel.endswith(".py"):
                            self._hot_reload_python_module(rel)
                    elif not existed and dst_p.exists():
                        dst_p.unlink()
                except Exception:
                    pass
            return {
                "ok": False,
                "rolled_back": True,
                "error": f"熱更新重載過程發生例外，已自動無損回滾至更新前狀態：{e}",
            }
        finally:
            self._relock_and_reseal()

    def _record_update_history(self, version: str, files: List[str], sig_msg: str) -> None:
        history: List[Dict[str, Any]] = []
        if self.update_history_path.exists():
            try:
                history = json.loads(self.update_history_path.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append({
            "version": version,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "files": files,
            "signature_status": sig_msg,
        })
        try:
            self.update_history_path.parent.mkdir(parents=True, exist_ok=True)
            self.update_history_path.write_text(
                json.dumps(history[-50:], ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def ensure_builtin_dlcs_signed(self) -> List[Dict[str, Any]]:
        """確保內建的官方選配模組 (`modules/*`) 皆已具備有效官方數位簽章。"""
        mods_root = self.base_dir / "modules"
        results = []
        if not mods_root.is_dir():
            return results
        for sub in sorted(mods_root.iterdir()):
            if sub.is_dir() and (sub / "module.json").exists():
                v_res = self.verify_dlc_directory(sub)
                if not v_res.get("verified"):
                    self.sign_dlc_directory(sub)
                    v_res = self.verify_dlc_directory(sub)
                results.append(v_res)
        return results

    def get_current_version(self) -> str:
        ver_file = self.base_dir / "data" / "version.json"
        if ver_file.exists():
            try:
                data = json.loads(ver_file.read_text(encoding="utf-8"))
                return str(data.get("version") or "1.0.0")
            except Exception:
                pass
        return "1.0.0"

    def set_current_version(self, version: str) -> None:
        ver_file = self.base_dir / "data" / "version.json"
        ver_file.parent.mkdir(parents=True, exist_ok=True)
        ver_file.write_text(
            json.dumps(
                {"version": version, "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def check_remote_update(
        self,
        feed_url: str = "",
        auto_apply: bool = False,
    ) -> Dict[str, Any]:
        """
        自帶網頁 / 遠端更新檔檢查器：
        1. 從指定的官方更新網址 (`feed_url` 或 `settings.json` 中的 `update_feed_url`，亦支援本地/區域網路發佈路徑)
           取得最新熱更新描述檔 (`syntra_hot_update` JSON)。
        2. 自動比對版本號並強制執行 `verify_hot_update_bundle` 官方數位簽章認證（Ed25519 + HMAC-SHA256）。
        3. 若 `auto_apply=True` 且有新版且簽章合法，直接執行不關機零停機熱更新！
        """
        import urllib.request

        current_ver = self.get_current_version()
        url = (feed_url or "").strip()
        if not url:
            try:
                from core.settings_manager import SettingsManager
                url = str(SettingsManager().get("update_feed_url", "") or "").strip()
            except Exception:
                url = ""

        # 若尚未配置遠端網址，檢查本機/預設發佈交換區 `data/release_channel/latest_update.json`
        local_channel = self.base_dir / "data" / "release_channel" / "latest_update.json"
        raw_bundle: Optional[Dict[str, Any]] = None
        source_desc = url or str(local_channel)

        try:
            if url and (url.startswith("http://") or url.startswith("https://")):
                req = urllib.request.Request(url, headers={"User-Agent": "Syntra-HotUpdater/1.0"})
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    raw_bundle = json.loads(resp.read().decode("utf-8"))
            elif url and Path(url).expanduser().is_file():
                raw_bundle = json.loads(Path(url).expanduser().read_text(encoding="utf-8"))
            elif local_channel.is_file():
                raw_bundle = json.loads(local_channel.read_text(encoding="utf-8"))
            else:
                return {
                    "ok": True,
                    "has_update": False,
                    "current_version": current_ver,
                    "message": f"目前已是最新版本 (v{current_ver})。若要連網檢查自架更新伺服器，可於設定填入 update_feed_url。",
                }
        except Exception as e:
            return {
                "ok": False,
                "current_version": current_ver,
                "source": source_desc,
                "error": f"連線檢查更新來源失敗：{e}",
            }

        ok_sig, sig_msg = self.verify_hot_update_bundle(raw_bundle)
        if not ok_sig:
            return {
                "ok": False,
                "has_update": False,
                "blocked_by_signature": True,
                "current_version": current_ver,
                "source": source_desc,
                "error": f"❌ 偵測到遠端更新檔，但官方數位簽章驗證失敗，已自動拒絕載入：{sig_msg}",
            }

        remote_ver = str((raw_bundle.get("payload") or {}).get("version") or "")
        desc = str((raw_bundle.get("payload") or {}).get("description") or "")
        files_list = list(((raw_bundle.get("payload") or {}).get("files_sha256") or {}).keys())

        has_newer = bool(remote_ver and remote_ver != current_ver)
        result: Dict[str, Any] = {
            "ok": True,
            "has_update": has_newer,
            "current_version": current_ver,
            "remote_version": remote_ver,
            "description": desc,
            "files": files_list,
            "signature_verified": True,
            "signature_status": sig_msg,
            "source": source_desc,
        }
        if has_newer and auto_apply:
            apply_res = self.apply_hot_update(raw_bundle)
            result["applied"] = apply_res
            if apply_res.get("ok"):
                self.set_current_version(remote_ver)
        return result


hot_update_manager = HotUpdateManager()


# ===========================================================================
# Agent 熱更新與 DLC / DLL 簽章認證工具規格與動態掛載 Hooks
# ===========================================================================
HOT_UPDATE_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "hot_update_check_remote",
        "description": "檢查網頁/遠端更新伺服器或發佈通道是否有新版本的自家官方更新檔，自動驗證數位簽章，並可選擇不關機直接套用熱更新。",
        "parameters": {
            "type": "object",
            "properties": {
                "feed_url": {"type": "string", "description": "遠端更新檔 JSON 網址或路徑（留空則使用系統預設更新通道）"},
                "auto_apply": {"type": "boolean", "description": "若發現通過官方簽章認證的新版更新檔，是否立即不關機熱更新（預設 false）"},
            },
        },
    },
    {
        "name": "hot_update_verify",
        "description": "驗證自家熱更新包 (update_bundle.json) 或選配 DLC 模組資料夾（含 .py 與 .dll/.pyd）的官方數位簽章與 SHA-256 完整性。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_path": {
                    "type": "string",
                    "description": "要驗證的熱更新包檔案路徑、DLC 模組資料夾路徑，或填入 'all_dlcs' 檢驗所有已安裝 DLC",
                },
            },
            "required": ["target_path"],
        },
    },
    {
        "name": "hot_update_apply",
        "description": "在不關閉 Syntra 主程式的情況下，驗證官方數位簽章並套用零停機熱更新包（自動協調解鎖、快照備份、importlib.reload 動態重載與重新上鎖）。",
        "parameters": {
            "type": "object",
            "properties": {
                "bundle_path": {
                    "type": "string",
                    "description": "已簽章的官方熱更新包 JSON 檔案路徑，或直接傳入要熱重載的專案相對路徑 (如 core/daily_life_tools.py)",
                },
            },
            "required": ["bundle_path"],
        },
    },
]
HOT_UPDATE_TOOL_NAMES = {s["name"] for s in HOT_UPDATE_TOOL_SPECS}
HOT_UPDATE_READ_ONLY = {"hot_update_verify", "hot_update_check_remote"}


def run_hot_update_tool(name: str, args: Dict[str, Any], brain: Any = None) -> str:
    from core.addon_module_manager import addon_module_manager

    if brain and hasattr(brain, "security_guard"):
        hot_update_manager.bind_security_guard(brain.security_guard)

    if name == "hot_update_check_remote":
        feed_url = str(args.get("feed_url", "")).strip()
        auto_apply = bool(args.get("auto_apply", False))
        res = hot_update_manager.check_remote_update(feed_url=feed_url, auto_apply=auto_apply)
        return json.dumps(res, ensure_ascii=False, indent=2)

    if name == "hot_update_verify":
        target = str(args.get("target_path", "all_dlcs")).strip()
        if target in ("all_dlcs", "all", ""):
            mods = addon_module_manager.discover_modules()
            report = [
                {
                    "id": m["id"],
                    "name": m.get("name"),
                    "verified": m.get("signature_verified", False),
                    "scheme": (m.get("signature_info") or {}).get("scheme", ""),
                    "key_fingerprint": (m.get("signature_info") or {}).get("key_fingerprint", ""),
                    "verified_files_count": (m.get("signature_info") or {}).get("verified_files_count", 0),
                    "native_binaries": (m.get("signature_info") or {}).get("native_binaries", []),
                    "message": (m.get("signature_info") or {}).get("message")
                    or (m.get("signature_info") or {}).get("error", ""),
                }
                for m in mods
            ]
            return json.dumps({"ok": True, "dlc_verifications": report}, ensure_ascii=False, indent=2)

        p = Path(target).expanduser()
        if not p.is_absolute():
            p = (hot_update_manager.base_dir / p).resolve()
        if p.is_dir():
            return json.dumps(hot_update_manager.verify_dlc_directory(p), ensure_ascii=False, indent=2)
        if p.is_file():
            try:
                bundle = json.loads(p.read_text(encoding="utf-8"))
                ok, msg = hot_update_manager.verify_hot_update_bundle(bundle)
                return json.dumps({"ok": ok, "verified": ok, "message": msg}, ensure_ascii=False, indent=2)
            except Exception as e:
                return json.dumps({"ok": False, "verified": False, "error": str(e)}, ensure_ascii=False, indent=2)
        return json.dumps({"ok": False, "error": f"找不到目標路徑：{target}"}, ensure_ascii=False)

    if name == "hot_update_apply":
        bpath = str(args.get("bundle_path", "")).strip()
        p = Path(bpath).expanduser()
        if not p.is_absolute():
            p = (hot_update_manager.base_dir / p).resolve()
        res = hot_update_manager.apply_hot_update(p)
        return json.dumps(res, ensure_ascii=False, indent=2)

    return json.dumps({"ok": False, "error": f"未知熱更新工具：{name}"}, ensure_ascii=False)


def install_hot_update_and_dlc_hooks() -> None:
    """
    將官方數位簽章驗證與零停機熱更新能力掛載至 `AddonModuleManager`、`SecurityGuard` 與 `local_tools`。
    """
    from core.addon_module_manager import AddonModuleManager, addon_module_manager
    from core.security_guard import SecurityGuard

    if getattr(AddonModuleManager, "_hot_update_hooked", False):
        return

    # 1. 不在啟動時自動補簽任何模組（防止竄改或側載模組被自動洗白）

    # 2. 包裝 AddonModuleManager.discover_modules：附上 signature_verified 與 signature_info
    _orig_discover = AddonModuleManager.discover_modules

    def _patched_discover_modules(self) -> List[Dict[str, Any]]:
        mods = _orig_discover(self)
        for m in mods:
            folder = m.get("folder_path", "")
            if folder:
                v_res = hot_update_manager.verify_dlc_directory(folder)
                m["signature_verified"] = bool(v_res.get("verified", False))
                m["signature_info"] = v_res
        return mods

    AddonModuleManager.discover_modules = _patched_discover_modules

    # 3. 包裝 AddonModuleManager.set_module_enabled：啟用前強制驗證官方數位簽章
    _orig_set_enabled = AddonModuleManager.set_module_enabled

    def _patched_set_module_enabled(self, module_id: str, enabled: bool) -> Dict[str, Any]:
        if enabled:
            mod = self.get_module(module_id)
            if not mod:
                return {"ok": False, "error": f"找不到模組：{module_id}"}
            sig_res = hot_update_manager.verify_dlc_directory(mod["folder_path"])
            if not sig_res.get("verified"):
                return {
                    "ok": False,
                    "blocked_by_signature": True,
                    "error": f"❌ DLC 數位簽章認證失敗，拒絕啟用：{sig_res.get('error')}",
                }
        return _orig_set_enabled(self, module_id, enabled)

    AddonModuleManager.set_module_enabled = _patched_set_module_enabled

    # 4. 包裝 AddonModuleManager.install_external_module_folder：匯入外部 DLC 時強制驗證簽章与 DLL 完整性
    _orig_install_ext = AddonModuleManager.install_external_module_folder

    def _patched_install_external(self, source_dir: str, sign_as_official: bool = False) -> Dict[str, Any]:
        src = Path(source_dir).expanduser().resolve()
        manifest_file = src / "module.json"
        if not src.is_dir() or not manifest_file.exists():
            return {"ok": False, "error": "選取的資料夾內找不到 module.json 模組描述檔"}
        if sign_as_official:
            try:
                meta = json.loads(manifest_file.read_text(encoding="utf-8"))
                hot_update_manager.sign_dlc_directory(src, version=str(meta.get("version", "1.0.0")))
            except Exception:
                pass
        sig_res = hot_update_manager.verify_dlc_directory(src)
        if not sig_res.get("verified"):
            return {
                "ok": False,
                "blocked_by_signature": True,
                "error": f"❌ 外部 DLC 模組未通過官方數位簽章認證（含 .py / .dll 完整性檢查），已拒絕加裝：\n{sig_res.get('error')}",
            }
        res = _orig_install_ext(self, source_dir)
        if res.get("ok"):
            res["signature_info"] = sig_res
        return res

    AddonModuleManager.install_external_module_folder = _patched_install_external

    # 5. 包裝 AddonModuleManager._load_plugin_for_module：每次載入與執行前皆驗證簽章，防止事後被竄改或塞入惡意 DLL
    _orig_load_plugin = AddonModuleManager._load_plugin_for_module

    def _patched_load_plugin(self, mod_meta: Dict[str, Any]) -> Optional[Any]:
        folder = Path(mod_meta["folder_path"])
        sig_res = hot_update_manager.verify_dlc_directory(folder)
        if not sig_res.get("verified"):
            self._loaded_plugins.pop(mod_meta["id"], None)
            return None
        return _orig_load_plugin(self, mod_meta)

    AddonModuleManager._load_plugin_for_module = _patched_load_plugin

    # 6. 擴充 refresh_agent_tool_registry 掛入 hot_update_* 工具
    _orig_refresh_registry = AddonModuleManager.refresh_agent_tool_registry

    def _patched_refresh_registry(self) -> None:
        _orig_refresh_registry(self)
        try:
            from core import local_tools as lt_mod
            from core.tool_ecc import ToolCallECC
            from core.tool_labels import TOOL_ACTIONS

            prev_run = lt_mod.run_tool

            async def _hot_dispatched_run(name: str, args: Dict[str, Any], brain=None):
                if name in HOT_UPDATE_TOOL_NAMES:
                    return run_hot_update_tool(name, args, brain=brain), None
                return await prev_run(name, args, brain=brain)

            if not getattr(lt_mod.run_tool, "_has_hot_update_dispatch", False):
                _hot_dispatched_run._has_hot_update_dispatch = True
                lt_mod.run_tool = _hot_dispatched_run

            existing_names = {s["name"] for s in lt_mod.TOOL_SPECS if isinstance(s, dict) and s.get("name")}
            for spec in HOT_UPDATE_TOOL_SPECS:
                if spec["name"] not in existing_names:
                    lt_mod.TOOL_SPECS.append(spec)
                    lt_mod.TOOL_NAMES.add(spec["name"])
            lt_mod.READ_ONLY.update(HOT_UPDATE_READ_ONLY)

            json_type_map = {"string": str, "integer": int, "number": float, "boolean": bool}
            for spec in HOT_UPDATE_TOOL_SPECS:
                t_name = spec["name"]
                params = spec.get("parameters", {})
                props = params.get("properties", {})
                reqs = list(params.get("required", []))
                opts = [k for k in props.keys() if k not in reqs]
                types_dict = {
                    k: json_type_map[v.get("type")]
                    for k, v in props.items()
                    if isinstance(v, dict) and v.get("type") in json_type_map
                }
                ToolCallECC.TOOL_SCHEMAS[t_name] = {
                    "required": reqs,
                    "optional": opts,
                    "types": types_dict,
                    "description": spec.get("description", ""),
                }

            TOOL_ACTIONS.update({
                "hot_update_verify": "驗證官方熱更新檔與 DLC/DLL 數位簽章",
                "hot_update_apply": "執行不關機零停機熱更新",
                "hot_update_sign_package": "簽署自家官方更新檔或 DLC/DLL 模組",
            })
        except Exception:
            pass

    AddonModuleManager.refresh_agent_tool_registry = _patched_refresh_registry

    # 7. 綁定 SecurityGuard 實例，讓熱更新時能合法解鎖與重新上鎖
    _orig_sg_init = SecurityGuard.__init__

    def _patched_sg_init(self, *args, **kwargs):
        _orig_sg_init(self, *args, **kwargs)
        hot_update_manager.bind_security_guard(self)

    SecurityGuard.__init__ = _patched_sg_init

    AddonModuleManager._hot_update_hooked = True
    addon_module_manager.refresh_agent_tool_registry()


install_hot_update_and_dlc_hooks()
