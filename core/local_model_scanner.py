"""
本地模型自動偵測器 (Local Model Scanner)

啟動時在背景探測本機常見的 LLM 服務（Ollama / LM Studio / llama.cpp 等 OpenAI 相容端點），
找出「尚未接入 Agent」的模型，交給 UI 詢問使用者是否加入。

資安原則：
- 只探測固定的 localhost 端點清單（不掃區網、不接受任意 URL）。
- 本模組只負責「偵測」與「在使用者同意後寫入」；寫入一律以使用者身分 (非 Agent) 呼叫
  ApiManager.upsert_provider()，因此照常經過 security_guard 驗證並觸發 API 異動安全通知。
"""

import asyncio
import json
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# 固定探測清單：port 必須與 security_guard.validate_api_provider 放行的本地 port (11434 / 1234 / 8080) 一致
LOCAL_ENDPOINTS: List[Dict[str, str]] = [
    {
        "provider_id": "local_ollama",
        "name": "Ollama 本地模型",
        "base_url": "http://127.0.0.1:11434/v1",
        "probe_url": "http://127.0.0.1:11434/api/tags",
        "kind": "ollama",
    },
    {
        "provider_id": "local_lmstudio",
        "name": "LM Studio 本地模型",
        "base_url": "http://127.0.0.1:1234/v1",
        "probe_url": "http://127.0.0.1:1234/v1/models",
        "kind": "openai",
    },
    {
        "provider_id": "local_llamacpp",
        "name": "llama.cpp / 本地 OpenAI 相容服務",
        "base_url": "http://127.0.0.1:8080/v1",
        "probe_url": "http://127.0.0.1:8080/v1/models",
        "kind": "openai",
    },
]

# 非對話用途的模型（嵌入、重排序）不適合當 Agent 大腦，略過
_NON_CHAT_KEYWORDS = ("embed", "embedding", "rerank", "bge-", "e5-")

USER_CONSENT_SOURCE = "本地模型自動偵測（使用者同意）"


def _is_chat_model(name: str) -> bool:
    low = name.lower()
    return not any(k in low for k in _NON_CHAT_KEYWORDS)


def endpoint_key(base_url: str) -> str:
    """把 base_url 正規化成 'host:port' 比對鍵（localhost / 127.0.0.1 / ::1 視為同一台）"""
    try:
        parsed = urllib.parse.urlparse(base_url.strip())
    except Exception:
        return base_url.strip().lower()
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "::1", "0.0.0.0"):
        host = "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{host}:{port}"


def _parse_models(kind: str, data: Any) -> List[str]:
    models: List[str] = []
    if kind == "ollama":
        for item in (data or {}).get("models", []) if isinstance(data, dict) else []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if name:
                    models.append(str(name))
    else:
        items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                models.append(str(item["id"]))
            elif isinstance(item, str):
                models.append(item)
    # 去重並保持順序
    seen = set()
    result = []
    for m in models:
        if m not in seen and _is_chat_model(m):
            seen.add(m)
            result.append(m)
    return result


class LocalModelScanner:
    def __init__(self, data_dir: Optional[Path] = None, timeout: float = 1.5):
        base_dir = Path(__file__).resolve().parent.parent
        self.data_dir = data_dir or (base_dir / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.dismissed_path = self.data_dir / "local_models_dismissed.json"
        self.timeout = timeout

    # ── 偵測 ────────────────────────────────────────────────
    async def _probe(self, client: httpx.AsyncClient, ep: Dict[str, str]) -> Optional[Dict[str, Any]]:
        try:
            resp = await client.get(ep["probe_url"])
            if resp.status_code >= 300:
                return None
            models = _parse_models(ep["kind"], resp.json())
        except Exception:
            return None
        if not models:
            return None
        return {**ep, "models": models}

    async def scan(self) -> List[Dict[str, Any]]:
        """探測所有本地端點，回傳有在運作且有模型的服務清單"""
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            results = await asyncio.gather(*(self._probe(client, ep) for ep in LOCAL_ENDPOINTS))
        return [r for r in results if r]

    # ── 比對：找出尚未接入、也沒被使用者拒絕過的模型 ─────────────────
    def find_new_models(self, api_manager: Any, scanned: List[Dict[str, Any]], include_dismissed: bool = False) -> List[Dict[str, Any]]:
        dismissed = set() if include_dismissed else self._load_dismissed()
        new_items: List[Dict[str, Any]] = []
        for svc in scanned:
            ek = endpoint_key(svc["base_url"])
            existing_models = set()
            existing_id = None
            for p in api_manager.providers:
                if endpoint_key(p.get("base_url", "")) == ek:
                    existing_models.update(p.get("models") or [])
                    existing_id = existing_id or p["id"]
            fresh = [
                m for m in svc["models"]
                if m not in existing_models and f"{ek}|{m}" not in dismissed
            ]
            if fresh:
                new_items.append({**svc, "models": fresh, "existing_provider_id": existing_id})
        return new_items

    # ── 使用者同意後寫入 ──────────────────────────────────────
    def apply(self, api_manager: Any, service: Dict[str, Any], selected_models: List[str]) -> Dict[str, Any]:
        """把使用者勾選的模型接入 Agent（既有同端點 Provider 則合併模型清單）"""
        if not selected_models:
            return {}
        pid = service.get("existing_provider_id")
        prov = next((p for p in api_manager.providers if p["id"] == pid), None) if pid else None
        if prov:
            merged = list(prov.get("models") or [])
            if merged == ["default-model"]:
                merged = []
            merged += [m for m in selected_models if m not in merged]
            payload = {
                "id": prov["id"],
                "name": prov.get("name", service["name"]),
                "protocol": prov.get("protocol", "openai"),
                "base_url": prov.get("base_url", service["base_url"]),
                "api_key": "",  # 空字串＝保留原本的 Key
                "models": merged,
                "enabled": True,
            }
        else:
            payload = {
                "id": service["provider_id"],
                "name": service["name"],
                "protocol": "openai",
                "base_url": service["base_url"],
                "api_key": "",
                "models": list(selected_models),
                "enabled": True,
            }
        return api_manager.upsert_provider(payload, source=USER_CONSENT_SOURCE)

    # ── 「不再詢問」清單 ─────────────────────────────────────
    def _load_dismissed(self) -> set:
        try:
            data = json.loads(self.dismissed_path.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
        except Exception:
            return set()

    def dismiss(self, service: Dict[str, Any], models: List[str]):
        dismissed = self._load_dismissed()
        ek = endpoint_key(service["base_url"])
        dismissed.update(f"{ek}|{m}" for m in models)
        self.dismissed_path.write_text(
            json.dumps(sorted(dismissed), ensure_ascii=False, indent=2), encoding="utf-8"
        )
