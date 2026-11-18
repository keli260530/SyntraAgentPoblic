import asyncio
import base64
import ctypes
from ctypes import wintypes
import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import urllib.parse
import httpx

# 本地模型服務（Ollama / LM Studio 等）不驗證金鑰，但 OpenAI 相容協定仍需帶 Authorization 標頭
LOCAL_PLACEHOLDER_KEY = "local-no-key"


def is_local_endpoint(base_url: str) -> bool:
    """端點是否為本機回環位址（本地模型免填 API Key）"""
    try:
        host = (urllib.parse.urlparse((base_url or "").strip()).hostname or "").lower()
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

def _dpapi_protect(text: str) -> str:
    """使用 Windows DPAPI 加密敏感字串，防止電腦上既有的木馬或竊密軟體 (Infostealer) 偷取 API Key"""
    if not text or not text.strip():
        return ""
    if text.startswith("DPAPI:"):
        return text
    try:
        raw_bytes = text.encode("utf-8")
        in_blob = DATA_BLOB(len(raw_bytes), ctypes.cast(ctypes.create_string_buffer(raw_bytes), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(in_blob), "AgentSecret", None, None, None, 0x01, ctypes.byref(out_blob)):
            enc = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return "DPAPI:" + base64.b64encode(enc).decode("ascii")
    except Exception:
        pass
    return text

def _dpapi_unprotect(text: str) -> str:
    """解密 Windows DPAPI 密文，僅限本機當前登入者可解密"""
    if not text or not text.startswith("DPAPI:"):
        return text
    try:
        enc = base64.b64decode(text[6:])
        in_blob = DATA_BLOB(len(enc), ctypes.cast(ctypes.create_string_buffer(enc), ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0x01, ctypes.byref(out_blob)):
            dec = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)
            return dec.decode("utf-8")
    except Exception:
        pass
    return text


class ApiManager:
    """
    多組 API Key 與自訂 Provider 接入管理器：
    支援使用者手動新增、編輯、刪除多組 API 連線（Gemini / OpenAI / Anthropic / DeepSeek / OpenRouter 等）。
    持久化存儲於 data/providers.json。
    """

    PRESETS = {
        "gemini": {
            "name": "Google Gemini (OpenAI 兼容)",
            "protocol": "openai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        },
        "openai": {
            "name": "OpenAI 官方",
            "protocol": "openai",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-4o", "gpt-4.1", "o3-mini"],
        },
        "anthropic": {
            "name": "Anthropic Claude",
            "protocol": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "models": ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest"],
        },
        "deepseek": {
            "name": "DeepSeek 官方",
            "protocol": "openai",
            "base_url": "https://api.deepseek.com/v1",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
        "openrouter": {
            "name": "OpenRouter",
            "protocol": "openai",
            "base_url": "https://openrouter.ai/api/v1",
            "models": ["google/gemini-2.5-pro", "anthropic/claude-3.7-sonnet", "openai/gpt-4o"],
        },
        "groq": {
            "name": "Groq 高速推理",
            "protocol": "openai",
            "base_url": "https://api.groq.com/openai/v1",
            "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
        },
        "nvidia": {
            "name": "NVIDIA NIM",
            "protocol": "openai",
            "base_url": "https://integrate.api.nvidia.com/v1",
            "models": ["deepseek-ai/deepseek-r1", "meta/llama-3.2-11b-vision-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"],
        },
        "ollama": {
            "name": "Ollama 本地模型",
            "protocol": "openai",
            "base_url": "http://127.0.0.1:11434/v1",
            "models": ["gpt-oss:20b", "gemma3:12b"],
        },
    }

    def __init__(self, data_dir: Optional[Path] = None):
        base_dir = Path(__file__).resolve().parent.parent
        self.data_dir = data_dir or (base_dir / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.data_dir / "api_providers.json"
        self.providers: List[Dict[str, Any]] = self._load()
        self.security_guard = None
        self._change_callbacks: List[Callable] = []

    def set_security_guard(self, security_guard: Any):
        self.security_guard = security_guard

    def register_change_callback(self, cb: Callable):
        """註冊 API 異動通知監聽器 (當有新增、修改、刪除時觸發)"""
        if not hasattr(self, "_change_callbacks"):
            self._change_callbacks = []
        self._change_callbacks.append(cb)

    def _notify_change(self, event_type: str, info: Dict[str, Any], source: str):
        """推播 API 異動即時安全通知給所有監聽通道 (Discord, System Tray, Web, Audit Log)"""
        if not hasattr(self, "_change_callbacks"):
            self._change_callbacks = []

        action_map = {
            "ADDED": ("🟢 新增 API Provider", "新增了"),
            "MODIFIED": ("🟡 修改 API Provider", "修改了"),
            "DELETED": ("🔴 刪除 API Provider", "刪除了"),
        }
        header, verb = action_map.get(event_type, ("ℹ️ API 異動", "異動了"))

        msg = (
            f"🔔 **【API 設定異動安全通知】**\n"
            f"系統檢測到 {source} {verb} API 連線設定：\n"
            f"• **動作類別**：{header}\n"
            f"• **服務商名稱**：`{info['name']}` (ID: `{info['id']}`)\n"
            f"• **端點 (Base URL)**：`{info['base_url']}`\n"
            f"• **協定類型**：`{info['protocol'].upper()}`\n"
            f"• **金鑰狀態**：`{info['masked_key']}`\n"
            f"• **異動明細**：{', '.join(info['changes'])}\n"
            f"• **異動來源**：`{source}`\n"
            f"• **紀錄時間**：`{info['timestamp']}`\n"
            f"⚠️ *若非你本人操作，請立刻檢查金鑰或按下緊急停止 (Ctrl+Alt+Q)！*"
        )

        for cb in self._change_callbacks:
            try:
                res = cb(event_type, info, source, msg)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception:
                pass

    def _default_providers(self) -> List[Dict[str, Any]]:
        # 預設範本清單（未填 Key）
        return [
            {
                "id": "gemini_default",
                "name": "Google Gemini",
                "protocol": "openai",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "api_key": "",
                "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
                "enabled": True,
            },
            {
                "id": "openai_default",
                "name": "OpenAI",
                "protocol": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "models": ["gpt-4o", "gpt-4.1", "o3-mini"],
                "enabled": True,
            },
            {
                "id": "anthropic_default",
                "name": "Anthropic Claude",
                "protocol": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
                "api_key": "",
                "models": ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest"],
                "enabled": True,
            },
            {
                "id": "deepseek_default",
                "name": "DeepSeek",
                "protocol": "openai",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "",
                "models": ["deepseek-chat", "deepseek-reasoner"],
                "enabled": True,
            },
            {
                "id": "openrouter_default",
                "name": "OpenRouter",
                "protocol": "openai",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "",
                "models": ["google/gemini-2.5-pro", "anthropic/claude-3.7-sonnet", "openai/gpt-4o"],
                "enabled": True,
            },
        ]

    def _load(self) -> List[Dict[str, Any]]:
        if self.file_path.exists():
            try:
                data = json.loads(self.file_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        raw_k = item.get("api_key", "")
                        if raw_k:
                            item["api_key"] = _dpapi_unprotect(raw_k)
                    return data
            except Exception:
                pass
        defaults = self._default_providers()
        self._save(defaults)
        return defaults

    def _save(self, providers: List[Dict[str, Any]]):
        to_save = []
        for p in providers:
            item = dict(p)
            k = item.get("api_key", "")
            if k:
                item["api_key"] = _dpapi_protect(k)
            to_save.append(item)
        self.file_path.write_text(
            json.dumps(to_save, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def save(self):
        self._save(self.providers)

    def get_providers(self, mask_keys: bool = True) -> List[Dict[str, Any]]:
        results = []
        for p in self.providers:
            item = dict(p)
            key = item.get("api_key", "").strip()
            item["has_key"] = bool(key)
            if mask_keys:
                item["masked_key"] = (
                    f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("已設定" if key else "未設定")
                )
                item["api_key"] = ""
            results.append(item)
        return results

    def get_models_catalog(self) -> List[Dict[str, Any]]:
        catalog = []
        for p in self.providers:
            if not p.get("enabled", True):
                continue
            # 本地端點免 Key 即可使用，視同「有 Key」以免被路由器排除
            has_key = bool(p.get("api_key", "").strip()) or is_local_endpoint(p.get("base_url", ""))
            models = p.get("models") or ["default-model"]
            for m in models:
                m_str = m.strip() if isinstance(m, str) else str(m)
                full_id = f"{p['id']}:{m_str}"
                catalog.append({
                    "full_id": full_id,
                    "provider_id": p["id"],
                    "provider_name": p.get("name", p["id"]),
                    "model_id": m_str,
                    "display_name": f"{p.get('name', p['id'])} · {m_str}",
                    "has_key": has_key,
                    "base_url": p.get("base_url", ""),
                    "protocol": p.get("protocol", "openai"),
                })
        return catalog

    def get_connection(self, full_model_id: Optional[str] = None) -> Dict[str, Any]:
        """依 full_model_id (格式 'provider_id:model_name') 取得連線設定"""
        catalog = self.get_models_catalog()

        target_item = None
        if full_model_id:
            for item in catalog:
                if item["full_id"] == full_model_id or item["model_id"] == full_model_id:
                    target_item = item
                    break

        # 優先回傳有 Key 的目標，若無指定則找第一個有 Key 的
        if not target_item:
            for item in catalog:
                if item["has_key"]:
                    target_item = item
                    break

        if not target_item and catalog:
            target_item = catalog[0]

        if target_item:
            # 找到原始 provider 取得未遮罩之 api_key
            prov = next((p for p in self.providers if p["id"] == target_item["provider_id"]), {})
            api_key = prov.get("api_key", "").strip()
            if not api_key and is_local_endpoint(prov.get("base_url", "")):
                api_key = LOCAL_PLACEHOLDER_KEY
            return {
                "provider_id": prov.get("id", ""),
                "provider_name": prov.get("name", ""),
                "model_id": target_item["model_id"],
                "full_id": target_item["full_id"],
                "api_key": api_key,
                "base_url": prov.get("base_url", "").strip(),
                "protocol": prov.get("protocol", "openai"),
            }

        return {
            "provider_id": "",
            "provider_name": "未設定",
            "model_id": "gemini-2.5-pro",
            "full_id": "",
            "api_key": "",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "protocol": "openai",
        }

    def upsert_provider(self, data: Dict[str, Any], source: str = "User") -> Dict[str, Any]:
        if self.security_guard and hasattr(self.security_guard, "validate_api_provider"):
            valid, err_msg, _ = self.security_guard.validate_api_provider(data, caller_is_agent=(source == "Agent 自主操作"))
            if not valid:
                raise ValueError(err_msg)

        pid = (data.get("id") or f"custom_{len(self.providers) + 1}").strip()
        name = (data.get("name") or pid).strip()
        protocol = data.get("protocol", "openai").strip().lower()
        base_url = data.get("base_url", "").strip()
        new_key = data.get("api_key", "").strip()
        enabled = data.get("enabled", True)

        raw_models = data.get("models") or []
        if isinstance(raw_models, str):
            models = [m.strip() for m in raw_models.replace("，", ",").split(",") if m.strip()]
        else:
            models = [str(m).strip() for m in raw_models if str(m).strip()]
        if not models:
            models = ["default-model"]

        # 尋找是否已有此 provider
        idx = next((i for i, p in enumerate(self.providers) if p["id"] == pid), None)
        changes = []
        if idx is not None:
            existing = self.providers[idx]
            event_type = "MODIFIED"
            if existing.get("name") != name:
                changes.append(f"名稱: {existing.get('name')} -> {name}")
            if existing.get("base_url") != base_url:
                changes.append(f"端點: {existing.get('base_url')} -> {base_url}")
            if existing.get("protocol") != protocol:
                changes.append(f"協定: {existing.get('protocol')} -> {protocol}")
            if new_key and "..." not in new_key and new_key != existing.get("api_key"):
                changes.append("API Key 已更新")
                existing["api_key"] = new_key
            if existing.get("models") != models:
                changes.append(f"模型清單更新 ({len(models)} 個模型)")
            if not changes:
                changes.append("設定內容覆寫保存")

            existing["name"] = name
            existing["protocol"] = protocol
            existing["base_url"] = base_url
            existing["models"] = models
            existing["enabled"] = enabled
            target = existing
        else:
            event_type = "ADDED"
            changes.append("建立全新 API Provider 項目")
            target = {
                "id": pid,
                "name": name,
                "protocol": protocol,
                "base_url": base_url,
                "api_key": new_key,
                "models": models,
                "enabled": enabled,
            }
            self.providers.append(target)

        self.save()

        # 產生脫敏 Key 資訊供通知使用
        active_key = target.get("api_key", "")
        masked_key = f"{active_key[:4]}...{active_key[-4:]}" if len(active_key) > 8 else ("已設定" if active_key else "未設定")

        info = {
            "id": pid,
            "name": name,
            "protocol": protocol,
            "base_url": base_url,
            "models": models,
            "masked_key": masked_key,
            "changes": changes,
            "source": source,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._notify_change(event_type, info, source=source)
        return target

    def delete_provider(self, provider_id: str, source: str = "User") -> bool:
        initial_len = len(self.providers)
        deleted_item = next((p for p in self.providers if p["id"] == provider_id), None)
        self.providers = [p for p in self.providers if p["id"] != provider_id]
        if len(self.providers) < initial_len:
            self.save()
            if deleted_item:
                active_key = deleted_item.get("api_key", "")
                masked_key = f"{active_key[:4]}...{active_key[-4:]}" if len(active_key) > 8 else ("已設定" if active_key else "未設定")
                info = {
                    "id": provider_id,
                    "name": deleted_item.get("name", provider_id),
                    "protocol": deleted_item.get("protocol", "openai"),
                    "base_url": deleted_item.get("base_url", ""),
                    "models": deleted_item.get("models", []),
                    "masked_key": masked_key,
                    "changes": ["已被刪除並從系統中移除"],
                    "source": source,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._notify_change("DELETED", info, source=source)
            return True
        return False

    async def fetch_available_models(
        self, api_key: str, base_url: str, protocol: str = "openai"
    ) -> Dict[str, Any]:
        """
        向服務商端點動態查詢該 API Key 支援的所有可用模型清單 (支援 Google Gemini 雙通道、OpenAI、Anthropic 等)
        """
        key = api_key.strip().strip("'\"")
        url_base = base_url.strip().rstrip("/")
        proto = protocol.lower()

        if not key and is_local_endpoint(url_base):
            key = LOCAL_PLACEHOLDER_KEY
        if not key:
            return {"ok": False, "error": "尚未輸入 API Key！", "models": []}

        # 針對 Google Gemini (專有原生 REST + OpenAI 雙通道自動容錯)
        is_gemini = "googleapis.com" in url_base or key.startswith("AIzaSy")
        if is_gemini:
            gemini_models = await self._fetch_gemini_models_dual_channel(key, url_base)
            if gemini_models.get("ok"):
                return gemini_models
            # 若專有管道未成功，繼續執行通用 OpenAI 相容邏輯

        if not url_base:
            return {"ok": False, "error": "Base URL 端點不能為空！", "models": []}

        try:
            if url_base.endswith("/chat/completions"):
                url_base = url_base[:-len("/chat/completions")]
            elif url_base.endswith("/messages"):
                url_base = url_base[:-len("/messages")]

            if proto == "anthropic":
                url = f"{url_base}/models" if not url_base.endswith("/models") else url_base
                headers = {
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                }
            else:
                url = f"{url_base}/models" if not url_base.endswith("/models") else url_base
                headers = {
                    "Authorization": f"Bearer {key}",
                }

            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(url, headers=headers)
                # 若 404 且 url_base 缺少 /v1，嘗試補上 /v1
                if resp.status_code == 404 and not url_base.endswith("/v1") and proto != "anthropic":
                    fallback_url = f"{url_base}/v1/models"
                    resp = await client.get(fallback_url, headers=headers)

                if resp.status_code >= 300:
                    return {
                        "ok": False,
                        "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                        "models": [],
                    }
                data = resp.json()
                models: List[str] = []
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list):
                        for item in data["data"]:
                            if isinstance(item, dict) and "id" in item:
                                models.append(str(item["id"]))
                            elif isinstance(item, str):
                                models.append(item)
                    elif "models" in data and isinstance(data["models"], list):
                        for item in data["models"]:
                            if isinstance(item, dict):
                                mid = item.get("id") or item.get("name")
                                if mid:
                                    if str(mid).startswith("models/"):
                                        mid = str(mid)[7:]
                                    models.append(str(mid))
                            elif isinstance(item, str):
                                models.append(item)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "id" in item:
                            models.append(str(item["id"]))
                        elif isinstance(item, str):
                            models.append(item)

                models = self._sort_and_filter_models(models)
                return {
                    "ok": True,
                    "models": models,
                    "count": len(models),
                    "message": f"成功獲取 {len(models)} 個可用模型",
                }
        except Exception as e:
            return {"ok": False, "error": f"抓取模型清單失敗：{e}", "models": []}

    async def _fetch_gemini_models_dual_channel(self, api_key: str, base_url: str) -> Dict[str, Any]:
        """
        Google Gemini 雙通道模型抓取：
        1. 優先嘗試 OpenAI 相容端點 (/v1beta/openai/models)
        2. 容錯降級嘗試 Google 官方原生端點 (/v1beta/models?key=...)
        3. 自動過濾出具備文字/對話生成能力 (generateContent) 的可用模型
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 通道 1: OpenAI 相容端點
            openai_url = "https://generativelanguage.googleapis.com/v1beta/openai/models"
            try:
                r1 = await client.get(openai_url, headers={"Authorization": f"Bearer {api_key}"})
                if r1.status_code == 200:
                    data = r1.json()
                    models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
                    if models:
                        sorted_models = self._sort_and_filter_models(models)
                        return {"ok": True, "models": sorted_models, "count": len(sorted_models), "source": "gemini_openai"}
            except Exception:
                pass

            # 通道 2: Google 官方原生端點 (支援 query param 或 header)
            native_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            try:
                r2 = await client.get(native_url, headers={"x-goog-api-key": api_key})
                if r2.status_code == 200:
                    data = r2.json()
                    models = []
                    for item in data.get("models", []):
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name", "")
                        if name.startswith("models/"):
                            name = name[7:]
                        methods = item.get("supportedGenerationMethods", [])
                        # 僅保留支援生成對話/文字內容的模型 (排除 embedding/aqa 等)
                        if "generateContent" in methods or not methods:
                            models.append(name)
                    if models:
                        sorted_models = self._sort_and_filter_models(models)
                        return {"ok": True, "models": sorted_models, "count": len(sorted_models), "source": "gemini_native"}
                elif r2.status_code >= 400:
                    return {"ok": False, "error": f"Google 端點回應 HTTP {r2.status_code}: {r2.text[:200]}", "models": []}
            except Exception as e:
                return {"ok": False, "error": f"Google Gemini 端點連線失敗: {e}", "models": []}

        return {"ok": False, "error": "無法從 Google Gemini 端點取得模型清單 (請檢查 API Key 是否正確或網路是否通暢)", "models": []}

    def _sort_and_filter_models(self, models: List[str]) -> List[str]:
        """將抓取到的模型進行去重與智慧排序 (熱門主力模型置頂)"""
        unique = list(dict.fromkeys([m.strip() for m in models if m and m.strip()]))
        
        def priority(name: str) -> int:
            nl = name.lower()
            if "gemini-2.5-pro" in nl or "gemini-2.5-flash" in nl:
                return 1
            if "gemini-2.0-flash" in nl or "gemini-2.0-pro" in nl:
                return 2
            if "gemini-1.5-pro" in nl or "gemini-1.5-flash" in nl:
                return 3
            if "claude-3-7-sonnet" in nl or "claude-3-5-sonnet" in nl:
                return 4
            if "gpt-4o" in nl or "gpt-4.1" in nl or "o3-mini" in nl:
                return 5
            if "deepseek-r1" in nl or "deepseek-chat" in nl:
                return 6
            if "embed" in nl or "embedding" in nl:
                return 99
            return 50

        unique.sort(key=lambda m: (priority(m), m))
        return unique

    async def test_connection_params(
        self,
        api_key: str,
        base_url: str,
        protocol: str = "openai",
        test_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """測試指定的 API Key、Base URL 與模型連線"""
        key = api_key.strip()
        url_base = base_url.strip().rstrip("/")
        proto = protocol.lower()

        if not key and is_local_endpoint(url_base):
            key = LOCAL_PLACEHOLDER_KEY
        if not key:
            return {"ok": False, "error": "尚未填入 API Key！"}
        if not url_base:
            return {"ok": False, "error": "端點 Base URL 不得為空！"}

        model = (test_model or "").strip()
        if not model:
            model = "gpt-4o" if proto == "openai" else "claude-3-5-sonnet-latest"

        try:
            if proto == "anthropic":
                url = f"{url_base}/messages" if not url_base.endswith("/messages") else url_base
                headers = {
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "ping"}],
                }
            else:
                if url_base.endswith("/chat/completions"):
                    url = url_base
                else:
                    url = f"{url_base}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 10,
                }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code < 300:
                    return {"ok": True, "message": f"✅ 連線成功！HTTP {resp.status_code}，模型 [{model}] 回應正常。"}
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except Exception as e:
            return {"ok": False, "error": f"連線例外：{e}"}

    async def test_connection(self, provider_id: str) -> Dict[str, Any]:
        """測試指定 Provider 的 API Key 與端點連線"""
        prov = next((p for p in self.providers if p["id"] == provider_id), None)
        if not prov:
            return {"ok": False, "error": f"找不到 Provider ID: {provider_id}"}

        api_key = prov.get("api_key", "").strip()
        base_url = prov.get("base_url", "").strip().rstrip("/")
        protocol = prov.get("protocol", "openai")
        models = prov.get("models") or ["gemini-2.5-flash"]
        test_model = models[0] if models else None

        return await self.test_connection_params(api_key, base_url, protocol, test_model)
