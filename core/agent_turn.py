# -*- coding: utf-8 -*-
"""
新版多步驟 Agent 回合（P0）

與舊版 run_chat_turn 的差別：
1. 串流：模型文字一邊產生一邊透過 token_callback 送出（約每 40ms 合併一次，避免 UI 被洗版）。
2. 原生 tool calling：模型一次可呼叫多個工具；相鄰的「只讀」工具並行執行，其餘依序執行。
   模型 / 端點不支援 tools 時，自動退回舊的 ```tool_call 文字協議（ToolCallECC 解析）。
3. 少一次 LLM 往返：任務拆解改用本機啟發式（不再先花一整輪請模型拆任務），由模型在工具迴圈中自行規劃。
回傳格式與舊版完全相同（ok / reply / tool_steps / model_used / routing_info / screenshot_b64），
所以桌面 UI、Discord、server.py 都不用改。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import time
from typing import Any, Callable, Dict, List, Optional

from . import tool_router
from .tool_ecc import ToolCallECC
from .tool_guard import ToolGuard
from .tool_schemas import READ_ONLY_TOOLS, build_tool_specs

MAX_ROUNDS = 12
TOKEN_FLUSH_SECONDS = 0.04

_TEXT_FORMAT_START = "### 工具呼叫格式："
_TEXT_FORMAT_END = "可用工具清單："
_NATIVE_FORMAT = (
    "### 工具呼叫方式：\n"
    "請直接使用 function calling（原生工具呼叫）執行工具，不要在文字中輸出 ```tool_call 區塊。\n"
    "互不相依的查詢類工具（例如同時搜尋多個關鍵字、同時讀取多個視窗）請在同一回合一次呼叫，系統會並行執行。\n"
    "會操作畫面或改變狀態的工具請一次一個，看到結果再決定下一步。\n"
)

_spec_cache: Dict[int, List[Dict[str, Any]]] = {}


def tool_specs_for(prompt: str) -> List[Dict[str, Any]]:
    key = hash(prompt)
    if key not in _spec_cache:
        _spec_cache[key] = build_tool_specs(prompt)
    return _spec_cache[key]


_TOOL_LIST_END = "若不需要呼叫工具或已完成所有步驟"


def native_system_prompt(text_prompt: str) -> str:
    """把 system prompt 中「請輸出 ```tool_call 區塊」的說明與整份文字版工具清單，換成原生 function calling 說明。
    工具名稱、參數與用途已經透過 tools 欄位提供，再列一次只會白白吃掉約 4K tokens（本機模型上下文很小）。"""
    a = text_prompt.find(_TEXT_FORMAT_START)
    b = text_prompt.find(_TOOL_LIST_END, a)
    if a < 0:
        return text_prompt
    if b < 0:
        b = text_prompt.find(_TEXT_FORMAT_END, a)
        if b < 0:
            return text_prompt
    return (text_prompt[:a] + _NATIVE_FORMAT
            + "（可用工具的名稱、參數與用途都已透過工具定義提供，請直接呼叫。）\n\n" + text_prompt[b:])


def is_local_model(model_full_id: Optional[str]) -> bool:
    """Ollama 等本機模型：上下文通常只有 8K～16K，要更積極地截短與壓縮。"""
    mid = (model_full_id or "").lower()
    return "ollama" in mid or "localhost" in mid or "127.0.0.1" in mid


_AUTO_MODEL_IDS = ("", "auto", "auto_router", "default")


def likely_local_model(brain, model_full_id: Optional[str], difficulty: str) -> bool:
    """這一輪大概會由本機模型回答嗎？（自動路由時，LOCAL_CAPABLE 的任務是本機優先）"""
    if is_local_model(model_full_id):
        return True
    if (model_full_id or "") not in _AUTO_MODEL_IDS:
        return False
    try:
        preferred = brain.settings_manager.get_raw().get("selected_model", "auto_router") or ""
    except Exception:
        return False
    return is_local_model(preferred) or (preferred in _AUTO_MODEL_IDS and difficulty == "LOCAL_CAPABLE")


def _remember_usage(brain, user_message: str, tool_steps: List[Dict[str, Any]], final_text: str = "") -> None:
    """回合順利結束：記下「這句話 → 實際用了哪些工具」，供工具選擇器之後重新訓練；
    有操作軟體且全部成功時，另存成「成功經驗」，下次相似要求直接照著做。"""
    try:
        tool_router.log_usage(user_message, tool_steps, brain.security_guard.sanitize_secrets)
    except Exception:
        pass
    try:
        from . import app_experience, app_learning
        final_ok = bool((final_text or "").strip()) and not final_text.lstrip().startswith(("⚠️", "❌"))
        # 只開了軟體就反問使用者 → 不算做成功（不記成成功做法，改記成教訓）
        done = final_ok and not app_learning.looks_unfinished(final_text, tool_steps)
        app_experience.record_turn(user_message, tool_steps, done, brain.security_guard.sanitize_secrets)
        app_learning.record(user_message, tool_steps, done, brain.security_guard.sanitize_secrets)
    except Exception:
        pass


def summarize_unfinished(tool_steps: List[Dict[str, Any]], max_steps: int) -> str:
    """步數用完還沒結論時，具體說明做到哪、哪裡卡住，而不是回一句制式文字。"""
    try:
        from .tool_labels import describe_tool_call as _describe  # 白話工具名稱（有就用）
    except Exception:
        _describe = None

    def label(st: Dict[str, Any]) -> str:
        name = st.get("tool", "?")
        if _describe:
            try:
                d = _describe(name, st.get("args", {}))
                return f"{d['action']} {d.get('detail', '')}".strip()
            except Exception:
                pass
        return f"`{name}`"

    if not tool_steps:
        return f"⚠️ 已達單輪上限（{max_steps} 輪），但還沒有實際執行任何步驟。請把要求說得更具體，或改用雲端模型再試一次。"
    fails = [st for st in tool_steps
             if st.get("status") not in (None, "DONE")
             or any(m in str(st.get("result_preview", ""))[:200] for m in ('"ok": false', "❌", "失敗", "拒絕"))]
    counts: Dict[str, int] = {}
    for st in tool_steps:
        counts[st.get("tool", "?")] = counts.get(st.get("tool", "?"), 0) + 1
    repeated = [f"`{k}` × {v}" for k, v in counts.items() if v >= 3]
    lines = [f"⚠️ 已達單輪上限（{max_steps} 輪），任務**還沒完成**。這一輪做了 {len(tool_steps)} 個步驟："]
    for st in tool_steps[-5:]:
        mark = "❌" if st in fails else "✅"
        lines.append(f"- {mark} {label(st)}")
    if repeated:
        lines.append(f"- 重複太多次的動作：{'、'.join(repeated)}（可能卡在同一個畫面）")
    if fails:
        last = str(fails[-1].get("result_preview", ""))[:160]
        lines.append(f"- 最後一個失敗：{last}")
    lines.append("可以回覆「繼續」接著做，或把目標拆小一點；需要操作軟體時，也可以先問我「某軟體怎麼做某件事」。")
    return "\n".join(lines)


def tool_output_limit(model_full_id: Optional[str]) -> int:
    return 6_000 if is_local_model(model_full_id) else 20_000


def repair_history(history: List[Dict[str, Any]]) -> int:
    """
    上一輪若在工具執行到一半被緊急停止，歷史裡會留下「有 tool_calls 但沒有對應結果」的訊息，
    各家 API 都會拒收。這裡替缺少的結果補上「已中斷」，回傳補了幾筆。
    """
    answered = {m.get("tool_call_id") for m in history if m.get("role") == "tool"}
    fixed = 0
    i = 0
    while i < len(history):
        m = history[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            j = i + 1
            while j < len(history) and history[j].get("role") == "tool":
                j += 1
            missing = [tc for tc in m["tool_calls"] if tc.get("id") not in answered]
            for k, tc in enumerate(missing):
                history.insert(j + k, {"role": "tool", "tool_call_id": tc.get("id", ""),
                                       "name": (tc.get("function") or {}).get("name", ""),
                                       "content": "🛑 此工具呼叫已被使用者緊急停止中斷，沒有執行結果。"})
                answered.add(tc.get("id"))
                fixed += 1
            i = j + len(missing)
            continue
        i += 1
    return fixed


class _TokenBatcher:
    """把逐字 token 合併後再送給 UI。"""

    def __init__(self, cb: Optional[Callable]):
        self.cb = cb
        self.buf: List[str] = []
        self.last = 0.0

    async def push(self, text: str):
        if not self.cb:
            return
        self.buf.append(text)
        now = time.monotonic()
        if now - self.last >= TOKEN_FLUSH_SECONDS:
            await self.flush()
            self.last = now

    async def flush(self):
        if not self.cb or not self.buf:
            return
        chunk, self.buf = "".join(self.buf), []
        try:
            r = self.cb(chunk)
            if asyncio.iscoroutine(r):
                await r
        except Exception:
            pass


async def _emit_step(step_callback, info):
    if not step_callback:
        return
    try:
        r = step_callback(info)
        if asyncio.iscoroutine(r):
            await r
    except Exception:
        pass


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


async def run_turn(
    brain,
    session_id: str,
    user_message: str,
    model_full_id: Optional[str] = None,
    attached_image_b64: Optional[str] = None,
    step_callback: Optional[Callable] = None,
    token_callback: Optional[Callable] = None,
    max_steps: int = MAX_ROUNDS,
) -> Dict[str, Any]:
    from .habit_sync_engine import habit_sync_engine

    if session_id not in brain.conversations:
        habit_context = habit_sync_engine.load_prompt_context()
        system_content = brain.SYSTEM_PROMPT + (f"\n{habit_context}" if habit_context else "")
        brain.conversations[session_id] = [{"role": "system", "content": system_content}]
    history: List[Dict[str, Any]] = brain.conversations[session_id]
    repair_history(history)
    # 長對話管理：太長就截斷舊工具輸出、摘要最舊的對話（core/context_manager.py）
    from .context_manager import compact_history, make_llm_summarizer
    try:
        if is_local_model(model_full_id):
            await compact_history(history, make_llm_summarizer(brain, model_full_id),
                                  max_chars=18_000, keep_recent_chars=8_000)
        else:
            await compact_history(history, make_llm_summarizer(brain, model_full_id))
    except Exception:
        pass
    memory = _memory(brain)

    # ▼ 資安前置防禦：誘導輸出 API Key / 憑證的提示詞直接拒絕（與舊版相同）
    is_leak, _ = brain.security_guard.is_credential_leak_attempt(user_message)
    leak_keywords = ["給我", "告訴我", "輸出", "印出", "顯示", "列出", "查看", "讀取", "dump", "print", "reveal",
                     "tell me", "show me", "what is", "get key", "send key", "export key"]
    if is_leak and any(k in user_message.lower() for k in leak_keywords):
        refusal = ("🔒 **[最高資安防護攔截]** 系統已啟用機密憑證隔離防護機制。所有 API Key、金鑰與設定檔均屬於最高機密資產，"
                   "Agent 受到底層硬性防禦約束，**絕對禁止以任何方式顯示、輸出、複誦或洩漏金鑰內容**。")
        history.append({"role": "assistant", "content": refusal})
        return {"ok": True, "reply": refusal, "tool_steps": [], "model_used": model_full_id or "security_guard",
                "routing_info": {"model_used": "security_guard", "routing_reason": "資安金鑰防護攔截"},
                "screenshot_b64": None}

    # ▼ LLM 前置提示詞注入與 AI 倫理把關（在語意拆解與送入大模型前執行）
    prompt_check = {"blocked": False, "sanitized_text": user_message, "reason": "", "injection_detected": False}
    if hasattr(brain.security_guard, "inspect_user_prompt"):
        prompt_check = brain.security_guard.inspect_user_prompt(user_message)
    if prompt_check.get("blocked"):
        refusal = f"🛡️ **[前置安全與 AI 倫理攔截]** {prompt_check.get('reason', '請求違反安全規範')}"
        history.append({"role": "assistant", "content": refusal})
        return {"ok": True, "reply": refusal, "tool_steps": [], "model_used": model_full_id or "security_guard",
                "routing_info": {"model_used": "security_guard", "routing_reason": "前置注入或倫理攔截"},
                "screenshot_b64": None}
    safe_user_message = prompt_check.get("sanitized_text") or user_message

    # ▼ LLM 前置權限快速驗證（在語意拆解與模型開始之前把關，並明確告知模型哪些權限被拒絕）
    perm_summary: Dict[str, Any] = {"denied_tools": {}, "ask_tools": {}, "prompt_notice": ""}
    try:
        from .permissions import summarize_permissions_for_llm
        dlc_av_enabled: Optional[bool] = None
        try:
            from .addon_module_manager import addon_module_manager
            dlc_av_enabled = bool(addon_module_manager.is_enabled("guardian"))
        except Exception:
            dlc_av_enabled = None
        raw_settings = brain.settings_manager.get_raw() if hasattr(brain, "settings_manager") else {}
        perm_summary = summarize_permissions_for_llm(raw_settings, dlc_antivirus_enabled=dlc_av_enabled)
    except Exception:
        pass

    ctx_state = brain.context_guard.evaluate_state()

    # ▼ 前後文：這句沒講軟體、又是「動手做」的要求時，沿用前一輪在用的軟體
    #   （例：上一句「打開 word」，這句「新增檔案並輸入…」→ 在 Word 裡開新文件，不是建專案檔案）
    app_hint = None
    routing_message = safe_user_message
    if getattr(brain, "enable_local_tools", True):
        try:
            from .app_context import infer_active_app
            app_hint = infer_active_app(history, safe_user_message)
        except Exception:
            app_hint = None
        if app_hint:
            from .app_playbooks import PLAYBOOKS as _PB
            routing_message = f"在 {(_PB.get(app_hint) or {}).get('name', app_hint)} 裡{safe_user_message}"

    # ▼ 任務拆解：優先交由大語言模型 (LLM) 進行深度語意分析與任務拆解；
    #   僅當無可用 LLM 或呼叫失敗時，decompose 內部才會降級到備援。
    call_llm_fn = getattr(brain, "call_llm", None)
    task_plan = await brain.task_orchestrator.decompose(
        user_prompt=routing_message, context_state=ctx_state,
        call_llm_fn=call_llm_fn, model_full_id=model_full_id,
        permission_notice=perm_summary.get("prompt_notice", ""))
    if task_plan.intent_mode == "TASK" and task_plan.subtasks:
        await _emit_step(step_callback, {
            "step": 0, "type": "TASK_PLAN", "plan_id": task_plan.plan_id, "goal": task_plan.inferred_goal,
            "category": task_plan.category, "intent_mode": task_plan.intent_mode,
            "difficulty": task_plan.difficulty, "recommended_tools": task_plan.recommended_tools,
            "html": task_plan.to_html_card(), "timestamp": _now(),
        })

    # ▼ 僅當無 LLM 可用而降級至規則快速通道時，才走固定開軟體備援
    if (getattr(task_plan, "source", "") == "RULE_APP_LAUNCH" and getattr(task_plan, "launch_target", "")
            and getattr(brain, "enable_local_tools", True)):
        fast = await _fast_launch_app(brain, session_id, user_message, task_plan,
                                      step_callback, model_full_id)
        if fast is not None:
            return fast

    # ▼「某軟體怎麼做？」先查再答：小模型常不會主動讀說明／上網查而憑記憶亂答，
    #   所以由程式先讀本機說明＋上網查（照常經過權限），把資料交給模型整理（core/app_howto.py）
    prefetch_steps: List[Dict[str, Any]] = []
    howto_ctx = ""
    if getattr(brain, "enable_local_tools", True) and not app_hint:
        try:
            from . import app_howto as _howto
            howto_info = _howto.detect(user_message)
            if howto_info and not howto_info["want_web"] and _howto.is_covered(howto_info["app"], howto_info["task"]):
                howto_info = None  # 手冊／筆記已經有，知識庫會自動帶進提示詞
            if howto_info:
                calls = _howto.plan_calls(howto_info)
                outs = await _run_tool_batch(brain, calls, step_callback, prefetch_steps, 0, task_plan,
                                             model_full_id, session_id=session_id)
                howto_ctx, _found = _howto.build_context(
                    howto_info, [(c["name"], o) for c, (o, _img) in zip(calls, outs)])
        except Exception:
            howto_ctx = ""

    # ▼ 學習迴路：相似的事以前失敗過、還沒學會 → 動手前先讀本機說明／上網查（照常經過權限）。
    #   查到的資料會存進知識庫，下面的「軟體操作知識庫」段落會自動帶進提示詞。每件事只查一次。
    if getattr(brain, "enable_local_tools", True) and not howto_ctx:
        try:
            from . import app_howto as _howto_study, app_learning as _learning
            _target = _learning.study_target(routing_message)
            if _target:
                _calls = _howto_study.plan_calls({"app": _target[1], "task": _target[2], "want_web": False})
                await _run_tool_batch(brain, _calls, step_callback, prefetch_steps, 0, task_plan,
                                      model_full_id, session_id=session_id)
                _learning.mark_studied(_target[0], routing_message)
        except Exception:
            pass

    context_prefix = (
        f"[系統即時狀態：目前模式={ctx_state['label']} | "
        f"前景視窗=\"{ctx_state['foreground'].get('title', '')}\" | "
        f"滑鼠閒置={ctx_state['idle_seconds']}s | "
        f"意圖分流={task_plan.intent_mode} | 難度={task_plan.difficulty}]\n"
        f"{task_plan.to_system_context()}\n\n"
        "（只處理下面這則最新的要求；先前被中斷或已回覆過的要求，除非使用者這次再提，否則不要接著做。）\n\n"
    )
    from .task_orchestrator import is_computer_use_request
    if getattr(brain, "enable_local_tools", True) and not howto_ctx and (
            "操控" in (task_plan.category or "") or is_computer_use_request(user_message)):
        from .computer_use import PROMPT_GUIDE as _CU_GUIDE
        context_prefix = _CU_GUIDE + "\n" + context_prefix
    # ▼ 軟體自主偵測：首次啟動或偵測到新下載軟體時，主動通知並徵詢使用者同意建圖與實測
    if getattr(brain, "enable_local_tools", True):
        try:
            from . import app_auto_mapper as _auto_mapper
            await _auto_mapper.check_new_apps_on_startup_or_turn(brain)
        except Exception:
            pass
    # ▼ 軟體操作知識庫：提到某個軟體時，附上操作手冊、功能地圖與以前成功的做法（放在最靠近要求的位置）
    if getattr(brain, "enable_local_tools", True):
        try:
            from .app_skills import context_for as _app_context_for
            app_ctx = _app_context_for(routing_message)
        except Exception:
            app_ctx = ""
        if app_ctx:
            context_prefix = context_prefix + app_ctx + "\n"
        if app_hint:
            from .app_context import context_note as _app_note
            context_prefix = context_prefix + _app_note(app_hint)
        if howto_ctx:
            context_prefix = context_prefix + howto_ctx + "\n"
        try:
            from .addon_module_manager import addon_module_manager as _addon_mgr
            addon_guide = _addon_mgr.get_enabled_prompt_guides()
            if addon_guide:
                context_prefix = context_prefix + addon_guide + "\n\n"
        except Exception:
            pass
    if memory is not None:
        mem_text = memory.as_prompt()
        if mem_text:
            context_prefix = mem_text + "\n\n" + context_prefix
    if perm_summary.get("prompt_notice"):
        context_prefix = perm_summary["prompt_notice"] + "\n\n" + context_prefix
    if prompt_check.get("injection_detected") and prompt_check.get("reason"):
        context_prefix = f"⚠️ [前置安全提醒：{prompt_check['reason']}]\n\n" + context_prefix
    history.append({"role": "user", "content": context_prefix + safe_user_message})

    specs = tool_specs_for(brain.SYSTEM_PROMPT)
    mcp = _mcp_manager(brain)
    if mcp is not None:
        mcp.ensure_warming()           # 沒暖機過就在背景啟動（不等待）
        specs = specs + mcp.ready_specs()  # 只加入已經就緒的 MCP 工具，不讓聊天卡住
    if memory is not None:
        from .long_term_memory import TOOL_SPECS as _MEMORY_SPECS
        specs = specs + _MEMORY_SPECS
    if getattr(brain, "enable_local_tools", True):
        from .local_tools import TOOL_SPECS as _LOCAL_SPECS  # OCR / 本機檔案搜尋 / 讀檔
        specs = specs + _LOCAL_SPECS
        from .computer_use import TOOL_SPECS as _CU_SPECS  # 按鍵 / 滾輪 / 拖曳 / 等待
        specs = specs + _CU_SPECS
        from .app_skills import TOOL_SPECS as _APP_SPECS  # 軟體操作知識庫 / 寫檔 / 用指定軟體開檔
        specs = specs + _APP_SPECS
    denied_tool_names = set(perm_summary.get("denied_tools") or {})
    if denied_tool_names:
        specs = [
            s for s in specs
            if (s.get("function") or {}).get("name") not in denied_tool_names
        ]
    # 多代理團隊：自己的終端、開子代理、互傳訊息（只有掛在團隊裡的代理才有）
    from .agent_team import team as _team, TOOL_SPECS as _TEAM_SPECS
    team_aid = _team.agent_for_session(session_id)
    if team_aid is not None:
        _team.begin_turn(team_aid)
        is_main = _team.is_main(team_aid)
        specs = specs + [s for s in _TEAM_SPECS if s["name"] != "spawn_subagent" or is_main]
        me = _team.members.get(team_aid)
        role = (f"[你是主代理「{me.name}」。PowerShell 指令請用 terminal_run 在你自己的終端執行；"
                f"大任務可以用 spawn_subagent 拆給子代理平行處理，再用 wait_subagents 收結果。]\n"
                if is_main else
                f"[你是子代理「{me.name}」。PowerShell 指令請用 terminal_run；有需要可用 send_to_agent 回報上層。]\n")
        role += _team.context_for(team_aid)  # 畫布上連給這個代理的便利貼、連結、圖片、資料夾
        if history and history[-1].get("role") == "user" and isinstance(history[-1].get("content"), str):
            history[-1]["content"] = role + history[-1]["content"]
    # ▼ 工具防呆：修正名稱／參數、擋空轉（看的是完整清單，被篩掉的工具仍可執行）
    guard = ToolGuard(specs)
    # ▼ 工具選擇器：本機小模型一次看七十幾個工具容易選錯，先用本機訓練的分類器挑出最相關的十幾個。
    #   沒訓練過、沒把握或嵌入服務不可用時 routed 為 None，照舊給完整清單。
    routed = None
    use_routed = likely_local_model(brain, model_full_id, task_plan.difficulty)
    if use_routed and task_plan.intent_mode != "CHAT":
        keep = list(task_plan.recommended_tools or [])
        for st in task_plan.subtasks or []:
            keep.extend(getattr(st, "allocated_tools", None) or [])
        routed = await tool_router.select_specs(user_message, specs, keep)
    batcher = _TokenBatcher(token_callback)
    tool_steps: List[Dict[str, Any]] = list(prefetch_steps)
    latest_shot: Optional[str] = attached_image_b64
    current_img = attached_image_b64
    model_used = model_full_id or ""
    routing_info: Dict[str, Any] = {}
    step_no = len(prefetch_steps)
    empty_retry_used = False

    for _round in range(max_steps):
        if brain.security_guard.emergency_stop_triggered:
            msg = "🛑 已觸發緊急停止開關 (Kill Switch)，所有操作已立即中止。"
            history.append({"role": "assistant", "content": msg})
            return {"ok": False, "reply": msg, "tool_steps": tool_steps, "model_used": model_used,
                    "routing_info": routing_info, "screenshot_b64": latest_shot}

        res = await brain.call_llm(messages=history, model_full_id=model_full_id, image_b64=current_img,
                                   difficulty=task_plan.difficulty,
                                   tools=([] if howto_ctx and _round == 0 else
                                          routed["specs"] if routed and use_routed else specs),
                                   on_text=batcher.push)
        await batcher.flush()
        current_img = None
        model_used = res.get("model_used", model_used)
        if routed and res.get("model_used"):
            use_routed = is_local_model(res["model_used"])  # 實際由雲端模型回答 → 之後給完整清單
        if step_callback and model_used:
            _emit_step(step_callback, {
                "type": "MODEL_ROUTED",
                "model_used": model_used,
                "is_local": is_local_model(model_used),
            })
        if team_aid is not None:
            try:
                _team.record_usage(session_id, res.get("usage"), res.get("model_used") or model_used, history)
            except Exception:
                pass
        routing_info = {
            "model_used": model_used, "routing_reason": res.get("routing_reason"),
            "task_type": res.get("task_type"), "failover_count": res.get("failover_count", 0),
            "routed_from": res.get("routed_from"),
        }
        if not res.get("ok"):
            err = brain.security_guard.sanitize_secrets(res.get("error", "未知錯誤"))
            history.append({"role": "assistant", "content": err})
            return {"ok": False, "reply": err, "tool_steps": tool_steps, "model_used": model_used,
                    "routing_info": routing_info, "screenshot_b64": latest_shot}

        text = brain.security_guard.sanitize_secrets(res.get("content", ""))
        calls = guard.prepare(res.get("tool_calls") or [])
        if routed:  # 模型叫了清單外但確實存在的工具：之後也讓它看得到定義
            shown = {s["name"] for s in routed["specs"]}
            extra = {c["name"] for c in calls if c["name"] not in shown and c["name"] in guard.specs}
            if extra:
                routed["specs"] = [s for s in specs if s["name"] in shown | extra]

        if res.get("native_tools"):
            if not calls and not text.strip():
                if not empty_retry_used:
                    empty_retry_used = True
                    history.append({"role": "user", "content": "（你剛才只有內部思考、沒有給出回覆。請直接用繁體中文給使用者最終回覆；"
                                                               "若還需要資料就呼叫工具。只有使用者本人能做的事，例如啟用 API、登入、核准，請直接告訴他怎麼做。）"})
                    continue
                text = "⚠️ 模型這一輪沒有產生回覆（可能是對話太長、上下文被截斷）。請再問一次，或在右上角改用 Gemini 等雲端模型。"
            if not calls:
                # 挽救機制：部分原生 tools 模型（如 flash-lite）偶爾誤把 tool_call JSON 寫進純文字，
                # 先交給 ToolCallECC 檢查並自動執行，嚴禁把生肉 tool_call 輸出給使用者。
                ecc_fallback = ToolCallECC.inspect_and_correct(text)
                if ecc_fallback.get("is_tool_call"):
                    if ecc_fallback.get("ok"):
                        salvaged = guard.prepare([{
                            "id": f"salvage_{step_no + 1}",
                            "name": ecc_fallback["tool"],
                            "args": ecc_fallback["args"],
                            "ecc_corrections": ecc_fallback.get("corrections", []),
                        }])
                        calls = salvaged
                    else:
                        history.append({"role": "assistant", "content": text})
                        guidance = ecc_fallback.get("recovery_guidance") or ecc_fallback.get("error")
                        history.append({"role": "user", "content": f"[工具調用格式修正]:\n{guidance}\n\n請直接使用 function calling 呼叫工具，勿輸出純文字 JSON。"})
                        continue
            if not calls:
                history.append({"role": "assistant", "content": text})
                _remember_usage(brain, user_message, tool_steps, text)
                return {"ok": True, "reply": text, "tool_steps": tool_steps, "model_used": model_used,
                        "routing_info": routing_info, "screenshot_b64": latest_shot}
            history.append({
                "role": "assistant", "content": text or None,
                "tool_calls": [{"id": c["id"], "type": "function",
                                "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                               for c in calls],
            })
            results = await _run_tool_batch(brain, calls, step_callback, tool_steps, step_no, task_plan, model_full_id,
                                            session_id=session_id, guard=guard)
            step_no += len(calls)
            new_shot = None
            for c, (output, img) in zip(calls, results):
                history.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"], "content": output})
                if img:
                    new_shot = img
            if new_shot:
                latest_shot = current_img = new_shot
                history.append({"role": "user", "content": "（上方工具回傳的畫面截圖如附圖，請據此決定下一步。）"})
            continue

        # ---------------- 退回文字協議（模型不支援原生 tools）----------------
        history.append({"role": "assistant", "content": text})
        ecc = ToolCallECC.inspect_and_correct(text)
        if not ecc["is_tool_call"]:
            _remember_usage(brain, user_message, tool_steps, text)
            return {"ok": True, "reply": text, "tool_steps": tool_steps, "model_used": model_used,
                    "routing_info": routing_info, "screenshot_b64": latest_shot}
        step_no += 1
        if not ecc["ok"]:
            info = {"step": step_no, "tool": ecc.get("tool") or "syntax_error", "args": {}, "status": "ECC_WARN",
                    "ecc_corrections": ecc.get("corrections", []),
                    "result_preview": f"⚠️ ECC 檢查發現錯誤：{ecc.get('error')}", "timestamp": _now()}
            tool_steps.append(info)
            await _emit_step(step_callback, info)
            guidance = ecc.get("recovery_guidance") or ecc.get("error")
            history.append({"role": "user", "content": f"[ECC 工具調用檢查警報]:\n{guidance}\n\n請根據上方具體說明修復參數或語法後重新調用工具。"})
            continue
        call, = guard.prepare([{"id": f"text_{step_no}", "name": ecc["tool"], "args": ecc["args"],
                                "ecc_corrections": ecc.get("corrections", [])}])
        (output, img), = await _run_tool_batch(brain, [call], step_callback, tool_steps, step_no - 1, task_plan,
                                               model_full_id, session_id=session_id, guard=guard)
        if img:
            latest_shot = current_img = img
        history.append({"role": "user", "content": f"[工具 `{call['name']}` 執行結果]:\n{output}\n\n請根據此結果決定下一步工具呼叫，或直接給出最終回覆。"})

    final = summarize_unfinished(tool_steps, max_steps)
    try:  # 步數用完還沒做完：把失敗的做法記成教訓，下次先查資料再做
        from . import app_learning as _learning_end
        _learning_end.record(user_message, tool_steps, False, brain.security_guard.sanitize_secrets)
    except Exception:
        pass
    history.append({"role": "assistant", "content": final})
    return {"ok": True, "reply": final, "tool_steps": tool_steps, "model_used": model_used,
            "routing_info": routing_info, "screenshot_b64": latest_shot}


async def _fast_launch_app(brain, session_id, user_message, task_plan, step_callback, model_full_id):
    """「開啟 X」快速通道：查本機安裝 → launch_application（允許清單／同意卡片照常由 execute_tool 把關）。
    本機查不到符合的軟體時回傳 None，交回一般 LLM 流程處理。"""
    target = task_plan.launch_target
    tool_steps: List[Dict[str, Any]] = []
    find_call = {"id": "fast_launch_find", "name": "list_installed_software",
                 "args": {"query": target, "max_items": 5}}
    (found_out, _), = await _run_tool_batch(brain, [find_call], step_callback, tool_steps, 0, task_plan,
                                            model_full_id, session_id=session_id)
    try:
        matches = json.loads(found_out)
    except Exception:
        matches = []
    if not isinstance(matches, list) or not matches:
        return None

    app_name = str(matches[0].get("name") or target)
    launch_call = {"id": "fast_launch_open", "name": "launch_application",
                   "args": {"target": app_name,
                            "purpose": f"使用者要求「{user_message.strip()}」",
                            "plan": f"開啟本機安裝的「{app_name}」，開啟後不做其他操作"}}
    (launch_out, _), = await _run_tool_batch(brain, [launch_call], step_callback, tool_steps, 1, task_plan,
                                             model_full_id, session_id=session_id)
    try:
        res = json.loads(launch_out)
    except Exception:
        res = {"ok": False, "error": launch_out}
    if isinstance(res, dict) and res.get("ok"):
        reply = f"✅ 已開啟 **{res.get('launched') or app_name}**。"
    else:
        err = res.get("error") if isinstance(res, dict) else launch_out
        reply = f"❌ 沒有開啟「{app_name}」：{err or launch_out}"

    history = brain.conversations[session_id]
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply})
    return {"ok": True, "reply": reply, "tool_steps": tool_steps, "model_used": "rule:app_launch",
            "routing_info": {"model_used": "rule:app_launch", "routing_reason": "🚀 開啟本機軟體快速通道（免模型推理）"},
            "screenshot_b64": None}


def _tool_failed(out: str) -> bool:
    """工具輸出代表失敗？（JSON 的 ok 為 false、被權限／免打擾擋下，或以 ❌ 開頭）——給步驟列顯示用。"""
    s = (out or "").lstrip()
    if s.startswith("❌"):
        return True
    if s.startswith("{"):
        try:
            d = json.loads(s)
        except Exception:
            return False
        return isinstance(d, dict) and (d.get("ok") is False or bool(d.get("blocked_by_permission"))
                                        or bool(d.get("deferred_by_dnd")))
    return False


async def _run_tool_batch(brain, calls, step_callback, tool_steps, step_base, task_plan, model_full_id,
                          session_id: str = "", guard: Optional[ToolGuard] = None):
    """相鄰的只讀工具並行；會改變狀態的工具依序執行。回傳與 calls 同順序的 [(output, img_b64)]。"""
    mcp = _mcp_manager(brain)

    memory = _memory(brain)
    from .long_term_memory import READ_ONLY as _MEM_RO, TOOL_NAMES as _MEM_TOOLS
    from . import local_tools as _local
    from . import app_skills as _skills
    from . import schedule_tools as _sched_tools
    from . import computer_use as _cu
    from . import agent_team as _teamtools
    in_team = bool(session_id) and _teamtools.team.agent_for_session(session_id) is not None

    def read_only(name: str) -> bool:
        if in_team and name in _teamtools.TOOL_NAMES:
            return name in _teamtools.READ_ONLY
        if mcp is not None and mcp.is_mcp_tool(name):
            return mcp.is_read_only(name)
        if name in _MEM_TOOLS:
            return name in _MEM_RO
        if name in _local.TOOL_NAMES:
            return name in _local.READ_ONLY
        if name in _skills.TOOL_NAMES:
            return name in _skills.READ_ONLY
        if name in _cu.TOOL_NAMES:
            return name in _cu.READ_ONLY
        return name in READ_ONLY_TOOLS

    infos = []
    for i, c in enumerate(calls):
        info = {"step": step_base + i + 1, "tool": c["name"], "args": c["args"], "status": "RUNNING",
                "ecc_corrections": c.get("ecc_corrections", []), "timestamp": _now(),
                "parallel": len(calls) > 1 and read_only(c["name"])}
        tool_steps.append(info)
        infos.append(info)

    async def one(c, info):
        await _emit_step(step_callback, info)
        blocked = c.get("guard_error")
        if blocked:
            out, img = blocked, None
        elif "__raw_arguments__" in c["args"]:
            out, img = (f"❌ 工具參數不是合法 JSON：{c['args']['__raw_arguments__'][:200]}，請修正後重新呼叫。", None)
        elif mcp is not None and mcp.is_mcp_tool(c["name"]):
            out, img = await _call_mcp_tool(brain, mcp, c)
        elif memory is not None and c["name"] in _MEM_TOOLS:
            out, img = memory.run_tool(c["name"], c["args"]), None
        elif c["name"] in _local.TOOL_NAMES:
            out, img = await _local.run_tool(c["name"], c["args"], brain)
        elif c["name"] in _skills.TOOL_NAMES:
            out, img = await _skills.run_tool(c["name"], c["args"], brain)
        elif c["name"] in _sched_tools.TOOL_NAMES:
            out, img = await _sched_tools.run_tool(c["name"], c["args"])
        elif c["name"] in _cu.TOOL_NAMES:
            out, img = await _cu.run_tool(c["name"], c["args"], brain)
        elif in_team and c["name"] in _teamtools.TOOL_NAMES:
            out, img = await _teamtools.run_tool(c["name"], c["args"], brain, session_id)
        elif in_team and c["name"] == "run_background_shell":
            # 團隊裡的代理：PowerShell 指令改在它自己的（或串線共用的）終端執行，使用者看得到
            cmd = str(c["args"].get("command", ""))
            cwd = str(c["args"].get("cwd") or "").strip()
            if cwd:
                cmd = f"Set-Location -LiteralPath '{cwd.replace(chr(39), chr(39) * 2)}'; " + cmd
            out, img = await _teamtools.run_tool("terminal_run", {"command": cmd}, brain, session_id)
        else:
            try:
                out, img = await brain.execute_tool(c["name"], c["args"], model_full_id=model_full_id)
            except Exception as e:
                out, img = f"❌ 工具執行例外：{type(e).__name__}: {e}", None
        out = brain.security_guard.sanitize_secrets(out or "")
        if guard is not None and not blocked:
            guard.record(c, out)
        limit = tool_output_limit(model_full_id)
        if len(out) > limit:
            out = out[:limit] + f"\n…（輸出太長，已截斷，只保留前 {limit} 字；需要更多請縮小查詢範圍）"
        try:
            task_plan.advance_with_tool_call(c["name"], c["args"], out)
        except Exception:
            pass
        info["status"] = "DONE"
        info["failed"] = _tool_failed(out)
        info["result_preview"] = out[:300]
        info["active_plan_html"] = task_plan.to_html_card()
        await _emit_step(step_callback, info)
        return out, img

    results: List[Any] = [None] * len(calls)
    i = 0
    while i < len(calls):
        if read_only(calls[i]["name"]):
            j = i
            while j < len(calls) and read_only(calls[j]["name"]):
                j += 1
            outs = await asyncio.gather(*(one(calls[k], infos[k]) for k in range(i, j)))
            results[i:j] = outs
            i = j
        else:
            results[i] = await one(calls[i], infos[i])
            i += 1
    return results


# ====================================================================== 長期記憶
def _memory(brain):
    """brain 可以帶自己的 long_term_memory（測試用，None 代表停用）；否則用全域的本機記憶檔。"""
    if hasattr(brain, "long_term_memory"):
        return brain.long_term_memory
    try:
        from .long_term_memory import get_memory
        return get_memory(sanitize=brain.security_guard.sanitize_secrets)
    except Exception:
        return None


# ====================================================================== MCP
def _mcp_manager(brain):
    """brain 可以帶自己的 mcp_manager（測試用）；否則用全域單例。"""
    if hasattr(brain, "mcp_manager"):
        return brain.mcp_manager
    try:
        from .mcp_client import mcp_manager
        return mcp_manager
    except Exception:
        return None


def mcp_needs_approval(mcp, name: str, execution_mode: str) -> bool:
    """與 shell 指令同一套規則：唯讀不問；Turbo 不問；Auto 只問破壞性；Default / 嚴格審查非唯讀都問。"""
    if mcp.is_read_only(name):
        return False
    mode = (execution_mode or "default").lower()
    if mode == "turbo":
        return False
    if mode == "auto":
        return mcp.is_destructive(name)
    return True


async def _call_mcp_tool(brain, mcp, c):
    sec = brain.security_guard
    if mcp_needs_approval(mcp, c["name"], getattr(sec, "execution_mode", "default")) and hasattr(sec, "request_user_approval"):
        preview = json.dumps(c["args"], ensure_ascii=False)[:300]
        ok, msg = await sec.request_user_approval(
            risk_level="HIGH_RISK",
            title=f"MCP 工具：{c['name']}",
            reason=f"這個 MCP 工具可能會修改檔案或外部資料。參數：{preview}",
            action_payload={"action": "mcp_tool", "tool": c["name"], "args": c["args"]},
        )
        if not ok:
            return f"🛑 使用者未批准此操作：{msg}", None
    try:
        return await mcp.call(c["name"], c["args"])
    except Exception as e:
        return f"❌ MCP 工具執行例外：{type(e).__name__}: {e}", None
