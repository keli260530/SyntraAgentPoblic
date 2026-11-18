# -*- coding: utf-8 -*-
"""
core/addon_module_manager.py
============================
Syntra 星樞 · 可選配模組（Mod / DLC 式）擴充管理器

設計理念（對齊 guardian/MODULE.md 規範）：
1. 模組預設不強迫啟用：每個模組目錄下皆含自我描述檔 `module.json`
   （包含 `id`、`name`、`category`、`optional: true`、`installable_later: true`、
   `permissions[]` 知情同意清單與 `not_doing[]` 範疇界線）。
2. 知情同意後啟用：使用者在 UI 檢視權限說明並按同意啟用後，狀態記錄於
   `user_profile/enabled_addons.json`（可隨個人雲端漫遊），並動態掛載該模組的 Agent 工具。
3. 支援事後加裝外部模組包：使用者可隨時從資料夾匯入新的模組包至 `modules/`。
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.user_profile_manager import user_profile_manager


class AddonModuleManager:
    """掃描、知情同意啟用/停用、以及動態載入可選配 DLC 模組"""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.modules_root = self.base_dir / "modules"
        self.modules_root.mkdir(parents=True, exist_ok=True)
        self._loaded_plugins: Dict[str, Any] = {}

    @property
    def state_file(self) -> Path:
        return user_profile_manager.profile_dir / "enabled_addons.json"

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"enabled": {}, "updated_at": ""}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("enabled"), dict):
                return data
        except Exception:
            pass
        return {"enabled": {}, "updated_at": ""}

    def _save_state(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def discover_modules(self) -> List[Dict[str, Any]]:
        """
        掃描專案內所有具備 `module.json` 的可選配模組：
        包含 `guardian/module.json` 與 `modules/*/module.json`。
        """
        candidates: List[Path] = []
        guardian_manifest = self.base_dir / "guardian" / "module.json"
        if guardian_manifest.exists():
            candidates.append(guardian_manifest)

        if self.modules_root.exists():
            for sub in sorted(self.modules_root.iterdir()):
                if sub.is_dir():
                    manifest = sub / "module.json"
                    if manifest.exists():
                        candidates.append(manifest)

        state = self._load_state()
        enabled_map = state.get("enabled", {})
        results: List[Dict[str, Any]] = []

        for manifest_path in candidates:
            try:
                meta = json.loads(manifest_path.read_text(encoding="utf-8"))
                mod_id = str(meta.get("id") or manifest_path.parent.name)
                meta["id"] = mod_id
                meta["folder_path"] = str(manifest_path.parent)
                meta["enabled"] = bool(enabled_map.get(mod_id, {}).get("enabled", False))
                meta["consented_at"] = enabled_map.get(mod_id, {}).get("consented_at", "")
                results.append(meta)
            except Exception:
                continue
        return results

    def get_module(self, module_id: str) -> Optional[Dict[str, Any]]:
        for m in self.discover_modules():
            if m.get("id") == module_id:
                return m
        return None

    def is_enabled(self, module_id: str) -> bool:
        state = self._load_state()
        return bool(state.get("enabled", {}).get(module_id, {}).get("enabled", False))

    def set_module_enabled(self, module_id: str, enabled: bool) -> Dict[str, Any]:
        """使用者閱讀權限說明並確認後，啟用或停用指定選配模組"""
        mod = self.get_module(module_id)
        if not mod:
            return {"ok": False, "error": f"找不到模組：{module_id}"}

        if enabled and mod.get("requires_license"):
            try:
                from core.licensing import has_valid_dlc_license
                lic_ok, _lic_msg = has_valid_dlc_license(dlc_id=module_id)
                if not lic_ok:
                    return {
                        "ok": False,
                        "locked": True,
                        "error": f"此模組「{mod.get('name', module_id)}」尚未解鎖，請先輸入兌換碼向後端完成授權驗證。",
                    }
            except Exception as e:
                return {"ok": False, "error": f"授權檢查失敗：{e}"}

        state = self._load_state()
        enabled_map = state.setdefault("enabled", {})
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")
        enabled_map[module_id] = {
            "enabled": bool(enabled),
            "name": mod.get("name", module_id),
            "consented_at": now_iso if enabled else enabled_map.get(module_id, {}).get("consented_at", ""),
        }
        self._save_state(state)

        if not enabled:
            self._loaded_plugins.pop(module_id, None)
        else:
            self._load_plugin_for_module(mod)

        self.refresh_agent_tool_registry()
        rec_mcps: List[str] = []
        if enabled:
            rec_mcps = [str(m) for m in (mod.get("recommended_mcps") or []) if m]
            if rec_mcps:
                try:
                    from core.mcp_skill_manager import McpSkillManager
                    mcp_mgr = McpSkillManager()
                    for mid in rec_mcps:
                        mcp_mgr.ensure_recommended_mcp(mid, enable=False)
                except Exception:
                    pass
        return {"ok": True, "id": module_id, "enabled": bool(enabled), "recommended_mcps": rec_mcps}

    def install_external_module_folder(self, source_dir: str) -> Dict[str, Any]:
        """
        事後加裝外部模組資料夾（DLC 式安裝）：
        驗證來源資料夾內有合法的 `module.json`，並複製到 `modules/<folder_name>`。
        """
        src = Path(source_dir).expanduser().resolve()
        manifest_file = src / "module.json"
        if not src.is_dir() or not manifest_file.exists():
            return {"ok": False, "error": "選取的資料夾內找不到 module.json 模組描述檔"}
        try:
            meta = json.loads(manifest_file.read_text(encoding="utf-8"))
            mod_id = str(meta.get("id") or src.name).strip()
            if not mod_id:
                return {"ok": False, "error": "module.json 缺少有效的 id 欄位"}
        except Exception as e:
            return {"ok": False, "error": f"無法解析 module.json：{e}"}

        safe_folder = "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in mod_id)
        dst = self.modules_root / safe_folder
        if src != dst.resolve():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

        return {
            "ok": True,
            "id": mod_id,
            "name": meta.get("name", mod_id),
            "installed_path": str(dst),
        }

    # ---- 動態載入選配模組的 .pyd / payload.enc / plugin.py -------------------
    def _load_plugin_for_module(self, mod_meta: Dict[str, Any]) -> Optional[Any]:
        mod_id = mod_meta["id"]
        if mod_id in self._loaded_plugins:
            return self._loaded_plugins[mod_id]

        folder = Path(mod_meta["folder_path"]).resolve()
        entrypoints = mod_meta.get("entrypoints") or {}
        plugin_rel = entrypoints.get("plugin", "plugin.py")
        safe_mod_name = f"syntra_addon_{''.join(c if c.isalnum() else '_' for c in mod_id)}"

        # 1. 優先載入原生編譯二進位 .pyd（若存在）
        pyd_candidates = list(folder.glob("*.pyd"))
        for pyd_path in pyd_candidates:
            if pyd_path.resolve().is_relative_to(folder):
                try:
                    spec = importlib.util.spec_from_file_location(safe_mod_name, pyd_path)
                    if spec and spec.loader:
                        module_obj = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module_obj)
                        self._loaded_plugins[mod_id] = module_obj
                        return module_obj
                except Exception:
                    pass

        # 2. 次優先：載入 AES-256-GCM 加密的 payload.enc（記憶體解密，不在硬碟寫出明文 .py）
        enc_rel = entrypoints.get("encrypted", "payload.enc")
        enc_path = (folder / enc_rel).resolve()
        if enc_path.is_relative_to(folder) and enc_path.exists():
            try:
                from core.dlc_crypto import load_encrypted_module
                from core.licensing import get_dlc_content_key, has_valid_dlc_license

                if mod_meta.get("requires_license"):
                    ok_lic, _ = has_valid_dlc_license(dlc_id=mod_id)
                    if not ok_lic:
                        return None
                ckey = get_dlc_content_key(mod_id)
                if not ckey:
                    return None
                module_obj = load_encrypted_module(enc_path, ckey, mod_id, safe_mod_name)
                self._loaded_plugins[mod_id] = module_obj
                return module_obj
            except Exception:
                return None

        # 3. 開發期或未加密免費模組：載入 .py
        plugin_path = (folder / plugin_rel).resolve()
        if not plugin_path.is_relative_to(folder) or not plugin_path.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location(safe_mod_name, plugin_path)
            if spec and spec.loader:
                module_obj = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module_obj)
                self._loaded_plugins[mod_id] = module_obj
                return module_obj
        except Exception:
            return None
        return None

    def get_active_plugins(self) -> List[Tuple[str, Any]]:
        active: List[Tuple[str, Any]] = []
        for mod in self.discover_modules():
            if mod.get("enabled"):
                if mod.get("requires_license"):
                    try:
                        from core.licensing import has_valid_dlc_license
                        lic_ok, _ = has_valid_dlc_license(dlc_id=mod["id"])
                        if not lic_ok:
                            continue
                    except Exception:
                        continue
                plugin = self._load_plugin_for_module(mod)
                if plugin is not None:
                    active.append((mod["id"], plugin))
        return active

    def get_enabled_prompt_guides(self) -> str:
        """收集所有已啟用且通過授權的 DLC 模組教學引導原則。"""
        guides: List[str] = []
        for _mod_id, plugin in self.get_active_plugins():
            text = ""
            if hasattr(plugin, "get_prompt_guide") and callable(plugin.get_prompt_guide):
                try:
                    text = str(plugin.get_prompt_guide() or "").strip()
                except Exception:
                    text = ""
            if not text:
                raw = getattr(plugin, "PROMPT_GUIDE", "")
                text = str(raw or "").strip()
            if text:
                guides.append(text)
        return "\n\n".join(guides)

    def get_enabled_tool_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        for _mod_id, plugin in self.get_active_plugins():
            mod_specs = getattr(plugin, "TOOL_SPECS", None)
            if isinstance(mod_specs, list):
                specs.extend(mod_specs)
        return specs

    def get_enabled_tool_names(self) -> Set[str]:
        out: Set[str] = set()
        for s in self.get_enabled_tool_specs():
            if isinstance(s, dict):
                nm = s.get("name") or (s.get("function") or {}).get("name")
                if nm:
                    out.add(nm)
        return out

    def get_enabled_read_only_names(self) -> Set[str]:
        ro: Set[str] = set()
        for _mod_id, plugin in self.get_active_plugins():
            mod_ro = getattr(plugin, "READ_ONLY", None)
            if isinstance(mod_ro, (set, list, tuple)):
                ro.update(mod_ro)
        return ro

    def run_addon_tool(self, name: str, args: Dict[str, Any], brain=None) -> Optional[str]:
        for _mod_id, plugin in self.get_active_plugins():
            mod_specs = getattr(plugin, "TOOL_SPECS", [])
            names = {
                (s.get("name") or (s.get("function") or {}).get("name"))
                for s in mod_specs
                if isinstance(s, dict)
            }
            if name in names and hasattr(plugin, "run_tool"):
                res = plugin.run_tool(name, args, brain=brain)
                return str(res)
        return None

    def refresh_agent_tool_registry(self) -> None:
        """
        將主 Agent 內建的日常工具 (daily_life_tools) 與使用者「已勾選啟用」的選配模組工具
        動態同步至 core.local_tools 註冊表；未啟用的選配模組不佔用任何工具定義。
        """
        try:
            from core import local_tools as lt_mod
            from core.daily_life_tools import (
                DAILY_READ_ONLY,
                DAILY_TOOL_NAMES,
                DAILY_TOOL_SPECS,
                run_daily_tool,
            )

            if not hasattr(lt_mod, "_ORIG_TOOL_SPECS"):
                lt_mod._ORIG_TOOL_SPECS = list(lt_mod.TOOL_SPECS)
                lt_mod._ORIG_READ_ONLY = set(lt_mod.READ_ONLY)
                lt_mod._ORIG_RUN_TOOL = lt_mod.run_tool

                async def _dispatched_run_tool(name: str, args: Dict[str, Any], brain=None):
                    if name == "read_local_file":
                        target_p = str(args.get("path", ""))
                        if user_profile_manager.is_protected_profile_path(target_p):
                            return (
                                "❌ [隱私保護攔截] 拒絕直接讀取 user_profile 個資保護資料夾內的原始檔案。"
                                "請改用專用記憶工具 (memory_list) 或對應的個人化模組工具查詢。",
                                None,
                            )
                    if name in DAILY_TOOL_NAMES:
                        return run_daily_tool(name, args, brain=brain), None
                    if name in self.get_enabled_tool_names():
                        out = self.run_addon_tool(name, args, brain=brain)
                        return (out or "（無輸出）"), None
                    return await lt_mod._ORIG_RUN_TOOL(name, args, brain=brain)

                lt_mod.run_tool = _dispatched_run_tool

            combined_specs = (
                list(lt_mod._ORIG_TOOL_SPECS)
                + list(DAILY_TOOL_SPECS)
                + self.get_enabled_tool_specs()
            )
            lt_mod.TOOL_SPECS[:] = combined_specs
            lt_mod.TOOL_NAMES.clear()
            lt_mod.TOOL_NAMES.update(s["name"] for s in combined_specs)
            lt_mod.READ_ONLY.clear()
            lt_mod.READ_ONLY.update(lt_mod._ORIG_READ_ONLY)
            lt_mod.READ_ONLY.update(DAILY_READ_ONLY)
            lt_mod.READ_ONLY.update(self.get_enabled_read_only_names())

            # 同步註冊至 ToolCallECC.TOOL_SCHEMAS 與 tool_labels.TOOL_ACTIONS，確保文字協議模型與步驟顯示完全閉合
            try:
                from core.tool_ecc import ToolCallECC
                from core.tool_labels import TOOL_ACTIONS
                from core.long_term_memory import TOOL_SPECS as MEM_SPECS

                json_type_map = {"string": str, "integer": int, "number": float, "boolean": bool}
                for spec in combined_specs + list(MEM_SPECS):
                    t_name = spec.get("name")
                    if not t_name:
                        continue
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
                    "daily_organize_files": "整理桌面或下載區檔案",
                    "daily_undo_organize": "還原最近一次整理的檔案",
                    "daily_switch_scene": "切換日常電腦情境模式",
                    "daily_wellbeing_report": "統計電腦用機時間與護眼報告",
                    "memory_save": "記住你的個人偏好",
                    "memory_forget": "刪除一筆長期記憶",
                    "memory_list": "查看長期記憶清單",
                    "finance_record_entry": "新增收支記帳紀錄",
                    "finance_parse_receipt_text": "解析發票收據並自動入帳",
                    "finance_monthly_report": "產生月度財務與報稅統計",
                    "finance_export_csv": "匯出財務帳本 CSV",
                    "research_save_paper": "收藏學術論文與研究筆記",
                    "research_query_library": "搜尋個人研究文獻庫",
                    "research_generate_citation": "產生論文引用格式",
                    "health_log_record": "記錄飲水或健康習慣打卡",
                    "health_today_summary": "查看今日健康與飲水進度",
                })
            except Exception:
                pass
        except Exception:
            pass


# 全域單例
addon_module_manager = AddonModuleManager()
addon_module_manager.refresh_agent_tool_registry()
