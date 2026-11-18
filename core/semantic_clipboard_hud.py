"""
core/semantic_clipboard_hud.py
==============================
語意剪貼簿監聽與智慧助理管道 (Semantic Clipboard HUD)
利用 Windows 原生 AddClipboardFormatListener 事件通知。
每當用戶複製內容時，在背景以毫秒級正則與語意規則進行快篩：
- Python / JS / Go / Rust 錯誤堆疊 (Traceback)
- JSON / 結構化資料
- SQL 查詢語法
- cURL / API 端點請求
- Git Diff / 補丁
在用戶複製時即刻預判需求，提供一鍵解析、自動修復或格式化支援。
"""

import time
import re
import json
import threading
import win32gui
import win32con
import win32clipboard
from typing import Callable, Optional, Dict, Any, List

class SemanticClipboardClassifier:
    """語意分類器：純本機內存毫秒級判斷"""

    @staticmethod
    def classify(text: str) -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {"type": "empty"}

        # 1. 偵測錯誤堆疊 (Traceback / Exceptions)
        if (
            "Traceback (most recent call last):" in text or
            re.search(r'(?:Exception|Error|panic:|fatal error):', text) or
            "npm ERR!" in text or
            "Stack trace:" in text
        ):
            # 提取最後一行的具體錯誤描述
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            error_headline = lines[-1] if lines else "Unknown Error"
            return {
                "type": "error_traceback",
                "headline": error_headline,
                "lines_count": len(lines),
                "suggestion": "是否需要助手自動分析錯誤成因並直接提供修正代碼？"
            }

        # 2. 偵測 JSON 資料
        if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
            try:
                parsed = json.loads(text)
                return {
                    "type": "json_data",
                    "keys_count": len(parsed) if isinstance(parsed, (dict, list)) else 0,
                    "suggestion": "已偵測到合法 JSON，可一鍵轉為 TypeScript / Pydantic 模型。"
                }
            except Exception:
                pass

        # 3. 偵測 SQL 語句
        if re.match(r'^(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH)\s+', text, re.IGNORECASE):
            return {
                "type": "sql_query",
                "preview": text[:80] + ("..." if len(text) > 80 else ""),
                "suggestion": "已偵測到 SQL 語句，可一鍵最佳化索引或轉為 ORM 查詢。"
            }

        # 4. 偵測 cURL / 網路指令
        if text.startswith("curl ") or text.startswith("http://") or text.startswith("https://"):
            return {
                "type": "http_request",
                "url_preview": text.split()[1] if text.startswith("curl") else text,
                "suggestion": "已偵測到網路端點，可一鍵轉換為 Python requests 代碼。"
            }

        # 5. 偵測 Git Diff
        if text.startswith("diff --git") or "--- a/" in text:
            return {
                "type": "git_diff",
                "suggestion": "已偵測到 Git Diff，可自動生成 Conventional Commit 訊息。"
            }

        return {"type": "general_text", "length": len(text)}


class SemanticClipboardListener:
    """Windows 原生訊息視窗，監聽 WM_CLIPBOARDUPDATE"""

    def __init__(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.callback = callback
        self.hwnd = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.latest_insight: Dict[str, Any] = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._msg_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

    def _msg_loop(self):
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "SyntraClipboardListenerClass"
        wc.hInstance = win32gui.GetModuleHandle(None)

        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception:
            class_atom = win32gui.GetModuleHandle(None)

        self.hwnd = win32gui.CreateWindow(
            class_atom,
            "SyntraClipboardListenerWindow",
            0, 0, 0, 0, 0,
            0, 0, wc.hInstance, None
        )

        # 註冊原生剪貼簿更新監聽（win32gui 未封裝此 API，改用 user32）
        import ctypes
        ctypes.windll.user32.AddClipboardFormatListener(int(self.hwnd))

        # 進入 Windows 訊息循環
        win32gui.PumpMessages()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == 0x031D:  # WM_CLIPBOARDUPDATE
            self._handle_clipboard_change()
            return 0
        elif msg == win32con.WM_DESTROY:
            import ctypes
            ctypes.windll.user32.RemoveClipboardFormatListener(int(hwnd))
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _handle_clipboard_change(self):
        text = self._get_clipboard_text()
        if not text:
            return

        insight = SemanticClipboardClassifier.classify(text)
        insight["raw_length"] = len(text)
        self.latest_insight = insight

        # 若是高價值型別（錯誤日誌、結構化資料），觸發回呼
        if insight.get("type") in ["error_traceback", "json_data", "sql_query", "http_request", "git_diff"]:
            if self.callback:
                try:
                    self.callback(insight)
                except Exception:
                    pass

    def _get_clipboard_text(self) -> Optional[str]:
        for _ in range(3):
            try:
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    return data
                win32clipboard.CloseClipboard()
                return None
            except Exception:
                time.sleep(0.02)
        return None


# 全域單例
clipboard_listener = SemanticClipboardListener()
