# -*- coding: utf-8 -*-
"""
MCP（Model Context Protocol）stdio 用戶端

讀 data/mcp_servers.json 裡 enabled 的伺服器，以子行程啟動，用 JSON-RPC 2.0（一行一則訊息）溝通：
initialize → notifications/initialized → tools/list → tools/call。
取得的工具轉成原生 tool calling 規格，名稱為 mcp__<伺服器id>__<工具名>，與內建工具一起交給模型。

設計重點：
- 不擋聊天：agent 啟動時在背景暖機（第一次 npx 可能要下載套件），聊天時只用「已經就緒」的工具。
- 每台伺服器各自的真實狀態（就緒 / 失敗原因 / 工具數）可由 status() 查詢，不再顯示寫死的 READY。
- 工具的 annotations.readOnlyHint 用來判斷能否並行、要不要跳批准視窗。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROTOCOL_VERSION = "2025-06-18"
START_TIMEOUT = 90.0     # 第一次 npx -y 可能要下載套件
CALL_TIMEOUT = 120.0
_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]")


class McpError(Exception):
    pass


class McpServer:
    def __init__(self, cfg: Dict[str, Any], cwd: Path):
        self.id = str(cfg.get("id") or cfg.get("name") or "server")
        self.name = cfg.get("name") or self.id
        self.command = cfg.get("command", "")
        self.args = [str(a) for a in cfg.get("args") or []]
        self.env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
        self.cwd = Path(cfg.get("cwd") or cwd)
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.tools: List[Dict[str, Any]] = []
        self.state = "STOPPED"   # STOPPED / STARTING / READY / FAILED
        self.error = ""
        self._next_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ 生命週期
    async def start(self) -> None:
        self.state, self.error = "STARTING", ""
        from core.npx_resolver import resolve
        cmd, run_args, self.direct_node = resolve(self.command, self.args)  # 已下載過就跳過 npx 外殼
        exe = shutil.which(cmd) or cmd
        if not shutil.which(exe) and not Path(exe).exists():
            self.state, self.error = "FAILED", f"找不到執行檔：{self.command}"
            return
        env = dict(os.environ)
        env.update(self.env)
        try:
            self.proc = await asyncio.create_subprocess_exec(
                exe, *run_args, cwd=str(self.cwd), env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=32 * 1024 * 1024,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.state, self.error = "FAILED", f"無法啟動：{e}"
            return
        self._stderr_tail: List[str] = []
        self._reader = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._drain_stderr())
        try:
            init = await self.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"roots": {"listChanged": False}},
                "clientInfo": {"name": "syntra-agent", "version": "1.0"},
            }, timeout=START_TIMEOUT)
            await self.notify("notifications/initialized")
            self.server_info = init.get("serverInfo", {})
            await self.refresh_tools()
            self.state = "READY"
        except Exception as e:
            tail = " | ".join(self._stderr_tail[-3:])
            self.state, self.error = "FAILED", f"{type(e).__name__}: {e}" + (f"（伺服器訊息：{tail[:300]}）" if tail else "")
            await self.stop()

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                import psutil
                parent = psutil.Process(self.proc.pid)
                for p in parent.children(recursive=True) + [parent]:
                    try:
                        p.kill()
                    except psutil.NoSuchProcess:
                        pass
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except Exception:
                pass
        if self.proc is not None:
            transport = getattr(self.proc, "_transport", None)
            if transport is not None:
                transport.close()  # 關閉管線，避免結束時印出 unclosed transport 警告
        if self._reader:
            self._reader.cancel()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpError("伺服器已停止"))
        self._pending.clear()
        if self.state != "FAILED":
            self.state = "STOPPED"

    # ------------------------------------------------------------------ JSON-RPC
    async def _send(self, msg: Dict[str, Any]) -> None:
        if not self.proc or self.proc.stdin is None or self.proc.returncode is not None:
            raise McpError("伺服器未在執行")
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = CALL_TIMEOUT):
        self._next_id += 1
        rid = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                fut = self._pending.get(msg["id"])
                if fut and not fut.done():
                    if "error" in msg:
                        err = msg["error"] or {}
                        fut.set_exception(McpError(f"{err.get('code')}: {err.get('message')}"))
                    else:
                        fut.set_result(msg.get("result") or {})
            elif "id" in msg and "method" in msg:
                await self._answer_server_request(msg)
            elif msg.get("method") == "notifications/tools/list_changed":
                asyncio.create_task(self.refresh_tools())
        if self.state == "READY":
            self.state, self.error = "FAILED", "伺服器意外結束"
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpError("伺服器意外結束"))

    async def _drain_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            self._stderr_tail.append(line.decode("utf-8", "replace").strip())
            del self._stderr_tail[:-20]

    async def _answer_server_request(self, msg: Dict[str, Any]) -> None:
        method = msg.get("method")
        if method == "ping":
            result: Dict[str, Any] = {}
        elif method == "roots/list":
            result = {"roots": [{"uri": self.cwd.resolve().as_uri(), "name": self.cwd.name}]}
        else:
            await self._send({"jsonrpc": "2.0", "id": msg["id"],
                              "error": {"code": -32601, "message": f"Method not supported: {method}"}})
            return
        await self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    # ------------------------------------------------------------------ 工具
    async def refresh_tools(self) -> None:
        tools, cursor = [], None
        while True:
            res = await self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=START_TIMEOUT)
            tools.extend(res.get("tools") or [])
            cursor = res.get("nextCursor")
            if not cursor:
                break
        self.tools = tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        res = await self.request("tools/call", {"name": name, "arguments": arguments or {}})
        texts, image = [], None
        for block in res.get("content") or []:
            t = block.get("type")
            if t == "text":
                texts.append(block.get("text", ""))
            elif t == "image" and not image:
                image = block.get("data")
                texts.append(f"[圖片 {block.get('mimeType', '')}]")
            elif t == "resource":
                r = block.get("resource") or {}
                texts.append(r.get("text") or f"[資源 {r.get('uri', '')}]")
            elif t == "resource_link":
                texts.append(f"[資源連結 {block.get('uri', '')}]")
        if not texts and res.get("structuredContent") is not None:
            texts.append(json.dumps(res["structuredContent"], ensure_ascii=False))
        out = "\n".join(texts).strip() or "(工具沒有回傳內容)"
        if res.get("isError"):
            out = "❌ 工具回報錯誤：" + out
        return out[:20000], image


class McpManager:
    PREFIX = "mcp__"

    def __init__(self, config_path: Optional[Path] = None, cwd: Optional[Path] = None):
        base = Path(__file__).resolve().parent.parent
        self.config_path = config_path or (base / "data" / "mcp_servers.json")
        self.cwd = cwd or base
        self.servers: Dict[str, McpServer] = {}
        self._tool_map: Dict[str, Tuple[McpServer, Dict[str, Any]]] = {}
        self._warm_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ 設定 / 暖機
    def _load_config(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return [s for s in data if s.get("enabled", True) and s.get("command")]
        except Exception:
            return []

    async def warm_up(self) -> None:
        """啟動所有 enabled 伺服器（並行）。重複呼叫只會跑一次。"""
        if self._warm_task is None:
            self._warm_task = asyncio.ensure_future(self._start_all())
        await asyncio.shield(self._warm_task)

    def ensure_warming(self) -> None:
        if self._warm_task is None:
            try:
                self._warm_task = asyncio.ensure_future(self._start_all())
            except RuntimeError:
                pass

    async def _start_all(self) -> None:
        for cfg in self._load_config():
            sid = _NAME_OK.sub("_", str(cfg.get("id") or cfg.get("name")))
            self.servers[sid] = McpServer(dict(cfg, id=sid), self.cwd)
        await asyncio.gather(*(s.start() for s in self.servers.values()), return_exceptions=True)
        self._rebuild_map()

    def _rebuild_map(self) -> None:
        self._tool_map.clear()
        for s in self.servers.values():
            if s.state != "READY":
                continue
            for t in s.tools:
                name = (self.PREFIX + s.id + "__" + _NAME_OK.sub("_", t.get("name", "")))[:64]
                self._tool_map[name] = (s, t)

    # ------------------------------------------------------------------ 給 agent 用
    def ready_specs(self) -> List[Dict[str, Any]]:
        """目前已就緒的 MCP 工具規格（中性格式）。不會等待、不會啟動伺服器。"""
        self._rebuild_map()
        specs = []
        for name, (s, t) in self._tool_map.items():
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}
            if schema.get("type") != "object":
                schema = {"type": "object", "properties": {}}
            desc = f"[MCP · {s.name}] " + (t.get("description") or t.get("title") or t.get("name", ""))
            specs.append({"name": name, "description": desc[:900], "parameters": schema})
        return specs

    def is_mcp_tool(self, name: str) -> bool:
        return name.startswith(self.PREFIX)

    def is_read_only(self, name: str) -> bool:
        entry = self._tool_map.get(name)
        return bool(entry and (entry[1].get("annotations") or {}).get("readOnlyHint"))

    def is_destructive(self, name: str) -> bool:
        entry = self._tool_map.get(name)
        if not entry:
            return True
        ann = entry[1].get("annotations") or {}
        if ann.get("readOnlyHint"):
            return False
        if "destructiveHint" in ann:
            return bool(ann["destructiveHint"])
        return bool(re.search(r"write|edit|delete|remove|move|rename|create|upload|send|post|update|set|kill|exec|run|commit|push",
                              entry[1].get("name", ""), re.I))

    async def call(self, name: str, args: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        entry = self._tool_map.get(name)
        if not entry:
            return f"❌ 找不到 MCP 工具：{name}（伺服器可能已停止）", None
        server, tool = entry
        if server.state != "READY":
            return f"❌ MCP 伺服器「{server.name}」目前不可用：{server.error}", None
        try:
            return await server.call_tool(tool["name"], args)
        except asyncio.TimeoutError:
            return f"❌ MCP 工具逾時（>{CALL_TIMEOUT:.0f} 秒）：{name}", None
        except McpError as e:
            return f"❌ MCP 工具錯誤：{e}", None

    def status(self) -> List[Dict[str, Any]]:
        return [{"id": s.id, "name": s.name, "state": s.state, "error": s.error,
                 "tools": [t.get("name") for t in s.tools] if s.state == "READY" else []}
                for s in self.servers.values()]

    async def shutdown(self) -> None:
        await asyncio.gather(*(s.stop() for s in self.servers.values()), return_exceptions=True)


# 全域單例
mcp_manager = McpManager()
