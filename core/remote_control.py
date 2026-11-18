# -*- coding: utf-8 -*-
"""
core/remote_control.py
======================
讓終端機 CLI（cli/syntra-windows.py、cli/syntra-linux）遙控 Syntra 桌面版的代理。

安全設計：
- 預設只聽 127.0.0.1（本機）；要讓其他電腦連線，需自己把 data/remote/config.json 的 host 改成 0.0.0.0。
- 每個請求都要帶 Authorization: Bearer <token>，token 存在 data/remote/token.txt（首次啟動自動產生）。
- 帶有 Origin 標頭的請求（瀏覽器網頁發出的）一律拒絕，防止惡意網頁偷打本機服務。
- 只提供代理管理與「交代任務」；不提供直接執行指令的 API。代理要執行的指令仍走原本的風險審核。

API（JSON）：
    GET    /v1/agents                         列出代理
    POST   /v1/agents            {"name"}     新增代理
    DELETE /v1/agents/<no>                    關閉代理
    POST   /v1/agents/<no>/ask   {"text"}     交代任務
    POST   /v1/agents/<no>/stop               停止這一輪
    GET    /v1/agents/<no>/messages?after=N   讀取第 N 則之後的訊息
    GET    /v1/approvals                      等待批准的操作（無介面模式）
    POST   /v1/approvals/<id> {"approved", "pin"}  批准或拒絕
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

DEFAULT_PORT = 8765
MAX_BODY = 256 * 1024


class DirectInvoker:
    """無介面模式：直接在請求的執行緒呼叫（api 自己負責執行緒安全）"""

    def __init__(self):
        self._lock = threading.Lock()

    def invoke(self, fn: Callable[[], Any], timeout: float = 15.0) -> Any:
        with self._lock:
            return fn()


def _make_qt_invoker():
    """桌面版：把函式丟到 Qt 主執行緒執行並等待結果（延後 import，無介面模式不需要 PyQt5）"""
    from PyQt5.QtCore import QObject, pyqtSignal

    class MainThreadInvoker(QObject):
        _call = pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self._call.connect(self._run)

        def _run(self, job):
            fn, box, ev = job
            try:
                box["result"] = fn()
            except Exception as e:  # noqa: BLE001
                box["error"] = e
            finally:
                ev.set()

        def invoke(self, fn: Callable[[], Any], timeout: float = 15.0) -> Any:
            box: Dict[str, Any] = {}
            ev = threading.Event()
            self._call.emit((fn, box, ev))
            if not ev.wait(timeout):
                raise TimeoutError("桌面程式忙碌中，請稍後再試")
            if "error" in box:
                raise box["error"]
            return box.get("result")

    return MainThreadInvoker()


def load_config(data_dir: Path) -> Dict[str, Any]:
    d = data_dir / "remote"
    d.mkdir(parents=True, exist_ok=True)
    cfg_path = d / "config.json"
    cfg = {"enabled": True, "host": "127.0.0.1", "port": DEFAULT_PORT}
    if cfg_path.exists():
        try:
            cfg.update(json.loads(cfg_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    else:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    token_path = d / "token.txt"
    if not token_path.exists() or not token_path.read_text(encoding="utf-8").strip():
        token_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    cfg["token"] = token_path.read_text(encoding="utf-8").strip()
    cfg["token_path"] = str(token_path)
    cfg["config_path"] = str(cfg_path)
    return cfg


class RemoteControlServer:
    """api 物件需提供：list_agents / new_agent / kill_agent / ask_agent / stop_agent / agent_messages
    （都會在 Qt 主執行緒中被呼叫）"""

    def __init__(self, api: Any, data_dir: Path, invoker: Any = None, host: Optional[str] = None,
                 port: Optional[int] = None):
        self.api = api
        self.cfg = load_config(data_dir)
        if host:
            self.cfg["host"] = host
        if port:
            self.cfg["port"] = int(port)
        self.invoker = invoker or _make_qt_invoker()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self.error: Optional[str] = None
        self.warning: Optional[str] = None
        self._rate_lock = threading.Lock()
        self._fail_timestamps: Dict[str, list] = {}  # client_ip -> [monotonic timestamps]

    def _is_rate_limited(self, client_ip: str) -> bool:
        now = time.monotonic()
        with self._rate_lock:
            stamps = [t for t in self._fail_timestamps.get(client_ip, []) if now - t < 60.0]
            self._fail_timestamps[client_ip] = stamps
            return len(stamps) >= 10

    def _record_failure(self, client_ip: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            stamps = [t for t in self._fail_timestamps.get(client_ip, []) if now - t < 60.0]
            stamps.append(now)
            self._fail_timestamps[client_ip] = stamps

    @property
    def address(self) -> str:
        return f"http://{self.cfg['host']}:{self.cfg['port']}"

    def start(self) -> bool:
        if not self.cfg.get("enabled", True):
            self.error = "已停用（data/remote/config.json 的 enabled 為 false）"
            return False
        host_str = str(self.cfg.get("host") or "127.0.0.1").strip()
        if host_str not in ("127.0.0.1", "localhost", "::1"):
            self.warning = f"⚠️ RemoteControlServer 綁定非本機位址 ({host_str})：HTTP 傳輸未加密，建議僅透過 SSH 通道或 TLS 反向代理存取。"
            logging.warning(self.warning)
        handler = self._make_handler()
        try:
            self._httpd = ThreadingHTTPServer((self.cfg["host"], int(self.cfg["port"])), handler)
        except OSError as e:
            self.error = f"無法啟動（{e}）"
            return False
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="SyntraRemote", daemon=True).start()
        return True

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None

    # ------------------------------------------------------------------
    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # 不要印到主控台
                pass

            def _send(self, code: int, payload: Dict[str, Any]):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                client_ip = self.client_address[0] if self.client_address else "unknown"
                if server._is_rate_limited(client_ip):
                    self._send(429, {"ok": False, "error": "嘗試次數過多，請稍後再試"})
                    return False
                if self.headers.get("Origin"):
                    self._send(403, {"ok": False, "error": "拒絕瀏覽器跨來源請求"})
                    return False
                auth = self.headers.get("Authorization", "")
                token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                if not token or not hmac.compare_digest(token, server.cfg["token"]):
                    server._record_failure(client_ip)
                    self._send(401, {"ok": False, "error": "token 錯誤或未提供"})
                    return False
                return True

            def _body(self) -> Dict[str, Any]:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0:
                    return {}
                if n > MAX_BODY:
                    raise ValueError("請求內容太大")
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                return data if isinstance(data, dict) else {}

            def _route(self, method: str):
                if not self._authorized():
                    return
                url = urlparse(self.path)
                parts = [p for p in url.path.split("/") if p]
                q = parse_qs(url.query)
                api = server.api
                try:
                    if parts[:2] == ["v1", "approvals"]:
                        if not hasattr(api, "list_approvals"):
                            return self._send(501, {"ok": False, "error": "桌面版請直接在視窗中批准"})
                        if method == "GET" and len(parts) == 2:
                            return self._send(200, {"ok": True, "approvals": server.invoker.invoke(api.list_approvals)})
                        if method == "POST" and len(parts) == 3:
                            body = self._body()
                            tid, ok_, pin = parts[2], bool(body.get("approved")), body.get("pin")
                            res = server.invoker.invoke(lambda: api.resolve_approval(tid, ok_, pin))
                            if isinstance(res, dict) and not res.get("ok") and "pin" in str(res.get("error", "")).lower():
                                client_ip = self.client_address[0] if self.client_address else "unknown"
                                server._record_failure(client_ip)
                            return self._send(200, res)
                        return self._send(404, {"ok": False, "error": "找不到這個 API"})
                    if parts[:2] != ["v1", "agents"]:
                        return self._send(404, {"ok": False, "error": "找不到這個 API"})
                    rest = parts[2:]
                    body = self._body() if method in ("POST",) else {}
                    call = server.invoker.invoke
                    if not rest:
                        if method == "GET":
                            return self._send(200, {"ok": True, "agents": call(api.list_agents)})
                        if method == "POST":
                            name = str(body.get("name") or "").strip()[:40] or None
                            return self._send(200, call(lambda: api.new_agent(name)))
                    elif rest[0].isdigit():
                        no = int(rest[0])
                        action = rest[1] if len(rest) > 1 else ""
                        if method == "DELETE" and not action:
                            return self._send(200, call(lambda: api.kill_agent(no)))
                        if method == "POST" and action == "ask":
                            text = str(body.get("text") or "").strip()
                            if not text:
                                return self._send(400, {"ok": False, "error": "text 不能是空的"})
                            return self._send(200, call(lambda: api.ask_agent(no, text[:20000])))
                        if method == "POST" and action == "stop":
                            return self._send(200, call(lambda: api.stop_agent(no)))
                        if method == "GET" and action == "messages":
                            after = int((q.get("after") or ["-1"])[0])
                            return self._send(200, call(lambda: api.agent_messages(no, after)))
                    return self._send(404, {"ok": False, "error": "找不到這個 API"})
                except (ValueError, json.JSONDecodeError) as e:
                    return self._send(400, {"ok": False, "error": str(e)})
                except TimeoutError as e:
                    return self._send(503, {"ok": False, "error": str(e)})
                except Exception as e:  # noqa: BLE001
                    return self._send(500, {"ok": False, "error": f"內部錯誤：{e}"})

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_DELETE(self):
                self._route("DELETE")

        return Handler
