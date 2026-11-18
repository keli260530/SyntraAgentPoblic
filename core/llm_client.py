# -*- coding: utf-8 -*-
"""
共用 LLM 連線層（P0：串流 + 原生 tool calling + 連線重用）

- 全程共用一個 httpx.AsyncClient（keep-alive），不再每次請求重新做 TLS 握手。
- 一律用串流（SSE）呼叫：OpenAI 相容 /chat/completions 與 Anthropic /v1/messages。
  文字每到一段就呼叫 on_text(delta)，UI 可以逐字顯示。
- 原生 tool calling：傳入 tools（中性格式 {name, description, parameters}），
  回傳 tool_calls = [{"id", "name", "args"}]，一次可回傳多個（可並行執行）。
- 某個模型 / 端點不支援 tools（回 400 / 422）時自動退回「不帶 tools」重送，
  並記住該模型，回傳 native_tools=False，讓上層改用舊的文字協議（```tool_call 區塊）。
- 對話歷史統一用 OpenAI 格式保存（含 assistant.tool_calls 與 role=tool 訊息），
  送往 Anthropic 時在這裡轉換；送往不支援 tools 的模型時攤平成純文字。
- Anthropic：system 與 tools 加上 prompt caching（cache_control: ephemeral），max_tokens 提高到 8192。
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Union

import httpx

TextCallback = Optional[Callable[[str], Union[None, Awaitable[None]]]]

ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 8192


class LLMClient:
    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop = None
        self.no_native_tools: Set[str] = set()  # 已知不支援原生 tools 的 full_id
        self.no_stream_usage: Set[str] = set()  # 已知不接受 stream_options 的端點

    # ------------------------------------------------------------------ 連線
    def _http(self) -> httpx.AsyncClient:
        import asyncio
        loop = asyncio.get_running_loop()
        # AsyncClient 綁定建立時的 event loop；換 loop（例如測試或 Discord 另開 loop）就重建
        if self._client is None or self._client.is_closed or self._client_loop is not loop:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
                limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=120.0),
            )
            self._client_loop = loop
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------ 入口
    async def chat(
        self,
        protocol: str,
        base_url: str,
        api_key: str,
        model_id: str,
        messages: List[Dict[str, Any]],
        full_id: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        on_text: TextCallback = None,
        fallback_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        fallback_messages：退回文字協議時改用的訊息（例如 system prompt 換回 ```tool_call 版本）；未給則沿用 messages。
        回傳 {"ok", "content", "tool_calls", "native_tools", "stop_reason", "streamed", "error", "model_used"}
        streamed=True 代表已經有文字透過 on_text 送出（上層此時不應再換模型重試，避免畫面重複）。
        """
        full_id = full_id or model_id
        use_tools = bool(tools) and full_id not in self.no_native_tools
        protocol = (protocol or "openai").lower()
        call = self._anthropic if protocol == "anthropic" else self._openai

        res = await call(base_url, api_key, model_id,
                         messages if use_tools else flatten_tool_messages(messages),
                         tools if use_tools else None, temperature, on_text)
        if use_tools and not res["ok"] and not res.get("streamed") and _looks_like_tools_unsupported(res):
            self.no_native_tools.add(full_id)
            use_tools = False
            res = await call(base_url, api_key, model_id, flatten_tool_messages(fallback_messages or messages),
                             None, temperature, on_text)
        res["native_tools"] = use_tools
        res["model_used"] = full_id
        return res

    # ------------------------------------------------------------------ OpenAI 相容
    async def _openai(self, base_url, api_key, model_id, messages, tools, temperature, on_text):
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if url not in self.no_stream_usage:
            payload["stream_options"] = {"include_usage": True}  # 串流最後一包附上 token 用量
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                   "Accept": "text/event-stream"}

        out = _new_result()
        reasoning: List[str] = []
        calls: Dict[int, Dict[str, Any]] = {}
        cur_slot: Dict[int, int] = {}  # 串流 index → calls 的格子編號
        try:
            async with self._http().stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    if resp.status_code == 400 and "stream_options" in payload and "stream_options" in body:
                        self.no_stream_usage.add(url)
                        return await self._openai(base_url, api_key, model_id, messages, tools, temperature, on_text)
                    return _error(out, f"HTTP {resp.status_code}: {body[:500]}", resp.status_code)
                ctype = resp.headers.get("content-type", "")
                if "text/event-stream" not in ctype:
                    # 少數端點忽略 stream=true，直接回整包 JSON
                    data = json.loads((await resp.aread()).decode("utf-8", "replace"))
                    return await _openai_full_json(out, data, on_text)
                async for data in _sse_json(resp):
                    if data.get("usage"):
                        out["usage"] = _openai_usage(data["usage"])
                    choice = (data.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        out["content"] += text
                        out["streamed"] = True
                        await _emit(on_text, text)
                    if delta.get("reasoning") or delta.get("reasoning_content"):
                        reasoning.append(delta.get("reasoning") or delta.get("reasoning_content"))
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index") or 0)
                        slot_no = cur_slot.get(idx)
                        slot = calls.get(slot_no) if slot_no is not None else None
                        fn = tc.get("function") or {}
                        # 有些端點（例如 Gemini 的 OpenAI 相容層）多個工具呼叫都用同一個 index，
                        # 只靠新的 id / 新的函式名稱區分 → 遇到就另開一格，避免名稱與參數黏在一起
                        starts_new = slot is None or (
                            slot["name"] and (
                                (tc.get("id") and slot["id"] and tc["id"] != slot["id"])
                                or (fn.get("name") and not tc.get("id") and slot["arguments"])
                            )
                        )
                        if starts_new:
                            slot_no = len(calls)
                            slot = calls[slot_no] = {"id": "", "name": "", "arguments": ""}
                            cur_slot[idx] = slot_no
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        out["stop_reason"] = choice["finish_reason"]
        except httpx.HTTPError as e:
            return _error(out, f"連線錯誤：{type(e).__name__}: {e}")

        # 模型只有「思考」沒有正式回覆（常見於上下文或輸出被截斷）：思考過程不當成回覆顯示，
        # 交給 agent 迴圈要求它補上正式答案
        out["reasoning"] = "".join(reasoning)
        out["tool_calls"] = [_finish_call(c, i) for i, c in sorted(calls.items()) if c["name"]]
        out["ok"] = True
        return out

    # ------------------------------------------------------------------ Anthropic
    async def _anthropic(self, base_url, api_key, model_id, messages, tools, temperature, on_text):
        url = base_url.rstrip("/")
        if not url.endswith("/messages"):
            url += "/messages"
        system_text, anth_msgs = to_anthropic_messages(messages)
        payload: Dict[str, Any] = {
            "model": model_id,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "temperature": temperature,
            "messages": anth_msgs,
            "stream": True,
        }
        if system_text:
            # system prompt 很長且每回合不變 → prompt caching
            payload["system"] = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
        if tools:
            anth_tools = [{"name": t["name"], "description": t.get("description", ""),
                           "input_schema": t.get("parameters") or {"type": "object", "properties": {}}}
                          for t in tools]
            anth_tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = anth_tools
        headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION,
                   "content-type": "application/json", "accept": "text/event-stream"}

        out = _new_result()
        blocks: Dict[int, Dict[str, Any]] = {}
        try:
            async with self._http().stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    return _error(out, f"Anthropic HTTP {resp.status_code}: {body[:500]}", resp.status_code)
                async for ev in _sse_json(resp):
                    et = ev.get("type")
                    if et == "content_block_start":
                        cb = ev.get("content_block") or {}
                        if cb.get("type") == "tool_use":
                            blocks[ev.get("index", 0)] = {"id": cb.get("id", ""), "name": cb.get("name", ""),
                                                         "arguments": ""}
                    elif et == "content_block_delta":
                        d = ev.get("delta") or {}
                        if d.get("type") == "text_delta" and d.get("text"):
                            out["content"] += d["text"]
                            out["streamed"] = True
                            await _emit(on_text, d["text"])
                        elif d.get("type") == "input_json_delta":
                            blk = blocks.get(ev.get("index", 0))
                            if blk is not None:
                                blk["arguments"] += d.get("partial_json", "")
                    elif et == "message_delta":
                        out["stop_reason"] = (ev.get("delta") or {}).get("stop_reason") or out["stop_reason"]
                        if ev.get("usage"):
                            out.setdefault("usage", {"prompt": 0, "completion": 0})
                            out["usage"]["completion"] = int(ev["usage"].get("output_tokens") or 0)
                    elif et == "message_start":
                        u = (ev.get("message") or {}).get("usage") or {}
                        prompt = sum(int(u.get(k) or 0) for k in
                                     ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                        out["usage"] = {"prompt": prompt, "completion": int(u.get("output_tokens") or 0)}
                    elif et == "error":
                        err = ev.get("error") or {}
                        return _error(out, f"Anthropic 串流錯誤：{err.get('type')}: {err.get('message')}")
        except httpx.HTTPError as e:
            return _error(out, f"連線錯誤：{type(e).__name__}: {e}")

        out["tool_calls"] = [_finish_call(c, i) for i, c in sorted(blocks.items()) if c["name"]]
        out["ok"] = True
        return out


# ====================================================================== 訊息格式轉換
def to_anthropic_messages(messages: List[Dict[str, Any]]):
    """OpenAI 格式 → (system 文字, Anthropic messages)；連續的 tool 結果合併成同一則 user 訊息。"""
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []

    def push(role: str, blocks: List[Dict[str, Any]]):
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            system_parts.append(content if isinstance(content, str) else _text_of(content))
        elif role == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                           "content": content if isinstance(content, str) else _text_of(content)}])
        elif role == "assistant":
            blocks: List[Dict[str, Any]] = []
            if content:
                blocks.extend(_as_blocks(content))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})
            if blocks:
                push("assistant", blocks)
        else:
            push("user", _as_blocks(content))
    return "\n".join(p for p in system_parts if p).strip(), out


def flatten_tool_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """給不支援原生 tools 的模型：把 tool_calls / role=tool 攤平成一般文字訊息。"""
    flat: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            flat.append({"role": "user", "content": f"[工具 `{m.get('name', '')}` 執行結果]:\n{_text_of(m.get('content'))}"})
        elif role == "assistant" and m.get("tool_calls"):
            parts = [_text_of(m.get("content"))] if m.get("content") else []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                parts.append("```tool_call\n" + json.dumps(
                    {"tool": fn.get("name", ""), "args": json.loads(fn.get("arguments") or "{}")},
                    ensure_ascii=False) + "\n```")
            flat.append({"role": "assistant", "content": "\n".join(parts)})
        else:
            flat.append({k: v for k, v in m.items() if k in ("role", "content")})
    return flat


def _as_blocks(content) -> List[Dict[str, Any]]:
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return [{"type": "text", "text": content or ""}]


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content or "")


# ====================================================================== 小工具
def _new_result() -> Dict[str, Any]:
    return {"ok": False, "content": "", "tool_calls": [], "stop_reason": "", "streamed": False, "error": "",
            "status_code": 0}


def _error(out: Dict[str, Any], msg: str, status: int = 0) -> Dict[str, Any]:
    out["ok"] = False
    out["error"] = msg
    out["status_code"] = status
    return out


def _looks_like_tools_unsupported(res: Dict[str, Any]) -> bool:
    if res.get("status_code") not in (400, 404, 422, 501):
        return False
    err = (res.get("error") or "").lower()
    return any(k in err for k in ("tool", "function", "unsupported", "not support", "unrecognized", "extra_forbidden"))


def _finish_call(c: Dict[str, Any], idx: int) -> Dict[str, Any]:
    raw = c.get("arguments") or "{}"
    try:
        args = json.loads(raw)
        if not isinstance(args, dict):
            args = {"value": args}
    except json.JSONDecodeError:
        args = {"__raw_arguments__": raw}
    return {"id": c.get("id") or f"call_{idx}", "name": c["name"], "args": args}


async def _emit(cb: TextCallback, text: str):
    if not cb or not text:
        return
    try:
        r = cb(text)
        if hasattr(r, "__await__"):
            await r
    except Exception:
        pass


async def _sse_json(resp: httpx.Response):
    """逐行解析 SSE，產出每個 data: 的 JSON 物件。"""
    async for line in resp.aiter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            continue


async def _openai_full_json(out: Dict[str, Any], data: Dict[str, Any], on_text: TextCallback) -> Dict[str, Any]:
    msg = ((data.get("choices") or [{}])[0]).get("message") or {}
    content = msg.get("content") or ""
    out["reasoning"] = msg.get("reasoning") or msg.get("reasoning_content") or ""
    out["content"] = content
    if content:
        out["streamed"] = True
        await _emit(on_text, content)
    out["tool_calls"] = [
        _finish_call({"id": tc.get("id"), "name": (tc.get("function") or {}).get("name", ""),
                      "arguments": (tc.get("function") or {}).get("arguments", "")}, i)
        for i, tc in enumerate(msg.get("tool_calls") or [])
    ]
    out["tool_calls"] = [c for c in out["tool_calls"] if c["name"]]
    if data.get("usage"):
        out["usage"] = _openai_usage(data["usage"])
    out["ok"] = True
    return out


def _openai_usage(u: Dict[str, Any]) -> Dict[str, int]:
    return {"prompt": int(u.get("prompt_tokens") or 0), "completion": int(u.get("completion_tokens") or 0)}


# 全域單例
llm_client = LLMClient()
