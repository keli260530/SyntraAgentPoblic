# -*- coding: utf-8 -*-
"""
core/tool_discovery_agent.py
============================
Syntra 專精工具調用與定期聯網檢索新工具的代理模組：
1. 與主模型（gpt-oss:20b）及視覺模型（gemma3:12b）協作，由 3B 專精小模型負責快速工具選擇與 JSON 拆解。
2. 定期透過網路檢索最新開源工具、MCP Server 與 CLI 能力，並快取至 data/tool_discovery_cache.json。
3. 內建抗干擾與防注入過濾：僅採信受信任技術來源網域，並對所有外部摘要執行 Prompt Injection 清洗，嚴禁自動安裝或執行未授權程式碼。
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

TRUSTED_TOOL_DOMAINS = (
    "github.com",
    "modelcontextprotocol.io",
    "pypi.org",
    "docs.python.org",
    "ollama.com",
    "huggingface.co",
    "learn.microsoft.com",
)

_SPAM_KEYWORDS = (
    "casino", "betting", "airdrop", "free crypto", "crack", "keygen",
    "sponsored", "buy now", "優惠", "博弈", "破解版",
)


class ToolDiscoveryAgent:
    """專責定期聯網檢索新工具並過濾雜訊與提示詞注入的輔助代理。"""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        security_guard: Any = None,
        interval_hours: int = 24,
    ):
        base_dir = Path(__file__).resolve().parent.parent
        self.data_dir = Path(data_dir) if data_dir else (base_dir / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.data_dir / "tool_discovery_cache.json"
        self.security_guard = security_guard
        self.interval_hours = max(1, int(interval_hours))

    def load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {"last_checked": "", "tools": []}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("tools"), list):
                return data
        except Exception:
            pass
        return {"last_checked": "", "tools": []}

    def _save_cache(self, payload: Dict[str, Any]) -> None:
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.cache_path)

    def is_due(self, now: Optional[datetime.datetime] = None) -> bool:
        """檢查是否已達定期檢索週期。"""
        cache = self.load_cache()
        last = cache.get("last_checked") or ""
        if not last:
            return True
        try:
            last_dt = datetime.datetime.fromisoformat(last)
            cur = now or datetime.datetime.now()
            return (cur - last_dt).total_seconds() >= self.interval_hours * 3600
        except Exception:
            return True

    @staticmethod
    def is_trusted_source(url: str) -> bool:
        """僅允許受信任技術網域，排除廣告與不可信來源干擾。"""
        if not url:
            return False
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            return False
        return any(host == d or host.endswith("." + d) for d in TRUSTED_TOOL_DOMAINS)

    def filter_candidates(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """過濾廣告雜訊、不可信網域與疑似 Prompt Injection 的結果。"""
        clean: List[Dict[str, Any]] = []
        seen_urls = set()
        for item in raw_items or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or item.get("description") or "").strip()
            if not url or url in seen_urls or not self.is_trusted_source(url):
                continue

            combined = f"{title} {snippet}".lower()
            if any(spam in combined for spam in _SPAM_KEYWORDS):
                continue

            # 若有安全守衛，先檢查並過濾任何疑似提示詞注入的外部結果
            if self.security_guard is not None:
                if hasattr(self.security_guard, "inspect_user_prompt"):
                    chk = self.security_guard.inspect_user_prompt(f"{title}\n{snippet}")
                    if chk.get("blocked") or chk.get("injection_detected"):
                        continue
                    snippet = chk.get("sanitized_text") or snippet
                if hasattr(self.security_guard, "sanitize_untrusted_content"):
                    snippet = self.security_guard.sanitize_untrusted_content(snippet, source_label=url)
            else:
                snippet = re.sub(r"ignore\s+previous\s+instructions", "[REDACTED]", snippet, flags=re.IGNORECASE)

            seen_urls.add(url)
            clean.append({
                "title": title[:120],
                "url": url,
                "summary": snippet[:500],
                "discovered_at": datetime.datetime.now().isoformat(timespec="seconds"),
            })
        return clean

    async def refresh_if_due(
        self,
        search_fn: Callable[[str], Awaitable[List[Dict[str, Any]]]],
        queries: Optional[List[str]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """若到期（或 force=True），執行聯網檢索並更新乾淨的工具候選快取。"""
        if not force and not self.is_due():
            cache = self.load_cache()
            return {"ok": True, "refreshed": False, "tools": cache.get("tools", [])}

        search_queries = queries or [
            "site:github.com modelcontextprotocol mcp server new tools",
            "site:pypi.org mcp tool agent automation",
        ]
        collected: List[Dict[str, Any]] = []
        for q in search_queries:
            try:
                res = await search_fn(q)
                if isinstance(res, list):
                    collected.extend(res)
            except Exception:
                continue

        vetted = self.filter_candidates(collected)
        payload = {
            "last_checked": datetime.datetime.now().isoformat(timespec="seconds"),
            "tools": vetted[:30],
        }
        self._save_cache(payload)
        return {"ok": True, "refreshed": True, "tools": payload["tools"]}
