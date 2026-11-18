# -*- coding: utf-8 -*-
"""
core/tool_labels.py
===================
把工具呼叫（工具名稱 + 參數）轉成使用者看得懂的白話描述，供聊天室步驟列顯示用。
未知工具一律退回「使用工具：<名稱>」，不會丟例外。
"""
from typing import Any, Dict

# 工具名稱 -> 白話動作
TOOL_ACTIONS: Dict[str, str] = {
    "list_windows": "查看目前開著哪些視窗",
    "inspect_accessibility_tree": "讀取視窗裡有哪些按鈕和欄位",
    "ui_invoke": "按下按鈕",
    "ui_type": "在欄位裡打字",
    "ui_click": "點擊畫面上的項目",
    "ui_read_text": "讀取視窗裡的文字",
    "inspect_window_background": "看一下視窗畫面",
    "capture_desktop_screen": "截圖看整個螢幕",
    "ocr_screen": "辨識螢幕上的文字",
    "click_screen": "用滑鼠點擊螢幕",
    "type_text": "用鍵盤打字",
    "send_ide_feedback": "把訊息送到編輯器",
    "dispatch_ai_coding_prompt": "把提示詞送進 AI 工具",
    "app_howto": "查這個軟體的操作手冊",
    "learn_app_ui": "自動探索軟體的選單與按鈕",
    "write_text_file": "建立或寫入檔案（會先問你同意）",
    "open_file_in_app": "用指定軟體開啟檔案",
    "read_app_help": "讀這個軟體的說明文件",
    "research_app_howto": "上網查這個軟體的操作方法",
    "save_app_knowledge": "把學到的操作方法記下來",
    "type_in_app": "在軟體視窗裡輸入文字",
    "list_installed_software": "查看電腦裡安裝了哪些軟體",
    "launch_application": "開啟一個軟體（會先問你同意）",
    "run_background_shell": "在背景執行指令",
    "run_linux_shell": "執行 Linux 指令",
    "sandbox_execute": "在沙盒裡執行指令",
    "web_search": "上網搜尋",
    "web_fetch": "讀取網頁內容",
    "browser_navigate": "用瀏覽器打開網頁",
    "browser_screenshot": "擷取網頁畫面",
    "browser_extract": "讀取網頁上的文字和連結",
    "browser_click": "點擊網頁上的項目",
    "browser_type": "在網頁欄位裡打字",
    "browser_close": "關閉瀏覽器",
    "search_local_files": "搜尋電腦裡的檔案",
    "read_local_file": "讀取檔案內容",
    "notify_discord": "發送 Discord 通知",
    "cdr_sanitize_file": "清理檔案中的可疑內容",
    "scan_antivirus": "掃描病毒",
    "audit_system_security": "檢查系統安全設定",
    "kill_threat_process": "關閉可疑程式",
    "lock_file_anti_tamper": "鎖定檔案防止被修改",
    "configure_api_provider": "設定 AI 服務連線",
    "install_skill": "安裝技能",
    "run_skill_script": "執行技能腳本",
    "list_installed_skills": "查看已安裝的技能",
    "gmail_list_messages": "查看 Gmail 信件",
    "gmail_send_message": "寄出 Gmail",
    "gdrive_search_files": "搜尋 Google 雲端硬碟",
    "gdrive_upload_file": "上傳到 Google 雲端硬碟",
    "gdocs_create_or_append": "編輯 Google 文件",
    "gsheets_action": "編輯 Google 試算表",
    "gcalendar_list_events": "查看 Google 行事曆",
    "syntax_error": "工具呼叫格式有誤",
}

# AI 編碼工具代號 -> 顯示名稱
_AI_TOOL_NAMES = {
    "claude_code": "Claude Code",
    "claude": "Claude",
    "vscode": "VS Code",
    "codex": "Codex",
    "cursor": "Cursor",
    "antigravity": "Antigravity",
}

# 依序挑第一個有值的參數當作補充說明
_DETAIL_KEYS = (
    "prompt_text", "text", "query", "url", "command", "target_path", "file_path",
    "path", "question", "selector_or_text", "target_label", "message", "skill_name", "target",
)


def _short(value: Any, limit: int = 40) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def describe_tool_call(tool: str, args: Any) -> Dict[str, str]:
    """回傳 {"action": 白話動作, "detail": 補充說明（可能為空字串）}"""
    tool = str(tool or "")
    action = TOOL_ACTIONS.get(tool) or f"使用工具：{tool or '未知'}"
    if not isinstance(args, dict):
        return {"action": action, "detail": ""}

    if tool == "dispatch_ai_coding_prompt":
        hint = str(args.get("tool_hint") or "").strip().lower()
        name = _AI_TOOL_NAMES.get(hint, hint or "AI 工具")
        action = f"把提示詞送進 {name}"

    detail = ""
    for key in _DETAIL_KEYS:
        val = args.get(key)
        if val not in (None, "", [], {}):
            detail = f"「{_short(val)}」"
            break
    return {"action": action, "detail": detail}
