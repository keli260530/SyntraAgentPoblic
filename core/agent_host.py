# -*- coding: utf-8 -*-
"""
core/agent_host.py
==================
不依賴任何介面（Qt）的多代理管理器，給無介面／伺服器模式（syntra_headless.py）使用。
提供和桌面版遙控 API 相同的方法：list_agents / new_agent / kill_agent / ask_agent /
stop_agent / agent_messages，另外加上 list_approvals / resolve_approval。

所有方法都可以從任何執行緒呼叫；代理的每一輪都丟到背景 asyncio 迴圈執行。
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from typing import Any, Callable, Dict, List, Optional

from core.tool_labels import describe_tool_call


class HeadlessAgent:
    def __init__(self, agent_id: str, name: str, session_id: str):
        self.agent_id = agent_id
        self.name = name
        self.session_id = session_id
        self.status = "IDLE"  # IDLE | RUNNING | DONE | ERROR
        self.messages: List[Dict[str, Any]] = []
        self.future: Optional[Future] = None

    @property
    def running(self) -> bool:
        return self.future is not None and not self.future.done()


class AgentHost:
    def __init__(
        self,
        agent_brain: Any,
        loop: asyncio.AbstractEventLoop,
        security_guard: Any = None,
        desktop_controller: Any = None,
        model_id: Optional[str] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ):
        self.brain = agent_brain
        self.loop = loop
        self.security_guard = security_guard
        self.desktop_controller = desktop_controller
        self.model_id = model_id
        self.on_event = on_event or (lambda kind, data: None)
        self.agents: "OrderedDict[str, HeadlessAgent]" = OrderedDict()
        self._lock = threading.RLock()
        self._counter = 0
        self.main_id: Optional[str] = None
        self.new_agent("代理 #1 (主控)")

    # ---------------- 內部工具 ----------------
    def _by_no(self, no: int) -> Optional[HeadlessAgent]:
        ids = list(self.agents.keys())
        return self.agents[ids[no - 1]] if 1 <= no <= len(ids) else None

    def _no(self, agent_id: str) -> int:
        ids = list(self.agents.keys())
        return ids.index(agent_id) + 1 if agent_id in ids else 0

    def _emit(self, kind: str, **data):
        try:
            self.on_event(kind, data)
        except Exception:
            pass

    # ---------------- 遙控 API ----------------
    def list_agents(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"no": i, "id": a.agent_id, "name": a.name, "status": a.status,
                 "main": a.agent_id == self.main_id, "active": a.agent_id == self.main_id,
                 "messages": len(a.messages)}
                for i, a in enumerate(self.agents.values(), 1)
            ]

    def new_agent(self, name: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            self._counter += 1
            idx = self._counter
            aid = f"agent_{int(time.time())}_{idx}"
            agent = HeadlessAgent(aid, name or f"代理 #{idx}", f"headless_{int(time.time())}_{idx}")
            self.agents[aid] = agent
            if self.main_id is None:
                self.main_id = aid
            return {"ok": True, "no": self._no(aid), "name": agent.name}

    def kill_agent(self, no: int) -> Dict[str, Any]:
        with self._lock:
            agent = self._by_no(no)
            if agent is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            if agent.agent_id == self.main_id:
                return {"ok": False, "error": "主控代理不能關閉"}
            if agent.future is not None:
                agent.future.cancel()
            self.agents.pop(agent.agent_id, None)
            return {"ok": True, "closed": agent.name}

    def rename_agent(self, no: int, name: str) -> Dict[str, Any]:
        with self._lock:
            agent = self._by_no(no)
            if agent is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            agent.name = name
            return {"ok": True, "name": name}

    def ask_agent(self, no: int, text: str) -> Dict[str, Any]:
        with self._lock:
            agent = self._by_no(no)
            if agent is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            if agent.running:
                return {"ok": False, "error": f"{agent.name} 還在執行上一輪，請稍後或先 stop"}
            agent.messages.append({"role": "user", "text": text, "t": time.time()})
            after = len(agent.messages) - 1
            agent.status = "RUNNING"
            agent.future = asyncio.run_coroutine_threadsafe(self._turn(agent, text), self.loop)
            return {"ok": True, "no": no, "after": after}

    async def _turn(self, agent: HeadlessAgent, text: str):
        no = self._no(agent.agent_id)

        async def _step_cb(step: Dict[str, Any]):
            # 同一步驟會先送「執行中」再送結果，只顯示一次
            if step.get("tool") and step.get("status") in ("RUNNING", "ECC_WARN"):
                label = describe_tool_call(step.get("tool", ""), step.get("args") or {})
                self._emit("step", no=no, name=agent.name, text=f"{label['action']}{label['detail']}")

        t0 = time.time()
        try:
            res = await self.brain.run_chat_turn(
                session_id=agent.session_id,
                user_message=text,
                model_full_id=self.model_id,
                step_callback=_step_cb,
            )
            reply = str(res.get("reply") or res.get("content") or "")
            agent.status = "DONE" if res.get("ok", True) else "ERROR"
        except asyncio.CancelledError:
            reply, agent.status = "⏹ 已停止這一輪。", "IDLE"
        except Exception as e:  # noqa: BLE001
            reply, agent.status = f"❌ 執行失敗：{e}", "ERROR"
        with self._lock:
            agent.messages.append({"role": "agent", "text": reply, "t": time.time(),
                                   "seconds": round(time.time() - t0, 1)})
        self._emit("reply", no=no, name=agent.name, text=reply)

    def stop_agent(self, no: int) -> Dict[str, Any]:
        with self._lock:
            agent = self._by_no(no)
            if agent is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            stopped = agent.running
            if stopped:
                agent.future.cancel()
                try:
                    if self.desktop_controller is not None:
                        self.desktop_controller.kill_running_commands()
                except Exception:
                    pass
            return {"ok": True, "stopped": stopped}

    def agent_messages(self, no: int, after: int = -1) -> Dict[str, Any]:
        with self._lock:
            agent = self._by_no(no)
            if agent is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            msgs = [{"i": i, "role": m["role"], "text": str(m.get("text") or "")[:20000]}
                    for i, m in enumerate(agent.messages) if i > after]
            return {"ok": True, "no": no, "name": agent.name, "running": agent.running,
                    "status": agent.status, "messages": msgs}

    def wait(self, no: int, timeout: Optional[float] = None) -> bool:
        """等代理這一輪結束（給命令列模式用）"""
        agent = self._by_no(no)
        if agent is None or agent.future is None:
            return True
        try:
            agent.future.result(timeout=timeout)
        except Exception:
            pass
        return agent.future.done()

    # ---------------- 批准 ----------------
    def list_approvals(self) -> List[Dict[str, Any]]:
        if self.security_guard is None:
            return []
        return [
            {"id": t.get("id"), "risk_level": t.get("risk_level"), "requires_pin": bool(t.get("requires_pin")),
             "title": t.get("title"), "reason": t.get("reason"), "created_at": t.get("created_at")}
            for t in self.security_guard.get_pending_list()
        ]

    def resolve_approval(self, ticket_id: str, approved: bool, pin: Optional[str] = None) -> Dict[str, Any]:
        if self.security_guard is None:
            return {"ok": False, "error": "沒有安全模組"}
        ok, msg = self.security_guard.resolve_approval(
            ticket_id=ticket_id, approved=approved, pin_code=pin, source="Headless CLI")
        return {"ok": ok, "message": msg, "error": None if ok else msg}
