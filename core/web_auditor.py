import asyncio
import datetime
import urllib.parse
from typing import Any, Callable, Dict, List, Optional
import httpx


class WebAuditor:
    """
    透明上網研究與即時通報模組：
    1. 每次連網查詢或造訪網頁，自動記錄「🌐 網址 + 搜尋目的 + 內容重點摘要」，並即時推播至 Gemini 介面與 Discord。
    2. 若涉及需登入網站、金流結帳頁面或未知風險操作，先交由 SecurityGuard 攔截並詢問使用者是否批准。
    3. 擷取回來的外部網頁內容一律經過 Prompt Injection 沙箱清洗。
    """

    def __init__(self, settings_manager, security_guard):
        self.settings_manager = settings_manager
        self.security_guard = security_guard
        self.history: List[Dict[str, Any]] = []
        self._callbacks: List[Callable] = []

    def register_callback(self, cb: Callable):
        self._callbacks.append(cb)

    def _notify(self, record: Dict[str, Any]):
        self.history.insert(0, record)
        if len(self.history) > 100:
            self.history = self.history[:100]
        self.settings_manager.append_audit_log("WEB_ACTIVITY", record)
        for cb in self._callbacks:
            try:
                res = cb(record)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

    def _is_domain_trusted_or_normal(self, url: str) -> tuple[bool, str]:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        path_lower = (parsed.path or "").lower()

        # 1. 主動網路白名單與惡意連線防禦比對
        if hasattr(self.security_guard, "network_guard"):
            net_eval = self.security_guard.network_guard.evaluate_outbound_connection(url, process_name="WebAuditor")
            if not net_eval.get("allowed"):
                return False, net_eval.get("reason", "目標網域未在信任白名單中！")

        # 2. 檢查是否為高風險登入/結帳/錢包路徑
        risk, reason = self.security_guard.classify_action("web_visit", url, {"url": url})
        if risk != "SAFE":
            return False, reason

        # 3. 檢查是否有敏感關鍵字
        suspicious_keywords = ("login", "signin", "oauth", "checkout", "payment", "upload", "admin")
        if any(k in path_lower or k in host for k in suspicious_keywords):
            return False, f"網址包含登入、付款或管理介面路徑 (`{url}`)，需先經你批准才可造訪。"

        return True, "OK"

    async def fetch_url(self, url: str, purpose: str = "查詢技術資料或網頁內容") -> Dict[str, Any]:
        """造訪指定網址，自動檢查安全性並即時回報網址與內容摘要給使用者"""
        is_safe, safety_reason = self._is_domain_trusted_or_normal(url)
        if not is_safe:
            risk, _ = self.security_guard.classify_action("web_visit", url, {"url": url})
            if risk == "SAFE":
                risk = "HIGH_RISK"
            approved, msg = await self.security_guard.request_user_approval(
                risk_level=risk,
                title=f"請求造訪外部網站：{url[:65]}",
                reason=f"目的：{purpose}\n攔截原因：{safety_reason}",
                action_payload={"action": "fetch_url", "url": url, "purpose": purpose},
            )
            if not approved:
                blocked_record = {
                    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                    "action": "BLOCKED_VISIT",
                    "url": url,
                    "purpose": purpose,
                    "title": "🛑 已攔截上網請求",
                    "summary": msg,
                }
                self._notify(blocked_record)
                return {"ok": False, "url": url, "error": msg}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
        }
        try:
            async with httpx.AsyncClient(timeout=18.0, follow_redirects=True, headers=headers) as client:
                resp = await client.get(url)
                html = resp.text

            from bs4 import BeautifulSoup  # 延遲載入

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "footer", "nav"]):
                tag.decompose()

            title = (soup.title.string.strip() if soup.title and soup.title.string else url)
            text_blocks = [p.get_text(" ", strip=True) for p in soup.find_all(["h1", "h2", "h3", "p", "li", "pre", "code"])]
            clean_text = "\n".join([b for b in text_blocks if len(b) > 15])
            if not clean_text:
                clean_text = soup.get_text(" ", strip=True)

            summary_preview = clean_text[:360].replace("\n", " ") + ("..." if len(clean_text) > 360 else "")
            sanitized_full = self.security_guard.sanitize_untrusted_content(clean_text[:6000], source_label=url)

            record = {
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "action": "WEB_VISIT",
                "url": str(resp.url),
                "purpose": purpose,
                "title": title[:120],
                "summary": summary_preview or "（網頁無純文字摘要）",
                "status_code": resp.status_code,
            }
            self._notify(record)

            return {
                "ok": True,
                "url": str(resp.url),
                "title": title,
                "summary": summary_preview,
                "content": sanitized_full,
            }
        except Exception as e:
            err_record = {
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "action": "WEB_ERROR",
                "url": url,
                "purpose": purpose,
                "title": "連線失敗",
                "summary": str(e),
            }
            self._notify(err_record)
            return {"ok": False, "url": url, "error": str(e)}

    async def search_web(self, query: str, purpose: str = "搜尋問題解答與參考資訊") -> Dict[str, Any]:
        """透過 DuckDuckGo HTML 搜尋引擎查詢資料，並立即向 Gemini 介面與 Discord 通報搜尋詞與結果摘要"""
        encoded_q = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
        }
        try:
            async with httpx.AsyncClient(timeout=18.0, follow_redirects=True, headers=headers) as client:
                resp = await client.get(search_url)

            from bs4 import BeautifulSoup  # 延遲載入

            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for item in soup.select(".result")[:6]:
                a_tag = item.select_one(".result__a")
                snip_tag = item.select_one(".result__snippet")
                if not a_tag:
                    continue
                r_title = a_tag.get_text(" ", strip=True)
                r_href = a_tag.get("href", "")
                if r_href.startswith("//"):
                    r_href = "https:" + r_href
                elif r_href.startswith("/"):
                    r_href = "https://html.duckduckgo.com" + r_href
                if "uddg=" in r_href:
                    try:
                        parsed_u = urllib.parse.urlparse(r_href)
                        qs = urllib.parse.parse_qs(parsed_u.query)
                        if "uddg" in qs and qs["uddg"]:
                            r_href = qs["uddg"][0]
                    except Exception:
                        pass

                r_snip = snip_tag.get_text(" ", strip=True) if snip_tag else ""
                results.append({"title": r_title, "url": r_href, "snippet": r_snip})

            summary_lines = [f"• {r['title']}: {r['snippet'][:90]}" for r in results[:4]]
            summary_text = "\n".join(summary_lines) if summary_lines else "未找到直接匹配的搜尋結果摘要。"

            record = {
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "action": "WEB_SEARCH",
                "url": f"https://duckduckgo.com/?q={encoded_q}",
                "query": query,
                "purpose": purpose,
                "title": f"🔍 搜尋：{query}",
                "summary": summary_text,
                "results_count": len(results),
            }
            self._notify(record)

            formatted = "\n\n".join(
                [f"[{i+1}] {r['title']}\nURL: {r['url']}\n摘要: {r['snippet']}" for i, r in enumerate(results)]
            )
            sanitized = self.security_guard.sanitize_untrusted_content(
                formatted or "無搜尋結果", source_label=f"WebSearch:{query}"
            )
            return {
                "ok": True,
                "query": query,
                "purpose": purpose,
                "results": results,
                "summary": summary_text,
                "content": sanitized,
            }
        except Exception as e:
            return {"ok": False, "query": query, "error": str(e)}
