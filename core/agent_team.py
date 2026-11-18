# -*- coding: utf-8 -*-
"""
代理團隊：多個主代理，每個主代理可以開任意多個子代理；代理之間可以串線協作。

- 結構：主代理（parent=None）→ 子代理（parent=主代理）。
- 串線（TerminalManager 的 link）：共用同一個 PowerShell 終端，而且可以互傳訊息。
  主代理與自己的子代理之間本來就可以互傳訊息；終端則要拖線串起來才共用。
- 用量：每個代理記錄「這一輪送出多少 token（＝上下文占用）」與累計輸入／輸出 token。
- 給模型用的協作工具（TOOL_SPECS / run_tool）：terminal_run、spawn_subagent、wait_subagents、
  send_to_agent、list_team。
- 介面無關：桌面版用 set_host() 提供「建立代理 / 送訊息給代理 / 讀狀態」的實作。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .agent_terminal import TerminalManager, terminal_manager

MAX_SPAWN_PER_TURN = 8       # 單一輪最多開幾個子代理（防止模型失控狂開）
WAIT_LIMIT_SECONDS = 900


# ---------------------------------------------------------------- 上下文長度
_CTX_BY_NAME = [
    ("gemini", 1_048_576), ("claude", 200_000), ("gpt-4.1", 1_000_000), ("gpt-4o", 128_000), ("gpt-5", 400_000),
    ("o3", 200_000), ("o4", 200_000), ("deepseek", 128_000), ("qwen", 32_768), ("llama", 128_000),
    ("mistral", 32_768), ("gemma3", 8_192), ("gpt-oss", 16_384),
]
_ollama_ctx_cache: Dict[str, Tuple[float, int]] = {}


def _ollama_runtime_ctx(model: str) -> Optional[int]:
    hit = _ollama_ctx_cache.get(model)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    try:
        import httpx
        data = httpx.get("http://127.0.0.1:11434/api/ps", timeout=1.5).json()
        for m in data.get("models", []):
            if m.get("name") == model or m.get("model") == model:
                n = int(m.get("context_length") or 0)
                if n:
                    _ollama_ctx_cache[model] = (time.time(), n)
                    return n
    except Exception:
        pass
    return None


def context_limit(model_full_id: str) -> int:
    full = model_full_id or ""
    provider, _, name = full.partition(":")
    if not name:
        provider, name = "", full
    if "ollama" in provider.lower():
        n = _ollama_runtime_ctx(name)
        if n:
            return n
    model = name.lower()  # 只比對模型名稱（「ollama」本身含有 llama，不能拿來比）
    for key, n in _CTX_BY_NAME:
        if key in model:
            return n
    return 32_768


def estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """沒有官方用量時的估算：中文約 1 字 1 token、英數約 4 字 1 token。"""
    total = 0
    for m in messages or []:
        c = m.get("content")
        text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) if c else ""
        if m.get("tool_calls"):
            text += json.dumps(m["tool_calls"], ensure_ascii=False)
        cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
        total += cjk + (len(text) - cjk) // 4 + 4
    return total


# ---------------------------------------------------------------- 資料
@dataclass
class Usage:
    context_tokens: int = 0        # 最近一次呼叫送出的 token（上下文占用）
    context_limit: int = 0
    input_total: int = 0
    output_total: int = 0
    calls: int = 0
    estimated: bool = False
    model: str = ""

    @property
    def ratio(self) -> float:
        return min(1.0, self.context_tokens / self.context_limit) if self.context_limit else 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {"context_tokens": self.context_tokens, "context_limit": self.context_limit, "ratio": self.ratio,
                "input_total": self.input_total, "output_total": self.output_total, "calls": self.calls,
                "estimated": self.estimated, "model": self.model}


@dataclass
class Member:
    agent_id: str
    name: str
    parent_id: Optional[str] = None
    session_id: str = ""
    created: float = field(default_factory=time.time)
    usage: Usage = field(default_factory=Usage)
    inbox: List[Dict[str, Any]] = field(default_factory=list)


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


TOOL_KINDS = {
    "note": ("📝", "便利貼"),
    "image": ("🖼", "圖片"),
    "link": ("🔗", "連結"),
    "computer": ("🖥", "讀取電腦"),
}


@dataclass
class ToolNode:
    """畫布上的工具節點：連到哪些代理，那些代理每一輪都會看到它的內容。"""
    node_id: str
    kind: str                      # note | image | link | computer
    title: str = ""
    content: str = ""              # 便利貼文字 / 連結網址 / 圖片或資料夾路徑
    extracted: str = ""            # 圖片 OCR 出來的文字（背景計算）

    def as_dict(self) -> Dict[str, Any]:
        return {"node_id": self.node_id, "kind": self.kind, "title": self.title, "content": self.content,
                "extracted": self.extracted}

    def context_text(self) -> str:
        icon, label = TOOL_KINDS.get(self.kind, ("•", self.kind))
        title = f"「{self.title}」" if self.title else ""
        if self.kind == "note":
            return f"{icon} 便利貼{title}：\n{self.content[:4000]}"
        if self.kind == "link":
            return f"{icon} 連結{title}：{self.content}（需要內容時用 web_fetch 讀取）"
        if self.kind == "image":
            txt = f"\n圖片中的文字：{self.extracted[:3000]}" if self.extracted else ""
            return f"{icon} 圖片{title}：{self.content}{txt}"
        if self.kind == "computer":
            if self.content:
                return (f"{icon} 讀取電腦{title}：使用者允許你查閱資料夾 {self.content}"
                        f"（用 search_local_files 指定 folder、read_local_file 讀檔）")
            return f"{icon} 讀取電腦{title}：需要知道使用者畫面上有什麼時，可用 ocr_screen 讀取目前螢幕文字"
        return f"{icon} {label}{title}：{self.content}"


class AgentTeam:
    def __init__(self, terminals: TerminalManager = terminal_manager):
        self.terminals = terminals
        self.members: Dict[str, Member] = {}
        self.tools: Dict[str, ToolNode] = {}
        self.tool_links: set = set()   # {(tool_id, agent_id)}
        self._by_session: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []
        self._spawned_in_turn: Dict[str, int] = {}
        # 由介面提供
        self._create: Optional[Callable[[Optional[str], str], Optional[str]]] = None
        self._ask: Optional[Callable[[str, str], bool]] = None
        self._status: Optional[Callable[[str], Tuple[str, str]]] = None
        self._resolver: Optional[Callable[[str], Optional[str]]] = None

    # ------------------------------------------------ 介面掛勾
    def set_host(self, create: Callable[[Optional[str], str], Optional[str]], ask: Callable[[str, str], bool],
                 status: Callable[[str], Tuple[str, str]]):
        """create(parent_id, name) -> agent_id；ask(agent_id, text) -> 有沒有送出；status(agent_id) -> (狀態, 最後回覆)。
        三個都會從背景執行緒呼叫，實作要自己轉回 UI 執行緒。"""
        self._create, self._ask, self._status = create, ask, status

    def on_event(self, fn: Callable[[str, Dict[str, Any]], None]):
        self._listeners.append(fn)

    def _emit(self, kind: str, **data):
        for fn in list(self._listeners):
            try:
                fn(kind, data)
            except Exception:
                pass

    # ------------------------------------------------ 成員
    def add(self, agent_id: str, name: str, session_id: str = "", parent_id: Optional[str] = None) -> Member:
        with self._lock:
            m = self.members.get(agent_id)
            if m is None:
                m = self.members[agent_id] = Member(agent_id, name, parent_id, session_id)
            else:
                m.name, m.parent_id = name, parent_id
                if session_id:
                    m.session_id = session_id
            if m.session_id:
                self._by_session[m.session_id] = agent_id
        self.terminals.register(agent_id)
        self._emit("changed")
        return m

    def set_session(self, agent_id: str, session_id: str):
        with self._lock:
            m = self.members.get(agent_id)
            if m:
                if m.session_id:
                    self._by_session.pop(m.session_id, None)
                m.session_id = session_id
                self._by_session[session_id] = agent_id

    def rename(self, agent_id: str, name: str):
        with self._lock:
            if agent_id in self.members:
                self.members[agent_id].name = name
        self._emit("changed")

    def set_parent(self, agent_id: str, parent_id: Optional[str]) -> bool:
        """把代理掛到某個主代理底下（parent_id=None 代表變回主代理）。只能掛在主代理底下，自己有子代理的不能被掛。"""
        with self._lock:
            m = self.members.get(agent_id)
            if m is None or agent_id == parent_id:
                return False
            if parent_id is not None:
                p = self.members.get(parent_id)
                if p is None or p.parent_id is not None or self.children(agent_id):
                    return False
            m.parent_id = parent_id
        self._emit("changed")
        return True

    def remove(self, agent_id: str) -> List[str]:
        """移除代理；它的子代理改掛到它的上層（主代理被關時子代理升為主代理）。回傳受影響的子代理。"""
        with self._lock:
            self.tool_links = {p for p in self.tool_links if p[1] != agent_id}
            m = self.members.pop(agent_id, None)
            if m is None:
                return []
            self._by_session.pop(m.session_id, None)
            orphans = [c.agent_id for c in self.members.values() if c.parent_id == agent_id]
            for cid in orphans:
                self.members[cid].parent_id = m.parent_id
        self.terminals.remove_agent(agent_id)
        self._emit("changed")
        return orphans

    def set_session_resolver(self, fn: Callable[[str], Optional[str]]):
        """代理換了新對話（session_id 改變）時，用這個找回是哪個代理。"""
        self._resolver = fn

    def agent_for_session(self, session_id: str) -> Optional[str]:
        aid = self._by_session.get(session_id)
        if aid is None and self._resolver is not None and session_id:
            try:
                aid = self._resolver(session_id)
            except Exception:
                aid = None
            if aid in self.members:
                self.set_session(aid, session_id)
            else:
                aid = None
        return aid

    def children(self, agent_id: str) -> List[str]:
        return [m.agent_id for m in self.members.values() if m.parent_id == agent_id]

    def roots(self) -> List[str]:
        return [m.agent_id for m in self.members.values() if m.parent_id is None]

    def is_main(self, agent_id: str) -> bool:
        m = self.members.get(agent_id)
        return bool(m and m.parent_id is None)

    def can_talk(self, a: str, b: str) -> bool:
        ma, mb = self.members.get(a), self.members.get(b)
        if not ma or not mb or a == b:
            return False
        return ma.parent_id == b or mb.parent_id == a or self.terminals.is_linked(a, b)

    def contacts(self, agent_id: str) -> List[str]:
        return [x for x in self.members if self.can_talk(agent_id, x)]

    # ------------------------------------------------ 工具節點
    def add_tool(self, node: ToolNode) -> ToolNode:
        with self._lock:
            self.tools[node.node_id] = node
        self._emit("changed")
        return node

    def remove_tool(self, node_id: str):
        with self._lock:
            self.tools.pop(node_id, None)
            self.tool_links = {p for p in self.tool_links if p[0] != node_id}
        self._emit("changed")

    def link_tool(self, node_id: str, agent_id: str) -> bool:
        with self._lock:
            if node_id not in self.tools or (node_id, agent_id) in self.tool_links:
                return False
            self.tool_links.add((node_id, agent_id))
        self._emit("changed")
        return True

    def unlink_tool(self, node_id: str, agent_id: str):
        with self._lock:
            self.tool_links.discard((node_id, agent_id))
        self._emit("changed")

    def tools_of(self, agent_id: str) -> List[ToolNode]:
        return [self.tools[t] for t, a in sorted(self.tool_links) if a == agent_id and t in self.tools]

    def context_for(self, agent_id: str) -> str:
        """連到這個代理的工具節點內容，加進它每一輪的提示。"""
        items = [t.context_text() for t in self.tools_of(agent_id)]
        if not items:
            return ""
        return "[使用者在畫布上連給你的工具與資料：]\n" + "\n\n".join(items) + "\n"

    # ------------------------------------------------ 用量
    def record_usage(self, session_id: str, usage: Optional[Dict[str, int]], model_full_id: str,
                     sent_messages: Optional[List[Dict[str, Any]]] = None):
        aid = self.agent_for_session(session_id)
        if aid is None:
            return
        with self._lock:
            m = self.members.get(aid)
            if m is None:
                return
            u = m.usage
            prompt = int((usage or {}).get("prompt") or 0)
            completion = int((usage or {}).get("completion") or 0)
            u.estimated = not prompt
            if not prompt:
                prompt = estimate_tokens(sent_messages or [])
            u.context_tokens = prompt
            u.input_total += prompt
            u.output_total += completion
            u.calls += 1
            u.model = model_full_id or u.model
            u.context_limit = context_limit(u.model)
        self._emit("usage", agent_id=aid, usage=m.usage.as_dict())

    def usage_of(self, agent_id: str) -> Optional[Usage]:
        m = self.members.get(agent_id)
        return m.usage if m else None

    # ------------------------------------------------ 協作動作
    def begin_turn(self, agent_id: str):
        self._spawned_in_turn[agent_id] = 0

    def spawn(self, parent_id: str, name: str, task: str) -> Dict[str, Any]:
        if self._create is None or self._ask is None:
            return {"ok": False, "error": "目前環境不支援子代理"}
        if not self.is_main(parent_id):
            return {"ok": False, "error": "只有主代理可以開子代理；請把工作回報給你的主代理"}
        n = self._spawned_in_turn.get(parent_id, 0)
        if n >= MAX_SPAWN_PER_TURN:
            return {"ok": False, "error": f"這一輪已經開了 {n} 個子代理，請先等它們完成"}
        child = self._create(parent_id, name or "子代理")
        if not child:
            return {"ok": False, "error": "建立子代理失敗"}
        self._spawned_in_turn[parent_id] = n + 1
        parent_name = self.members.get(parent_id).name if parent_id in self.members else "主代理"
        prompt = (f"[你是 {parent_name} 開的子代理「{name}」。完成下面的工作後，直接給出精簡、可交付的結果；"
                  f"需要回報進度或提問時可用 send_to_agent 傳給 {parent_name}。]\n\n{task}")
        sent = self._ask(child, prompt)
        self._emit("spawned", parent_id=parent_id, agent_id=child)
        return {"ok": bool(sent), "agent_id": child, "name": name,
                "note": "子代理已在背景開始工作；用 wait_subagents 等結果"}

    async def wait(self, agent_ids: List[str], timeout: float) -> Dict[str, Any]:
        if self._status is None:
            return {"ok": False, "error": "目前環境不支援子代理"}
        deadline = time.time() + max(5.0, min(float(timeout or 300), WAIT_LIMIT_SECONDS))
        await asyncio.sleep(1.0)
        while True:
            states = {aid: self._status(aid) for aid in agent_ids}
            running = [a for a, (st, _) in states.items() if st == "RUNNING"]
            if not running or time.time() >= deadline:
                break
            await asyncio.sleep(1.5)
        results = []
        for aid, (st, last) in states.items():
            name = self.members[aid].name if aid in self.members else aid
            results.append({"agent_id": aid, "name": name, "status": st, "result": (last or "")[:6000]})
        return {"ok": not running, "timed_out": bool(running), "results": results}

    def send(self, from_id: str, to_id: str, text: str) -> Dict[str, Any]:
        if self._ask is None:
            return {"ok": False, "error": "目前環境不支援代理間傳訊"}
        if not self.can_talk(from_id, to_id):
            return {"ok": False, "error": "你們之間沒有串線（主代理與自己的子代理、或被使用者拖線串起來的代理才能互傳）"}
        sender = self.members[from_id].name if from_id in self.members else from_id
        ok = self._ask(to_id, f"[來自 {sender} 的訊息]\n{text}")
        return {"ok": bool(ok), "delivered_to": self.members[to_id].name if to_id in self.members else to_id,
                "note": "已送達；對方若正在忙，會在它這一輪結束後接著處理" if ok else "傳送失敗"}

    def describe(self, agent_id: str) -> Dict[str, Any]:
        def row(aid):
            m = self.members[aid]
            st = self._status(aid)[0] if self._status else ""
            return {"agent_id": aid, "name": m.name, "role": "主代理" if m.parent_id is None else "子代理",
                    "status": st, "can_message": self.can_talk(agent_id, aid),
                    "shares_terminal": aid != agent_id and self.terminals.is_linked(agent_id, aid)}
        me = self.members.get(agent_id)
        return {"me": row(agent_id) if me else None,
                "team": [row(a) for a in self.members if a != agent_id]}

    def resolve(self, ref: str, from_id: str) -> Optional[str]:
        """名稱或 agent_id → agent_id（只在可以聯絡的人裡找名稱）。"""
        ref = (ref or "").strip()
        if ref in self.members:
            return ref
        for aid in self.contacts(from_id) + list(self.members):
            if self.members[aid].name.strip() == ref or ref in self.members[aid].name:
                return aid
        return None


team = AgentTeam()


# ---------------------------------------------------------------- 給模型用的工具
TOOL_SPECS: List[Dict[str, Any]] = [
    {"name": "terminal_run",
     "description": "在你自己的 PowerShell 終端機執行指令。終端會記住目前目錄與變數（cd 之後下一個指令還在那裡）；"
                    "使用者把你和其他代理拖線串起來時，大家共用同一個終端。使用者看得到你在終端打的每一行。",
     "parameters": {"type": "object", "properties": {
         "command": {"type": "string", "description": "PowerShell 指令（可多行）"},
         "timeout": {"type": "integer", "description": "秒數上限，預設 120，最多 900"}},
         "required": ["command"]}},
    {"name": "spawn_subagent",
     "description": "（只有主代理能用）開一個子代理在背景平行處理一件獨立的工作，例如把大任務拆成幾份同時做。"
                    "子代理有自己的對話與終端；開完用 wait_subagents 收結果。",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string", "description": "子代理的名字，例如「測試員」「資料查詢」"},
         "task": {"type": "string", "description": "交給它的完整工作說明（它看不到你的對話，要寫清楚）"}},
         "required": ["name", "task"]}},
    {"name": "wait_subagents",
     "description": "等待子代理完成並取回它們的最終結果。",
     "parameters": {"type": "object", "properties": {
         "agent_ids": {"type": "array", "items": {"type": "string"}, "description": "spawn_subagent 回傳的 agent_id；省略代表全部子代理"},
         "timeout": {"type": "integer", "description": "最多等幾秒，預設 300"}}}},
    {"name": "send_to_agent",
     "description": "傳訊息給另一個代理（自己的主代理／子代理，或被使用者拖線串起來的代理），對方會收到並處理。",
     "parameters": {"type": "object", "properties": {
         "to": {"type": "string", "description": "對方的名字或 agent_id"},
         "message": {"type": "string"}},
         "required": ["to", "message"]}},
    {"name": "list_team",
     "description": "列出所有代理、誰是主代理／子代理、目前狀態，以及你能聯絡誰、和誰共用終端。",
     "parameters": {"type": "object", "properties": {}}},
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}
READ_ONLY = {"list_team"}


async def run_tool(name: str, args: Dict[str, Any], brain, session_id: str) -> Tuple[str, Optional[str]]:
    aid = team.agent_for_session(session_id)

    def out(obj) -> Tuple[str, Optional[str]]:
        return json.dumps(obj, ensure_ascii=False), None

    if aid is None:
        return out({"ok": False, "error": "這個對話不屬於任何代理（例如背景工作），無法使用團隊工具"})
    try:
        if name == "terminal_run":
            cmd = str(args.get("command", ""))
            sec = getattr(brain, "security_guard", None)
            if sec is not None:
                risk, why = sec.classify_action("run_command", cmd, {"command": cmd, "cwd": ""})
                if risk == "CREDENTIAL_THEFT_BLOCKED":
                    return out({"ok": False, "blocked_by_security": True, "output": f"❌ [資安防護] {why}"})
                if risk != "SAFE":
                    approved, msg = await sec.request_user_approval(
                        risk_level=risk, title=f"在終端執行：{cmd[:60]}", reason=why,
                        action_payload={"action": "terminal_run", "command": cmd})
                    if not approved:
                        return out({"ok": False, "blocked_by_security": True, "output": msg})
            timeout = max(5, min(int(args.get("timeout") or 120), 900))
            res = await asyncio.to_thread(team.terminals.run, aid, cmd, aid, timeout)
            if sec is not None:
                res["output"] = sec.sanitize_secrets(str(res.get("output", "")))
            return out(res)
        if name == "spawn_subagent":
            return out(team.spawn(aid, str(args.get("name", "子代理"))[:30], str(args.get("task", ""))))
        if name == "wait_subagents":
            ids = [team.resolve(str(x), aid) or str(x) for x in (args.get("agent_ids") or [])] or team.children(aid)
            if not ids:
                return out({"ok": False, "error": "你目前沒有子代理"})
            return out(await team.wait(ids, float(args.get("timeout") or 300)))
        if name == "send_to_agent":
            to = team.resolve(str(args.get("to", "")), aid)
            if to is None:
                return out({"ok": False, "error": f"找不到代理：{args.get('to')}；先用 list_team 查名字"})
            return out(team.send(aid, to, str(args.get("message", ""))))
        if name == "list_team":
            return out(team.describe(aid))
    except Exception as e:
        return out({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return out({"ok": False, "error": f"未知的團隊工具：{name}"})
