import asyncio
import base64
import json
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional
import httpx
import websockets

logger = logging.getLogger("BrowserController")


class BrowserController:
    """
    原生全功能無頭 / 擬人瀏覽器控制器（對標 Antigravity /browser）：
    1. 優先使用本機現有 Microsoft Edge 或 Google Chrome 透過 Chrome DevTools Protocol (CDP) 進行精確控制。
    2. 支援網頁即時導航、DOM 文字與結構提取、元素模擬點擊、文字填寫、全頁截圖 (供 VLM 分析)。
    3. 獨立沙箱 User-Data-Dir，絕不污染使用者平常用於日常工作或登入的瀏覽器 Profiles。
    """

    CHROME_EDGE_PATHS = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]

    def __init__(self, port: int = 9222, headless: bool = True):
        self.port = port
        self.headless = headless
        self.browser_proc: Optional[subprocess.Popen] = None
        self.ws_url: Optional[str] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.req_id: int = 0
        self.base_data_dir = Path(__file__).resolve().parent.parent / "data" / "browser_profile"
        self.base_data_dir.mkdir(parents=True, exist_ok=True)
        self.current_url: str = "about:blank"

    def _find_browser_binary(self) -> Optional[str]:
        for p in self.CHROME_EDGE_PATHS:
            if p.exists() and p.is_file():
                return str(p)
        return None

    async def start(self) -> bool:
        """啟動瀏覽器並連接 CDP 介面"""
        if self.ws and not self.ws.closed:
            return True

        binary = self._find_browser_binary()
        if not binary:
            logger.error("找不到本機 Microsoft Edge 或 Google Chrome 執行檔")
            return False

        args = [
            binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.base_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-default-apps",
            "--hide-scrollbars",
            "--window-size=1280,800",
        ]
        if self.headless:
            args.extend(["--headless=new", "--disable-gpu"])

        try:
            self.browser_proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as e:
            logger.error(f"啟動瀏覽器失敗: {e}")
            return False

        # 等待 CDP 端點就緒
        endpoint = f"http://127.0.0.1:{self.port}/json/version"
        retries = 20
        async with httpx.AsyncClient() as client:
            for _ in range(retries):
                await asyncio.sleep(0.3)
                try:
                    res = await client.get(endpoint, timeout=1.0)
                    if res.status_code == 200:
                        data = res.json()
                        self.ws_url = data.get("webSocketDebuggerUrl")
                        break
                except Exception:
                    continue

        if not self.ws_url:
            logger.error("無法取得 CDP WebSocket Debugger URL")
            self.close()
            return False

        try:
            self.ws = await websockets.connect(self.ws_url, max_size=20 * 1024 * 1024)
            # 啟用必要 Domains
            await self._send_cdp("Page.enable")
            await self._send_cdp("DOM.enable")
            await self._send_cdp("Runtime.enable")
            return True
        except Exception as e:
            logger.error(f"CDP WebSocket 連接失敗: {e}")
            self.close()
            return False

    async def _send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.ws or self.ws.closed:
            ok = await self.start()
            if not ok or not self.ws:
                return {"error": "Browser not connected"}

        self.req_id += 1
        payload = {"id": self.req_id, "method": method, "params": params or {}}
        try:
            await self.ws.send(json.dumps(payload))
            while True:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=15.0)
                data = json.loads(msg)
                if data.get("id") == payload["id"]:
                    return data
        except Exception as e:
            return {"error": str(e)}

    async def navigate(self, url: str) -> Dict[str, Any]:
        """導航至指定網址"""
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file://"):
            url = f"https://{url}"

        await self.start()
        res = await self._send_cdp("Page.navigate", {"url": url})
        self.current_url = url
        # 等待頁面載入緩衝
        await asyncio.sleep(2.0)
        title_res = await self.evaluate_js("document.title")
        title = title_res.get("result", {}).get("value", "Untitled")
        return {"ok": "error" not in res, "url": url, "title": title}

    async def capture_screenshot(self, full_page: bool = False) -> Dict[str, Any]:
        """擷取當前頁面截圖 (回傳 Base64 與尺寸)"""
        await self.start()
        params = {"format": "png", "quality": 90}
        if full_page:
            params["captureBeyondViewport"] = True
        res = await self._send_cdp("Page.captureScreenshot", params)
        if "result" in res and "data" in res["result"]:
            b64_data = res["result"]["data"]
            return {"ok": True, "image_b64": b64_data, "url": self.current_url}
        return {"ok": False, "error": res.get("error", "擷取截圖失敗")}

    async def evaluate_js(self, expression: str) -> Dict[str, Any]:
        """在頁面執行 JavaScript"""
        await self.start()
        res = await self._send_cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return res.get("result", {})

    async def extract_readable_page(self) -> Dict[str, Any]:
        """智慧提取頁面結構：文字主體、標題層級、表單輸入框與可互動按鈕"""
        js_extractor = """
        (() => {
            const title = document.title;
            const url = window.location.href;
            
            // 提取主要文字
            const clone = document.body.cloneNode(true);
            const badTags = clone.querySelectorAll('script, style, noscript, svg, iframe');
            badTags.forEach(el => el.remove());
            const textContent = clone.innerText.replace(/\\n{3,}/g, '\\n\\n').trim().slice(0, 5000);
            
            // 提取互動元件
            const interactables = [];
            document.querySelectorAll('a, button, input, textarea, select, [role="button"]').forEach((el, idx) => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.top <= window.innerHeight) {
                    const tag = el.tagName.toLowerCase();
                    const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim();
                    const href = el.getAttribute('href') || '';
                    if (text || href) {
                        interactables.push({
                            index: idx,
                            tag: tag,
                            text: text.slice(0, 50),
                            href: href,
                            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}
                        });
                    }
                }
            });
            
            return {
                title: title,
                url: url,
                text_preview: textContent,
                interactive_elements: interactables.slice(0, 30)
            };
        })()
        """
        res = await self.evaluate_js(js_extractor)
        val = res.get("value")
        if val:
            return {"ok": True, **val}
        return {"ok": False, "error": "無法提取頁面內容"}

    async def click_element(self, selector_or_text: str) -> Dict[str, Any]:
        """模擬點擊元素 (支援 CSS 選擇器或文字比對)"""
        js_click = f"""
        (() => {{
            const sel = {json.dumps(selector_or_text)};
            let el = document.querySelector(sel);
            if (!el) {{
                const all = Array.from(document.querySelectorAll('button, a, input[type="submit"], [role="button"], span, div'));
                el = all.find(e => (e.innerText || '').trim() === sel || (e.innerText || '').includes(sel));
            }}
            if (el) {{
                el.scrollIntoView({{behavior: 'instant', block: 'center'}});
                el.click();
                return {{ok: true, tag: el.tagName, text: el.innerText}};
            }}
            return {{ok: false, error: '找不到可點擊的元素: ' + sel}};
        }})()
        """
        res = await self.evaluate_js(js_click)
        val = res.get("value", {})
        await asyncio.sleep(1.0)
        return val

    async def type_into_element(self, selector: str, text: str) -> Dict[str, Any]:
        """在指定元素填寫文字"""
        js_type = f"""
        (() => {{
            const sel = {json.dumps(selector)};
            const val = {json.dumps(text)};
            let el = document.querySelector(sel);
            if (!el) {{
                const inputs = Array.from(document.querySelectorAll('input, textarea'));
                el = inputs.find(e => (e.placeholder || '').includes(sel) || (e.name || '').includes(sel));
            }}
            if (el) {{
                el.focus();
                el.value = val;
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                return {{ok: true, selector: sel, value: val}};
            }}
            return {{ok: false, error: '找不到輸入框: ' + sel}};
        }})()
        """
        res = await self.evaluate_js(js_type)
        return res.get("value", {})

    def close(self):
        """關閉連線與瀏覽器子行程"""
        if self.ws and not self.ws.closed:
            try:
                asyncio.create_task(self.ws.close())
            except Exception:
                pass
        self.ws = None

        if self.browser_proc:
            try:
                self.browser_proc.terminate()
                self.browser_proc.wait(timeout=2)
            except Exception:
                try:
                    self.browser_proc.kill()
                except Exception:
                    pass
            self.browser_proc = None
