# -*- coding: utf-8 -*-
"""
core/task_orchestrator.py
=========================
語意任務拆分與自主工具分配調度器 (Semantic Task Orchestrator)
完全遵循 OOP 與 SOLID 原則：
1. 單一職責 (SRP)：專注於將使用者的自然語言提示詞拆解為結構化子任務，並自動分配最佳工具鏈。
2. API 語意優先 (LLM-driven Semantic Analysis)：直接調用大腦 LLM API 進行深度意圖解析與動態子任務生成，拒絕死板關鍵字規則。
3. 零使用者點擊 (Zero-Click Autonomy)：讓使用者僅需給出自然語言 Prompt，其餘環境感知、工具調度與驗證全自動完成。
"""
from dataclasses import dataclass, field
import datetime
import html
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class SubTask:
    """單一子任務資料模型"""
    step_id: int
    title: str
    description: str
    intent_phase: str  # PERCEPTION (環境感知/定位), EXECUTION (核心執行), VERIFICATION (驗證自檢), SYNTHESIS (結果整合)
    allocated_tools: List[str] = field(default_factory=list)
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, SKIPPED
    result_summary: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def start(self):
        self.status = "RUNNING"
        self.started_at = datetime.datetime.now().strftime("%H:%M:%S")

    def complete(self, summary: str = ""):
        self.status = "COMPLETED"
        self.completed_at = datetime.datetime.now().strftime("%H:%M:%S")
        if summary:
            self.result_summary = summary

    def fail(self, error_msg: str):
        self.status = "FAILED"
        self.completed_at = datetime.datetime.now().strftime("%H:%M:%S")
        self.result_summary = error_msg


@dataclass
class TaskPlan:
    """結構化任務總計畫"""
    plan_id: str
    user_prompt: str
    inferred_goal: str
    category: str
    subtasks: List[SubTask] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    is_completed: bool = False
    source: str = "LLM_API"  # LLM_API 或 HEURISTIC_FALLBACK
    intent_mode: str = "TASK"  # CHAT (一般對話免工具) 或 TASK (需派發工具任務)
    difficulty: str = "LOCAL_CAPABLE"  # LOCAL_CAPABLE (本地模型即可) 或 CLOUD_API_REQUIRED (複雜任務調用雲端強模 API)
    launch_target: str = ""  # RULE_APP_LAUNCH：使用者要開啟的軟體名稱
    recommended_tools: List[str] = field(default_factory=list)

    @property
    def current_subtask(self) -> Optional[SubTask]:
        for st in self.subtasks:
            if st.status in ("PENDING", "RUNNING"):
                return st
        return None

    def advance_with_tool_call(self, tool_name: str, tool_args: Dict[str, Any], tool_output: str):
        """根據工具執行結果自動推進子任務進度"""
        current = self.current_subtask
        if not current:
            return

        if current.status == "PENDING":
            current.start()

        clean_output = tool_output.strip()
        preview = clean_output[:120].replace("\n", " ") if clean_output else "執行完畢"
        
        # 若該工具屬於分配工具名單或無特別限制
        if tool_name in current.allocated_tools or len(current.allocated_tools) == 0:
            current.complete(f"[{tool_name}] {preview}")
        else:
            current.result_summary = f"[{tool_name}] 推進中"

        if all(st.status in ("COMPLETED", "SKIPPED") for st in self.subtasks):
            self.is_completed = True

    # 卡片上顯示的白話狀態（Qt QTextBrowser 不支援 flex，所以版面一律用 table）
    _STATUS_TEXT = {
        "PENDING": ("⚪", "還沒開始", "#8b949e"),
        "RUNNING": ("🟡", "進行中", "#fbbf24"),
        "COMPLETED": ("🟢", "完成", "#34d399"),
        "FAILED": ("🔴", "失敗", "#f87171"),
        "SKIPPED": ("⚫", "跳過", "#9ca3af"),
    }

    def to_html_card(self) -> str:
        """產出內嵌至聊天室的任務計畫卡片：白話標題 + 每步狀態，不顯示內部術語與工具名稱"""
        rows = []
        for idx, st in enumerate(self.subtasks, start=1):
            dot, label, color = self._STATUS_TEXT.get(st.status, ("⚪", st.status, "#8b949e"))
            result_line = ""
            if st.result_summary:
                result_line = (
                    f"<br><span style='font-size:11px;color:#8b949e;'>→ {html.escape(st.result_summary[:120])}</span>"
                )
            rows.append(
                "<tr>"
                f"<td width='26' valign='top' style='color:#c9d1d9;font-size:12.5px;'>{idx}.</td>"
                f"<td valign='top' style='color:#e6edf3;font-size:12.5px;'>{html.escape(st.title)}{result_line}</td>"
                f"<td width='86' align='right' valign='top' style='color:{color};font-size:11.5px;'>{dot} {label}</td>"
                "</tr>"
            )

        model_hint = "雲端大模型" if self.difficulty == "CLOUD_API_REQUIRED" else "本機模型"
        planner_hint = "AI 規劃" if self.source == "LLM_API" else "內建規則規劃"
        return (
            "<table width='100%' cellspacing='0' cellpadding='4' "
            "style='background:#161b22;border:1px solid #30363d;margin:6px 0;'>"
            "<tr><td colspan='3' style='color:#58a6ff;font-weight:bold;font-size:13px;'>📋 我打算這樣做</td></tr>"
            f"<tr><td colspan='3' style='color:#c9d1d9;font-size:12px;'>你的要求：{html.escape(self.user_prompt.strip()[:200])}</td></tr>"
            f"{''.join(rows)}"
            f"<tr><td colspan='3' style='color:#6e7681;font-size:10.5px;'>{html.escape(self.category)} · {planner_hint} · 使用{model_hint}</td></tr>"
            "</table>"
        )

    def to_system_context(self) -> str:
        """生成供 LLM 遵守之結構化任務推進提示，確保大腦嚴格按步驟自主執行或純對話回覆"""
        if self.intent_mode == "CHAT" or not self.subtasks:
            return (
                "### 【對話意圖判定：純對話 / 知識問答模式 (CHAT)】\n"
                "💬 系統判定使用者此訊息屬於「一般對話、觀念解答或獨立程式碼生成」，**不需要操作電腦視窗或執行系統工具**。\n"
                "👉 請直接用繁體中文給出精確、完整的回答，**嚴禁輸出任何 ```tool_call 區塊**！"
            )
        lines = [
            f"### 【自主任務拆解與調度指示 (難度評級: {self.difficulty})】",
            f"🎯 總目標：{self.inferred_goal}",
            "📋 系統已自動將使用者提示詞拆解為以下子任務，請依序自主推進工具調用，嚴禁要求使用者手動點擊或介入：",
        ]
        for st in self.subtasks:
            status_mark = "✔" if st.status == "COMPLETED" else ("▶" if st.status == "RUNNING" else "⏳")
            tools_str = f" [推薦工具: {', '.join(st.allocated_tools)}]" if st.allocated_tools else ""
            res_str = f" -> 已獲取結果: {st.result_summary[:80]}" if st.result_summary else ""
            lines.append(f"  {status_mark} 步驟 {st.step_id}: {st.title} ({st.intent_phase}){tools_str}{res_str}")
        
        cur = self.current_subtask
        if cur:
            tool_hint = f"（優先使用 `{cur.allocated_tools[0]}`）" if cur.allocated_tools else ""
            lines.append(f"\n👉 目前請立即執行「步驟 {cur.step_id}: {cur.title}」{tool_hint}，直接輸出對應的 ```tool_call 區塊！")
        else:
            lines.append("\n👉 所有子任務已完成，請進行最終成果整合回報！")
        return "\n".join(lines)


_COMPUTER_USE_KEYWORDS = (
    "操控", "操作電腦", "控制電腦", "操作我的電腦", "幫我操作", "自己操作", "模仿使用者", "模仿我",
    "像人一樣", "滑鼠", "鍵盤", "computer use", "computer-use", "電腦操作",
)


def is_computer_use_request(prompt: str) -> bool:
    """使用者要 agent 像人一樣用滑鼠鍵盤操作電腦（Claude computer use 那類）。"""
    p = (prompt or "").lower()
    return any(k in p for k in _COMPUTER_USE_KEYWORDS)


_AI_CODING_TOOL_NAME_KEYWORDS = (
    "antigravity", "vscode", "vs code", "codex", "claude code", "cursor", "claude",
)
# 註：「打開／開啟」不能放這裡——「開啟 vscode」只是要開軟體，不是要對它下提示詞，
# 放進來會被誤判成提示詞派送，小模型接著亂查軟體清單、永遠不會真的開啟（2026-11-11 實測）。
_AI_DISPATCH_ACTION_KEYWORDS = (
    "輸入", "提示", "問", "叫", "指示", "送出", "發送", "送",
    "幫我叫", "下提示詞", "派送", "說",
)

# ── 「開啟某軟體」快速通道 ─────────────────────────────────────
_LAUNCH_RE = re.compile(
    r"^(?:請|麻煩)?\s*(?:幫我|替我|給我|你)?\s*"
    r"(?:在電腦上|在本機上|在本機|電腦上|本機)?\s*"
    r"(?:打開|開啟|啟動|開一下|open|launch|start)\s*(?:一下)?\s*"
    r"(?P<target>.+?)\s*(?:一下|吧|啦|好嗎|好不好|謝謝|thanks)?\s*[。.!！?？~～]*$",
    re.IGNORECASE,
)
_LAUNCH_MODIFIER_PREFIX_RE = re.compile(
    r"^(?:在電腦上|在本機上|在本機|電腦上|電腦裡|本機的|本機|電腦|桌面)\s*(?:的)?\s*",
    re.IGNORECASE,
)
_LAUNCH_MODIFIER_SUFFIX_RE = re.compile(
    r"\s*(?:在電腦上|在本機上|在本機|電腦上|電腦裡|本機版|電腦版|桌面版|應用程式|軟體|程式|\bdesktop\b|\bapp\b|\bon my computer\b|\bon computer\b|\bon pc\b|\blocally\b)+\s*$",
    re.IGNORECASE,
)
# 出現這些字代表不只是「開軟體」，交給一般規劃流程
_LAUNCH_BLOCK_WORDS = (
    "叫", "問", "讓它", "請它", "輸入", "提示", "送出", "傳給", "說", "並", "然後", "再", "後",
    "，", ",", "、", "網頁", "網址", "http", "www.", "檔案", "資料夾", "目錄", "文件",
    ".py", ".txt", ".md", ".json", ".pdf", "\\", "/",
)


def _strip_launch_modifiers(text: str) -> str:
    """剝除軟體名稱頭尾的環境／位置修飾詞（如「在電腦上」「桌面版」）。"""
    s = (text or "").strip(" 「」『』\"'`")
    for _ in range(3):
        prev = s
        s = _LAUNCH_MODIFIER_PREFIX_RE.sub("", s).strip(" 「」『』\"'`")
        s = _LAUNCH_MODIFIER_SUFFIX_RE.sub("", s).strip(" 「」『』\"'`")
        if s == prev:
            break
    return s


def extract_app_launch_target(prompt: str) -> Optional[str]:
    """「開啟 vscode」「幫我打開 Chrome」「打開claude在電腦上」這種單純開軟體的要求 → 回傳軟體名稱；其他回傳 None。"""
    p = (prompt or "").strip()
    if not p or len(p) > 40 or "\n" in p:
        return None
    m = _LAUNCH_RE.match(p)
    if not m:
        return None
    raw_target = m.group("target").strip(" 「」『』\"'`")
    target = _strip_launch_modifiers(raw_target) or raw_target
    if not target or len(target) > 30:
        return None
    low = target.lower()
    if any(w in low for w in _LAUNCH_BLOCK_WORDS):
        return None
    return target


def is_ai_tool_dispatch_request(prompt: str) -> bool:
    """
    使用者要 agent 去叫某個 AI 編碼工具（Antigravity/VS Code/Codex/Claude Code/Cursor）做事。
    跟 is_computer_use_request 一樣，在呼叫 LLM 規劃前先攔下來，不要讓本機小模型自由發揮——
    本機 20B/12B 小模型常常不會照 AVAILABLE_TOOLS_SUMMARY 的指示選 dispatch_ai_coding_prompt，
    反而亂猜成 list_installed_software、檔案搜尋等不相干工具。
    """
    p = (prompt or "").lower()
    return (
        any(k in p for k in _AI_CODING_TOOL_NAME_KEYWORDS)
        and any(k in p for k in _AI_DISPATCH_ACTION_KEYWORDS)
    )


class SemanticTaskOrchestrator:
    """
    任務語意拆分與工具自動分配中樞
    【核心規範】優先調用 LLM API 進行深度自然語言語意解析與動態子任務拆分，無 API 時自動平滑降級至啟發式規劃。
    """

    AVAILABLE_TOOLS_SUMMARY = """
- inspect_accessibility_tree: 透過 Windows 無障礙 API 提取視窗結構樹與元素 ID（如 #1, #2），首選此項代替截圖
- ui_invoke: 透過無障礙 Invoke/Toggle/Select 原生觸發按鈕或開關（零滑鼠干擾）
- ui_type: 透過無障礙 ValuePattern 原生直接填入文字
- ui_click: 定位無障礙元素中心點擊
- ui_read_text: 提取長篇文件或編輯器純文字
- list_windows: 列出桌面所有開啟中的視窗 (HWND, 標題)
- inspect_window_background: 背景截圖視覺分析
- capture_desktop_screen: 全螢幕視覺截圖
- click_screen: 螢幕座標 (X, Y) 滑鼠點擊
- type_text: 鍵盤模擬輸入文字
- run_background_shell: 背景無黑窗執行 PowerShell 指令、檢索檔案、測試或 Git
- send_ide_feedback: 將修正回報給 IDE
- dispatch_ai_coding_prompt: 自動找到本機已開啟的 AI 編碼工具視窗（antigravity|vscode|codex|claude_code|cursor）並直接送出提示詞，取代 ui_type 盲目搜尋輸入框；只要使用者意圖是「叫/問/請某個 AI 編碼工具做事」就優先選此工具，不要用 inspect_accessibility_tree + ui_type 慢慢找
- list_installed_software: 列出本機已安裝軟體清冊（唯讀地圖），不需使用者同意
- launch_application: 開啟本機軟體，每次都會先跳出核准卡片，需使用者同意才會真正啟動
- web_search: 聯網搜尋關鍵字
- web_fetch: 抓取指定網頁正文
- browser_navigate: 操控瀏覽器開啟網址
- browser_extract: 提取網頁文字與可點擊元素
- audit_system_security: 檢查開機啟動項與安全庫存
- scan_antivirus: 本地與 Defender 雙引擎深度掃毒
- kill_threat_process: 終止惡意進程
- lock_file_anti_tamper: 啟用檔案防篡改鎖定
- gmail_list_messages: 搜尋或查看 Gmail
- gmail_send_message: 發送 Gmail
- gdrive_search_files: 搜尋 Google 雲端硬碟檔案
- gdocs_create_or_append: 讀寫 Google Docs
- gsheets_action: 讀寫 Google Sheets
"""

    def __init__(self):
        self._counter = 1

    # 供快速預判是否為純對話或需要工具的關鍵特徵
    TASK_ACTION_MARKERS = [
        # 桌面與視窗操作
        "視窗", "螢幕", "畫面", "桌面", "點擊", "按鈕", "輸入", "操作", "點選", "無障礙", "控制項", "截圖", "開啟", "打開", "關閉",
        "操控", "滑鼠", "鍵盤", "computer use",
        # 檔案與終端指令
        "檔案", "目錄", "資料夾", "執行", "指令", "終端", "腳本", "powershell", "cmd", "git", "pytest", "測試", "讀取", "寫入", "整理", "檢查", "查看", "列出",
        # 上網與搜尋
        "搜尋", "上網", "網頁", "網址", "瀏覽器", "查一下", "查詢", "最新", "新聞", "http://", "https://", "爬蟲",
        # Google Workspace
        "gmail", "信箱", "郵件", "寄信", "雲端硬碟", "gdrive", "日曆", "行事曆", "calendar", "試算表", "gsheet", "gdocs", "習慣",
        # 資安與防毒
        "掃毒", "病毒", "木馬", "惡意", "防火牆", "自癒", "白名單", "黑名單", "記憶體", "行程", "殺掉", "鎖定", "防篡改",
    ]

    HIGH_DIFFICULTY_MARKERS = [
        "架構設計", "大型重構", "深度分析", "多步驟", "全面審查", "安全審計", "系統設計",
        "演算法證明", "跨檔案重構", "完整專案", "論文", "研究報告", "complex", "refactor", "architecture", "benchmark"
    ]

    def classify_triage_fast(self, user_prompt: str, has_image: bool = False) -> Dict[str, Any]:
        """
        毫秒級意圖與難度預判（零延遲決定：1. 正常對話 vs 派任務、2. 本地模型 vs 雲端 API）
        """
        p = user_prompt.strip()
        p_lower = p.lower()

        needs_tools = any(k in p_lower for k in self.TASK_ACTION_MARKERS)
        is_pure_qa_or_snippet = (not needs_tools and not has_image)
        intent_mode = "CHAT" if is_pure_qa_or_snippet else "TASK"

        is_hard = (
            len(p) > 350
            or any(k in p_lower for k in self.HIGH_DIFFICULTY_MARKERS)
            or sum(1 for k in self.TASK_ACTION_MARKERS if k in p_lower) >= 6
        )
        difficulty = "CLOUD_API_REQUIRED" if is_hard else "LOCAL_CAPABLE"

        return {
            "intent_mode": intent_mode,
            "difficulty": difficulty,
        }

    async def decompose(
        self,
        user_prompt: str,
        context_state: Optional[Dict[str, Any]] = None,
        call_llm_fn: Optional[Callable] = None,
        model_full_id: Optional[str] = None,
        permission_notice: str = "",
    ) -> TaskPlan:
        """
        將使用者的自然語言提示詞交由大語言模型 (LLM) 進行語意判定 (CHAT / TASK) 與多步驟 TaskPlan 拆解；
        僅當無可用 LLM 或 API 呼叫失敗時，才平滑降級至本地規則／向量語意備援。
        """
        plan_id = f"plan_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._counter}"
        self._counter += 1

        # 1. 最優先：由大語言模型 (LLM) 進行深度語意判斷與任務拆解
        if call_llm_fn is not None:
            try:
                api_plan = await self._decompose_via_api(
                    plan_id=plan_id,
                    user_prompt=user_prompt,
                    context_state=context_state,
                    call_llm_fn=call_llm_fn,
                    model_full_id=model_full_id,
                    permission_notice=permission_notice,
                )
                if api_plan is not None:
                    return api_plan
            except Exception as e:
                # 記錄原因後降級至備援層
                self._log_decompose_error(e)

        # 2. 備援層（無 LLM 或 LLM 失敗時使用）
        fast_triage = self.classify_triage_fast(user_prompt)

        if fast_triage["intent_mode"] == "CHAT" and len(user_prompt.strip()) < 150:
            return TaskPlan(
                plan_id=plan_id,
                user_prompt=user_prompt,
                inferred_goal="一般對話與知識解答（免調用系統工具）",
                category="💬 一般對話與問答",
                subtasks=[],
                is_completed=True,
                source="FAST_TRIAGE",
                intent_mode="CHAT",
                difficulty=fast_triage["difficulty"],
                recommended_tools=[],
            )

        launch_target = extract_app_launch_target(user_prompt)
        if launch_target:
            plan = self._plan_app_launch_task(plan_id, user_prompt, launch_target)
            plan.difficulty = fast_triage["difficulty"]
            return plan

        if is_ai_tool_dispatch_request(user_prompt):
            plan = self._plan_ai_tool_dispatch_task(plan_id, user_prompt, context_state)
            plan.source = "RULE_AI_DISPATCH"
            plan.intent_mode = "TASK"
            plan.difficulty = fast_triage["difficulty"]
            return plan

        playbook_plan = self._plan_from_playbook(plan_id, user_prompt)
        if playbook_plan is not None:
            playbook_plan.difficulty = fast_triage["difficulty"]
            return playbook_plan

        if is_computer_use_request(user_prompt):
            plan = self._plan_computer_use_task(plan_id, user_prompt, context_state)
            plan.source = "RULE_COMPUTER_USE"
            plan.intent_mode = "TASK"
            plan.difficulty = fast_triage["difficulty"]
            return plan

        return await self._semantic_decompose(plan_id, user_prompt, context_state)

    async def _decompose_via_api(
        self,
        plan_id: str,
        user_prompt: str,
        context_state: Optional[Dict[str, Any]],
        call_llm_fn: Callable,
        model_full_id: Optional[str],
        permission_notice: str = "",
    ) -> Optional[TaskPlan]:
        """調用模型執行語意意圖識別、難度判定與任務工具拆分"""
        fg_title = (context_state or {}).get("foreground", {}).get("title", "未知名稱")
        mode_label = (context_state or {}).get("label", "正常工作模式")
        perm_block = f"\n\n{permission_notice.strip()}" if permission_notice and permission_notice.strip() else ""

        sys_prompt = f"""你是精通 Agent 意圖分流、任務難度評估與工具分配的決策專家。{perm_block}
請分析使用者的自然語言提示詞 (Prompt)，做出三個核心決策：
1. `intent_mode`: 判斷這是「一般對話/純知識問答/寫獨立範例代碼」(`"CHAT"`)，還是「需要操作電腦視窗/檔案/網路/系統工具的任務」(`"TASK"`)。
2. `difficulty`: 判斷任務難度：
   - `"LOCAL_CAPABLE"`: 日常對話、單一工具操作、一般腳本或中小型任務，本機 20B/12B 模型即可勝任。
   - `"CLOUD_API_REQUIRED"`: 跨多系統複雜重構、大型架構設計、長篇深度研究或高難度多步推理，需調用雲端旗艦 API (如 Gemini 2.5 Pro / GPT-4o / Claude)。
3. `recommended_tools` 與 `subtasks`:
   - 若 `intent_mode` 為 `"CHAT"`，`subtasks` 與 `recommended_tools` 請填寫空陣列 `[]`。
   - 若 `intent_mode` 為 `"TASK"`，請拆解為有邏輯順序的 `subtasks` 並精準指定每個步驟要用的 `allocated_tools`（涉及視窗優先選 `list_windows` + `inspect_accessibility_tree`；但若意圖是對 Antigravity/VS Code/Codex/Claude Code/Cursor 等 AI 編碼工具下提示詞，直接選 `dispatch_ai_coding_prompt`，不要先用 `inspect_accessibility_tree`/`ui_type` 慢慢找輸入框）。

【可用工具清單】：
{self.AVAILABLE_TOOLS_SUMMARY}

【嚴格輸出純 JSON 範例】：
{{
  "intent_mode": "TASK",
  "difficulty": "LOCAL_CAPABLE",
  "recommended_tools": ["list_windows", "inspect_accessibility_tree"],
  "goal": "精準提煉之總目標說明",
  "category": "🖥️ 桌面視窗與無障礙操作",
  "subtasks": [
    {{
      "step_id": 1,
      "title": "用一般人看得懂的白話寫，15 字內，不要用術語或工具名稱",
      "description": "具體動作說明",
      "intent_phase": "PERCEPTION",
      "allocated_tools": ["list_windows", "inspect_accessibility_tree"]
    }}
  ]
}}
"""

        user_content = f"【使用者提示詞】\n{user_prompt}\n\n【目前系統環境】\n前景視窗：{fg_title}\n當前模式：{mode_label}"

        res = await call_llm_fn(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_content},
            ],
            model_full_id=model_full_id,
            temperature=0.0,
            task_type="fast",
        )

        if not res.get("ok"):
            return None

        content = res.get("content", "").strip()
        # 清除 markdown codeblock
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        # 提取 JSON 物件
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return None
        data = json.loads(m.group(0))

        intent_mode = str(data.get("intent_mode") or "TASK").upper()
        if intent_mode not in ("CHAT", "TASK"):
            intent_mode = "TASK"
        difficulty = str(data.get("difficulty") or "LOCAL_CAPABLE").upper()
        if difficulty not in ("LOCAL_CAPABLE", "CLOUD_API_REQUIRED"):
            difficulty = "LOCAL_CAPABLE"
        recommended_tools = [str(t) for t in (data.get("recommended_tools") or [])]

        goal = str(data.get("goal") or user_prompt)
        category = str(data.get("category") or ("💬 一般對話與問答" if intent_mode == "CHAT" else "⚡ 通用自主任務"))
        raw_subtasks = data.get("subtasks") or []

        if intent_mode == "CHAT":
            return TaskPlan(
                plan_id=plan_id,
                user_prompt=user_prompt,
                inferred_goal=goal,
                category=category,
                subtasks=[],
                is_completed=True,
                source="LLM_API",
                intent_mode="CHAT",
                difficulty=difficulty,
                recommended_tools=[],
            )

        subtasks: List[SubTask] = []
        for idx, item in enumerate(raw_subtasks, start=1):
            s_id = int(item.get("step_id", idx))
            s_title = str(item.get("title") or f"步驟 {s_id}")
            s_desc = str(item.get("description") or "")
            s_phase = str(item.get("intent_phase", "EXECUTION")).upper()
            if s_phase not in ("PERCEPTION", "EXECUTION", "VERIFICATION", "SYNTHESIS"):
                s_phase = "EXECUTION"
            s_tools = [str(t) for t in (item.get("allocated_tools") or [])]
            for rt in s_tools:
                if rt not in recommended_tools:
                    recommended_tools.append(rt)
            subtasks.append(SubTask(
                step_id=s_id,
                title=s_title,
                description=s_desc,
                intent_phase=s_phase,
                allocated_tools=s_tools,
            ))

        if not subtasks:
            return None

        return TaskPlan(
            plan_id=plan_id,
            user_prompt=user_prompt,
            inferred_goal=goal,
            category=category,
            subtasks=subtasks,
            source="LLM_API",
            intent_mode="TASK",
            difficulty=difficulty,
            recommended_tools=recommended_tools,
        )

    def _log_decompose_error(self, err: Exception) -> None:
        """意圖判別降級時留下痕跡（不讓 LLM 失敗被靜默吞掉）。"""
        try:
            print(f"[task_orchestrator] 意圖判別降級至語意向量：{type(err).__name__}: {err}",
                  flush=True)
        except Exception:
            pass

    # 意圖類別 -> 對應的任務規劃建構器（與 semantic_intent.INTENT_PROTOTYPES 類別一致）
    def _semantic_builder_map(self):
        return {
            "SECURITY": self._plan_security_audit_task,
            "GOOGLE": self._plan_google_workspace_task,
            "DESKTOP": self._plan_desktop_ui_task,
            "AI_DISPATCH": self._plan_ai_tool_dispatch_task,
            "CODE": self._plan_code_dev_task,
            "WEB": self._plan_web_research_task,
        }

    async def _semantic_decompose(self, plan_id: str, user_prompt: str,
                                  context_state: Optional[Dict[str, Any]]) -> TaskPlan:
        """最差情況的意圖判別：用『向量語意相似度』取代關鍵字 NLU。
        - 嵌入可用且信心足夠 => 路由到對應任務規劃。
        - 嵌入不可用 / 信心不足 / 判為一般對話 => 安全退回『一般任務』，
          絕不因為出現『安全 / 記憶體 / 威脅』等日常字就自動掃毒。"""
        label, score = None, 0.0
        try:
            try:
                from . import semantic_intent          # 套件內相對匯入
            except Exception:
                import semantic_intent                 # 直接以模組名匯入（相容不同載入方式）
            label, score = await semantic_intent.classify(user_prompt)
        except Exception as e:
            self._log_decompose_error(e)
            label, score = None, 0.0

        builder = self._semantic_builder_map().get(label)
        if builder is None:
            # CHAT / None（嵌入不可用或信心不足）=> 一般任務，不觸發任何資安掃描
            plan = self._plan_general_task(plan_id, user_prompt, context_state)
        else:
            plan = builder(plan_id, user_prompt, context_state)

        triage = self.classify_triage_fast(user_prompt)
        plan.source = "SEMANTIC_VECTOR"
        plan.intent_mode = "TASK"
        plan.difficulty = triage["difficulty"]
        return plan

    def _heuristic_decompose(self, plan_id: str, user_prompt: str, context_state: Optional[Dict[str, Any]]) -> TaskPlan:
        """啟發式本地規則降級備援"""
        p = user_prompt.strip().lower()
        triage = self.classify_triage_fast(user_prompt)

        if triage["intent_mode"] == "CHAT":
            return TaskPlan(
                plan_id=plan_id,
                user_prompt=user_prompt,
                inferred_goal="一般對話與知識解答（免調用系統工具）",
                category="💬 一般對話與問答",
                subtasks=[],
                is_completed=True,
                source="HEURISTIC_FALLBACK",
                intent_mode="CHAT",
                difficulty=triage["difficulty"],
                recommended_tools=[],
            )

        if is_computer_use_request(user_prompt):
            plan = self._plan_computer_use_task(plan_id, user_prompt, context_state)
        elif (
            any(kw in p for kw in ["antigravity", "vscode", "vs code", "codex", "claude code", "cursor", "claude"])
            and any(kw in p for kw in _AI_DISPATCH_ACTION_KEYWORDS)
        ):
            plan = self._plan_ai_tool_dispatch_task(plan_id, user_prompt, context_state)
        elif any(kw in p for kw in [
            "掃毒", "病毒", "木馬", "惡意", "安全", "防火牆", "自癒", "cpr", "入侵",
            "白名單", "黑名單", "記憶體", "殺掉進程", "殺毒", "威脅"
        ]):
            # 註：「行程」原本也在此清單中，但它在中文裡同時是「日曆行程」(schedule) 與
            # 「進程/process」兩種意思，跟下面 Google Workspace 分支的日曆意圖衝突，
            # 導致「看我日曆的行程」被誤判成資安掃描，所以移除，改用更明確的「殺掉進程」。
            plan = self._plan_security_audit_task(plan_id, user_prompt, context_state)
        elif any(kw in p for kw in [
            "信箱", "gmail", "郵件", "寄信", "雲端硬碟", "gdrive", "日曆", "日歷", "行事曆", "行程",
            "calendar", "試算表", "gsheet", "google文件", "gdocs", "工作習慣"
        ]):
            plan = self._plan_google_workspace_task(plan_id, user_prompt, context_state)
        elif any(kw in p for kw in [
            "看畫面", "螢幕", "視窗", "桌面", "點擊", "按鈕", "打字", "輸入", "操作", "點選",
            "查看軟體", "看現在", "看目前", "報錯是什麼", "uia", "無障礙", "介面", "控制項"
        ]):
            plan = self._plan_desktop_ui_task(plan_id, user_prompt, context_state)
        elif any(kw in p for kw in [
            "修復", "報錯", "bug", "代碼", "程式", "整理檔案", "檔案", "目錄", "資料夾",
            "test", "pytest", "git", "執行指令", "建置", "編譯", "讀取檔案"
        ]):
            plan = self._plan_code_dev_task(plan_id, user_prompt, context_state)
        elif any(kw in p for kw in [
            "搜尋", "最新", "找資料", "網頁", "網址", "瀏覽器", "google", "search",
            "新聞", "文件", "api文件", "官網", "查一下", "查詢", "查查"
        ]):
            plan = self._plan_web_research_task(plan_id, user_prompt, context_state)
        else:
            plan = self._plan_general_task(plan_id, user_prompt, context_state)

        plan.source = "HEURISTIC_FALLBACK"
        plan.intent_mode = "TASK"
        plan.difficulty = triage["difficulty"]
        return plan

    def _plan_from_playbook(self, plan_id: str, prompt: str) -> Optional[TaskPlan]:
        try:
            from . import app_playbooks
        except Exception:
            return None
        app = app_playbooks.find_app(prompt)
        task = app_playbooks.match_task(app, prompt) if app else None
        if not task:
            return None
        pb = app_playbooks.PLAYBOOKS[app]
        subtasks = []
        for i, step in enumerate(task["steps"], 1):
            tools = re.findall(r"`([a-z_]+)`", step)
            subtasks.append(SubTask(
                step_id=i,
                title=re.sub(r"`", "", step.split("：")[0])[:40],
                description=step,
                intent_phase="EXECUTION",
                allocated_tools=tools,
            ))
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"{pb['name']}：{task['title']}",
            category=f"🧰 依操作手冊執行（{pb['name']}）",
            subtasks=subtasks,
            source="RULE_APP_PLAYBOOK",
            intent_mode="TASK",
        )

    def _plan_app_launch_task(self, plan_id: str, prompt: str, target: str) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"開啟本機軟體「{target}」",
            category="🚀 開啟本機軟體",
            subtasks=[
                SubTask(
                    step_id=1,
                    title=f"在這台電腦找「{target}」",
                    description=f"用 list_installed_software（query=\"{target}\"）查本機安裝的版本",
                    intent_phase="DISCOVERY",
                    allocated_tools=["list_installed_software"],
                ),
                SubTask(
                    step_id=2,
                    title="開啟它",
                    description="用 launch_application 開啟查到的軟體（不在允許清單內會先請使用者同意）",
                    intent_phase="EXECUTION",
                    allocated_tools=["launch_application"],
                ),
            ],
            source="RULE_APP_LAUNCH",
            intent_mode="TASK",
            launch_target=target,
        )

    def _plan_ai_tool_dispatch_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"自動對本機已開啟的 AI 編碼工具視窗派送提示詞 ({prompt[:30]})",
            category="🤖 AI 編碼工具提示詞派送",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="把提示詞送進指定的 AI 工具視窗",
                    description="判斷使用者指名的工具（antigravity|vscode|codex|claude_code|cursor），直接呼叫 dispatch_ai_coding_prompt 送出提示詞，不要先用 inspect_accessibility_tree 慢慢找輸入框",
                    intent_phase="EXECUTION",
                    allocated_tools=["dispatch_ai_coding_prompt"],
                ),
                SubTask(
                    step_id=2,
                    title="確認有沒有送出成功",
                    description="檢查 dispatch_ai_coding_prompt 回傳的 ok / matched_window / response_snapshot，整合成果總結；若找不到視窗則明確告知使用者該工具未開啟",
                    intent_phase="SYNTHESIS",
                    allocated_tools=["dispatch_ai_coding_prompt"],
                ),
            ]
        )

    def _plan_computer_use_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"模仿使用者用滑鼠鍵盤操作電腦 ({prompt[:30]})",
            category="🖱️ 模仿使用者操控電腦",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="先看清楚畫面",
                    description="用 list_windows / inspect_accessibility_tree 了解視窗；自繪畫面或看不懂時用 capture_desktop_screen 取得附座標格線的截圖",
                    intent_phase="PERCEPTION",
                    allocated_tools=["list_windows", "inspect_accessibility_tree", "capture_desktop_screen"],
                ),
                SubTask(
                    step_id=2,
                    title="一步一步用滑鼠鍵盤操作",
                    description="一次一個動作：ui_invoke / ui_type 或 click_screen、type_text、computer_key、computer_scroll、computer_drag；"
                                "要開軟體用 launch_application（需使用者核准）。沒有指定目標時做無害示範：開記事本輸入一行「Syntra 操控測試成功」",
                    intent_phase="EXECUTION",
                    allocated_tools=["launch_application", "click_screen", "type_text", "computer_key", "computer_scroll",
                                     "computer_drag", "ui_invoke", "ui_type"],
                ),
                SubTask(
                    step_id=3,
                    title="截圖確認並回報",
                    description="每個動作後重新截圖或讀結構樹確認畫面有變化，最後列出做了哪些步驟與結果",
                    intent_phase="SYNTHESIS",
                    allocated_tools=["capture_desktop_screen", "inspect_accessibility_tree"],
                ),
            ]
        )

    def _plan_desktop_ui_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"自主感知目標視窗狀態並透過無障礙模式執行操作 ({prompt[:30]})",
            category="🖥️ 桌面視窗與無障礙操作",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="找到要操作的視窗",
                    description="自主調用 list_windows 列出桌面視窗，並以 inspect_accessibility_tree 提取控制項結構與純文字",
                    intent_phase="PERCEPTION",
                    allocated_tools=["list_windows", "inspect_accessibility_tree"],
                ),
                SubTask(
                    step_id=2,
                    title="在視窗裡點按鈕或打字",
                    description="透過 ui_invoke 原生觸發按鈕或 ui_type 填寫文字（非必要不使用盲點截圖）",
                    intent_phase="EXECUTION",
                    allocated_tools=["ui_invoke", "ui_type", "ui_click"],
                ),
                SubTask(
                    step_id=3,
                    title="確認結果並回報",
                    description="確認視窗反應、控制項數值變化，直接給出成果總結",
                    intent_phase="SYNTHESIS",
                    allocated_tools=["inspect_accessibility_tree", "ui_read_text"],
                ),
            ]
        )

    def _plan_code_dev_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"代碼檢視、背景執行驗證與問題修復 ({prompt[:30]})",
            category="💻 程式開發與環境維護",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="查看專案檔案與目前狀態",
                    description="使用 run_background_shell 檢查專案目錄、Git 狀態或錯誤日誌",
                    intent_phase="PERCEPTION",
                    allocated_tools=["run_background_shell"],
                ),
                SubTask(
                    step_id=2,
                    title="找出問題並修改程式",
                    description="透過背景指令或專用腳本處理檔案變更、執行修正",
                    intent_phase="EXECUTION",
                    allocated_tools=["run_background_shell", "send_ide_feedback"],
                ),
                SubTask(
                    step_id=3,
                    title="跑測試確認沒壞掉",
                    description="於背景執行測試確保零報錯，回報完整修正總結與代碼差異",
                    intent_phase="VERIFICATION",
                    allocated_tools=["run_background_shell"],
                ),
            ]
        )

    def _plan_web_research_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"自主聯網資料搜尋與結構化內容提煉 ({prompt[:30]})",
            category="🌐 聯網搜尋與情報分析",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="上網搜尋",
                    description="調用 web_search 搜尋權威來源，系統自動發布連網透明度通報",
                    intent_phase="PERCEPTION",
                    allocated_tools=["web_search"],
                ),
                SubTask(
                    step_id=2,
                    title="打開找到的網頁讀內容",
                    description="調用 web_fetch 或 browser_navigate 提取網頁細節數據",
                    intent_phase="EXECUTION",
                    allocated_tools=["web_fetch", "browser_extract"],
                ),
                SubTask(
                    step_id=3,
                    title="整理重點給你",
                    description="提煉具體技術結論與來源出處，回報給使用者",
                    intent_phase="SYNTHESIS",
                    allocated_tools=[],
                ),
            ]
        )

    def _plan_google_workspace_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"Google Workspace 雲端辦公與習慣排程處理 ({prompt[:30]})",
            category="☁️ Google Workspace 雲端協作",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="查看 Google 信箱／雲端硬碟／行事曆",
                    description="自主調用 gmail_list_messages, gdrive_search_files 或 gcalendar_list_events 探測目標",
                    intent_phase="PERCEPTION",
                    allocated_tools=["gmail_list_messages", "gdrive_search_files", "gcalendar_list_events"],
                ),
                SubTask(
                    step_id=2,
                    title="寄信、建檔或修改資料",
                    description="調用對應的 Gmail, Drive, Docs, Sheets 專屬工具完成操作",
                    intent_phase="EXECUTION",
                    allocated_tools=["gmail_send_message", "gdrive_upload_file", "gsheets_action", "gdocs_create_or_append"],
                ),
                SubTask(
                    step_id=3,
                    title="確認完成並附上連結",
                    description="整合建立的資源 ID 與狀態，給予使用者確認回覆",
                    intent_phase="SYNTHESIS",
                    allocated_tools=[],
                ),
            ]
        )

    def _plan_security_audit_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=f"系統資安威脅掃描、防篡改排查與自主修復 ({prompt[:30]})",
            category="🛡️ 系統防禦與資安巡檢",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="掃描電腦有沒有可疑程式",
                    description="調用 audit_system_security, scan_memory_injections 或 scan_antivirus 探測威脅",
                    intent_phase="PERCEPTION",
                    allocated_tools=["audit_system_security", "scan_memory_injections", "scan_antivirus"],
                ),
                SubTask(
                    step_id=2,
                    title="處理可疑程式並加強保護",
                    description="對發現的風險執行 kill_threat_process 或 lock_file_anti_tamper",
                    intent_phase="EXECUTION",
                    allocated_tools=["kill_threat_process", "threat_hunter_annihilate", "lock_file_anti_tamper"],
                ),
                SubTask(
                    step_id=3,
                    title="給你一份安全檢查報告",
                    description="總結系統健康狀況、白名單規則與處置日誌",
                    intent_phase="SYNTHESIS",
                    allocated_tools=["get_network_defense_status"],
                ),
            ]
        )

    def _plan_general_task(self, plan_id: str, prompt: str, ctx: Optional[Dict[str, Any]]) -> TaskPlan:
        return TaskPlan(
            plan_id=plan_id,
            user_prompt=prompt,
            inferred_goal=prompt[:40] if len(prompt) > 40 else prompt,
            category="⚡ 通用自主執行計畫",
            subtasks=[
                SubTask(
                    step_id=1,
                    title="先了解目前電腦狀況",
                    description="根據使用者提示詞自動探測相關系統環境、視窗或檔案",
                    intent_phase="PERCEPTION",
                    allocated_tools=["inspect_accessibility_tree", "run_background_shell", "list_windows"],
                ),
                SubTask(
                    step_id=2,
                    title="動手完成你要的事",
                    description="依據探測結果發起對應的工具呼叫與連鎖推進",
                    intent_phase="EXECUTION",
                    allocated_tools=[],
                ),
                SubTask(
                    step_id=3,
                    title="確認結果並回報",
                    description="驗證任務產出品質，直接給出清晰具體的解答或程式碼",
                    intent_phase="SYNTHESIS",
                    allocated_tools=[],
                ),
            ]
        )
