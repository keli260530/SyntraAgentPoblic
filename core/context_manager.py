# -*- coding: utf-8 -*-
"""
長對話管理：避免對話越聊越長，最後超出模型上限、又慢又貴。

每回合開始前呼叫 compact_history()：
1. 舊的工具輸出（最近幾則以外）截斷成頭尾各一段，保留重點、丟掉大量中間內容。
2. 若總長度仍超過上限，把「最舊的那一段對話」交給模型摘要成一則訊息，只保留最近的對話原文。
   切點一定落在「使用者開新一輪」的位置，不會把 tool_calls 與對應的 tool 結果拆開。
3. 摘要失敗（例如模型不可用）就直接丟掉最舊的幾輪，並留下一行說明。
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional

MAX_CHARS = 60_000          # 約 15k～30k tokens（中英混合），留空間給工具定義與回覆
KEEP_RECENT_CHARS = 24_000  # 摘要後保留原文的最近對話長度
OLD_TOOL_OUTPUT_CHARS = 1_500
KEEP_RECENT_MSGS = 6        # 最近幾則訊息的工具輸出不截斷

SUMMARY_TAG = "[先前對話摘要]"
SummarizeFn = Callable[[str], Awaitable[str]]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return "" if content is None else str(content)


def msg_chars(m: Dict[str, Any]) -> int:
    n = len(_text_of(m.get("content")))
    for tc in m.get("tool_calls") or []:
        n += len((tc.get("function") or {}).get("arguments", "")) + 30
    return n


def total_chars(history: List[Dict[str, Any]]) -> int:
    return sum(msg_chars(m) for m in history)


def _is_tool_output(m: Dict[str, Any]) -> bool:
    if m.get("role") == "tool":
        return True
    c = m.get("content")
    return m.get("role") == "user" and isinstance(c, str) and c.startswith("[工具 `")


def _is_turn_start(m: Dict[str, Any]) -> bool:
    """使用者開新一輪的訊息（不是工具結果、不是摘要）。"""
    c = m.get("content")
    return (m.get("role") == "user" and not _is_tool_output(m)
            and not (isinstance(c, str) and c.startswith(SUMMARY_TAG)))


def truncate_old_tool_outputs(history: List[Dict[str, Any]], keep_recent: int = KEEP_RECENT_MSGS,
                              limit: int = OLD_TOOL_OUTPUT_CHARS) -> int:
    cut = 0
    for m in history[:max(0, len(history) - keep_recent)]:
        if _is_tool_output(m) and isinstance(m.get("content"), str) and len(m["content"]) > limit:
            c = m["content"]
            head, tail = c[: limit * 2 // 3], c[-limit // 3:]
            m["content"] = f"{head}\n…（較舊的工具輸出已截斷，原長 {len(c)} 字）…\n{tail}"
            cut += 1
    return cut


def _find_cut(history: List[Dict[str, Any]], keep_recent_chars: int) -> int:
    """回傳切點 i：history[1:i] 拿去摘要，history[i:] 保留原文。i 必定是某一輪的開頭。"""
    acc = 0
    best = 0
    for i in range(len(history) - 1, 0, -1):
        acc += msg_chars(history[i])
        if _is_turn_start(history[i]):
            best = i
            if acc >= keep_recent_chars:
                break
    return best


def _render_for_summary(msgs: List[Dict[str, Any]]) -> str:
    lines = []
    for m in msgs:
        role = {"user": "使用者", "assistant": "助手", "tool": "工具結果"}.get(m.get("role"), m.get("role"))
        txt = _text_of(m.get("content"))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            txt += f"\n（呼叫工具 {fn.get('name')} {fn.get('arguments', '')[:200]}）"
        lines.append(f"{role}：{txt[:3000]}")
    return "\n\n".join(lines)


async def compact_history(history: List[Dict[str, Any]], summarize: Optional[SummarizeFn] = None,
                          max_chars: int = MAX_CHARS, keep_recent_chars: int = KEEP_RECENT_CHARS) -> Dict[str, Any]:
    """就地壓縮 history（history[0] 必須是 system）。回傳做了什麼，方便記錄與測試。"""
    report = {"before": total_chars(history), "truncated": 0, "summarized": 0, "dropped": 0}
    if report["before"] <= max_chars:
        report["after"] = report["before"]
        return report
    report["truncated"] = truncate_old_tool_outputs(history)
    if total_chars(history) > max_chars:
        cut = _find_cut(history, keep_recent_chars)
        if cut > 1:
            old = history[1:cut]
            summary = None
            if summarize is not None:
                try:
                    summary = (await summarize(_render_for_summary(old))).strip() or None
                except Exception:
                    summary = None
            if summary:
                history[1:cut] = [{"role": "user", "content": f"{SUMMARY_TAG}\n{summary}"}]
                report["summarized"] = len(old)
            else:
                history[1:cut] = [{"role": "user",
                                   "content": f"{SUMMARY_TAG}\n（較早的 {len(old)} 則訊息因長度限制已移除，無法摘要。）"}]
                report["dropped"] = len(old)
    report["after"] = total_chars(history)
    return report


def make_llm_summarizer(brain, model_full_id: Optional[str] = None) -> SummarizeFn:
    """用 agent 目前的模型做摘要（不帶工具、不串流到畫面）。"""
    async def summarize(text: str) -> str:
        res = await brain.call_llm(
            messages=[
                {"role": "system", "content": "你是對話摘要器。請用繁體中文，把下面的對話整理成重點摘要："
                                              "使用者的目標與偏好、已完成的事、做過的決定、重要的檔案路徑與數字、尚未完成的事。"
                                              "只輸出摘要本身，不超過 800 字。"},
                {"role": "user", "content": text[:40_000]},
            ],
            model_full_id=model_full_id,
        )
        return res.get("content", "") if res.get("ok") else ""
    return summarize
