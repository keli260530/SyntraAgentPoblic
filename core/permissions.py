# -*- coding: utf-8 -*-
"""
權限與功能開關（設定 → 🔐 權限與功能）

三類設定都存在 settings.json 的 "permissions" 底下：
- google_scopes：要向 Google 要求哪些權限（Gmail 讀信、寄信、雲端硬碟…），登入時只要求勾選的項目。
- agent：AI 代理每一類操作的權限 —— allow（直接執行）/ ask（每次先問你）/ deny（禁止）。
- features：防護功能開關（父項關閉時底下子項一律視為關閉）。背景監控類需重新啟動 Syntra 才生效。

這裡只放「目錄」與純邏輯判斷，不依賴 PyQt，方便測試。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

ALLOW, ASK, DENY = "allow", "ask", "deny"
POLICY_LABELS = {ALLOW: "允許", ASK: "每次詢問", DENY: "禁止"}

# ---------------------------------------------------------------------------
# Google 權限範圍：(key, 顯示名稱, 說明, scope, 需要此權限的工具)
# ---------------------------------------------------------------------------
GOOGLE_SCOPE_OPTIONS: List[Tuple[str, str, str, str, Tuple[str, ...]]] = [
    ("gmail_read", "Gmail：讀取郵件", "查看收件匣、讀取郵件內容",
     "https://www.googleapis.com/auth/gmail.readonly", ("gmail_list_messages", "gmail_read_message")),
    ("gmail_send", "Gmail：寄送郵件", "以你的名義寄出郵件",
     "https://www.googleapis.com/auth/gmail.send", ("gmail_send_message",)),
    ("drive_file", "雲端硬碟：上傳／管理 Syntra 建立的檔案", "只能存取由 Syntra 建立或你指定的檔案",
     "https://www.googleapis.com/auth/drive.file", ("gdrive_upload_file",)),
    ("drive_read", "雲端硬碟：搜尋與讀取所有檔案", "唯讀存取你整個雲端硬碟",
     "https://www.googleapis.com/auth/drive.readonly", ("gdrive_search_files",)),
    ("calendar", "Google 日曆：查看與建立活動", "讀取、新增、修改你的行事曆活動",
     "https://www.googleapis.com/auth/calendar.events", ("gcalendar_list_events", "gcalendar_create_event")),
    ("docs", "Google 文件：建立與編輯", "建立文件或在文件末尾新增內容",
     "https://www.googleapis.com/auth/documents", ("gdocs_create_or_append",)),
    ("sheets", "Google 試算表：讀取與編輯", "讀寫你的試算表",
     "https://www.googleapis.com/auth/spreadsheets", ("gsheets_action",)),
]

# ---------------------------------------------------------------------------
# AI 代理操作權限：(key, 顯示名稱, 說明, 預設, 涵蓋的工具)
# ---------------------------------------------------------------------------
AGENT_PERMISSION_CATEGORIES: List[Tuple[str, str, str, str, Tuple[str, ...]]] = [
    ("shell", "執行指令與程式", "在終端機、Linux 環境或技能腳本中執行指令（破壞性指令仍會依執行模式另外詢問）", ALLOW,
     ("run_background_shell", "run_linux_shell", "run_skill_script")),
    ("desktop_control", "控制滑鼠、鍵盤與視窗", "點擊、輸入文字、操作視窗元件、開啟軟體", ALLOW,
     ("click_screen", "type_text", "ui_invoke", "ui_type", "ui_click", "launch_application", "send_ide_feedback")),
    ("screen_read", "讀取螢幕與視窗內容", "截圖、讀取視窗文字與介面結構", ALLOW,
     ("capture_desktop_screen", "inspect_window_background", "inspect_accessibility_tree", "list_windows",
      "ui_read_text")),
    ("browser", "瀏覽器自動化", "開啟網頁、點擊、輸入、擷取內容", ALLOW,
     ("browser_navigate", "browser_screenshot", "browser_extract", "browser_click", "browser_type", "browser_close")),
    ("web", "網路搜尋與讀取網頁", "搜尋網路、下載網頁內容", ASK, ("web_search", "web_fetch")),
    ("google_read", "讀取 Google 資料", "讀郵件、搜尋雲端硬碟、查看日曆", ALLOW,
     ("gmail_list_messages", "gmail_read_message", "gdrive_search_files", "gcalendar_list_events",
      "google_open_service", "sync_user_habits")),
    ("google_write", "寄信與修改 Google 資料", "寄出郵件、上傳檔案、建立活動、編輯文件或試算表", ASK,
     ("gmail_send_message", "gdrive_upload_file", "gcalendar_create_event", "gdocs_create_or_append", "gsheets_action")),
    ("outbound", "對外傳送訊息", "傳 Discord 通知、把提示詞送給其他 AI 編碼工具", ALLOW,
     ("notify_discord", "dispatch_ai_coding_prompt")),
    ("system_config", "安裝技能與修改設定", "安裝新技能、新增或修改 AI 服務的 API 設定、加入網域白名單", ASK,
     ("install_skill", "configure_api_provider", "add_domain_whitelist")),
    ("active_defense", "主動防禦動作", "結束可疑程式、封鎖 IP、隔離或粉碎檔案、反擊、系統急救、鎖定檔案", ASK,
     ("kill_threat_process", "block_malicious_ip", "threat_hunter_annihilate", "counter_strike_retaliate",
      "execute_os_cpr", "lock_file_anti_tamper", "unlock_file_anti_tamper", "self_heal_files",
      "ai_predict_and_patch_vulnerability", "citadel_backup_data")),
]

# ---------------------------------------------------------------------------
# 防護功能：(父 key, 名稱, 說明, [(子 key, 名稱, 說明, 需要此功能的工具)])
# ---------------------------------------------------------------------------
FEATURE_TREE: List[Tuple[str, str, str, List[Tuple[str, str, str, Tuple[str, ...]]]]] = [
    ("antivirus", "防毒與即時防護", "關閉後底下所有防毒功能都會停用", [
        ("realtime_sentinel", "即時主動防禦哨兵", "背景持續監控可疑程式行為", ()),
        ("ransomware_canary", "勒索軟體誘餌檔", "放置誘餌檔，被加密時立即警示", ()),
        ("memory_injection", "記憶體注入偵測", "偵測無檔案、反射式注入攻擊", ("scan_memory_injections",)),
        ("storm_shield", "大量病毒湧入減壓閥", "短時間大量威脅時批次處理", ()),
        ("sandbox", "沙箱隔離執行", "在隔離環境執行可疑程式或程式碼", ("sandbox_execute",)),
        ("cdr", "檔案消毒（CDR）", "移除文件中的巨集與主動內容", ("cdr_sanitize_file",)),
        ("manual_scan", "手動病毒掃描", "讓 AI 依你的要求掃描檔案或資料夾", ("scan_antivirus", "scan_byovd_and_early_boot")),
    ]),
    ("self_protection", "系統自我保護", "保護 Syntra 本身不被關閉或接管", [
        ("anti_takeover", "防遠端接管", "偵測遠端桌面、控制權被搶奪", ()),
        ("symbiotic_mesh", "多節點共生守護", "多個守護程序互相監控、被關閉時自動重啟", ()),
    ]),
]

# ---------------------------------------------------------------------------
# AI 可使用的應用程式（允許清單）
# 不在清單內的程式，AI 要開啟、讀取或操作它之前一律先跳出「允許請求」。
# ---------------------------------------------------------------------------
# key: (顯示名稱, 比對關鍵字)。關鍵字會和 exe 檔名、視窗程式名稱或 AI 給的名稱做「包含」比對。
KNOWN_APPS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "chrome": ("Google Chrome（Google 服務）", ("chrome", "google")),
    "msedge": ("Microsoft Edge", ("msedge", "edge")),
    "firefox": ("Firefox", ("firefox",)),
    "code": ("Visual Studio Code", ("vscode", "visual studio code", "code")),
    "antigravity": ("Antigravity", ("antigravity",)),
    "cursor": ("Cursor", ("cursor",)),
    "codex": ("Codex CLI", ("codex",)),
    "claude_code": ("Claude Code", ("claude",)),
    "windowsterminal": ("Windows 終端機", ("windowsterminal", "wt", "terminal", "powershell", "cmd")),
    "notepad": ("記事本", ("notepad", "記事本")),
    "explorer": ("檔案總管", ("explorer", "檔案總管")),
    "winword": ("Microsoft Word", ("winword", "word")),
    "excel": ("Microsoft Excel", ("excel",)),
    "powerpnt": ("Microsoft PowerPoint", ("powerpnt", "powerpoint")),
    "outlook": ("Microsoft Outlook", ("outlook",)),
    "line": ("LINE", ("line",)),
    "discord": ("Discord", ("discord",)),
    "teams": ("Microsoft Teams", ("teams", "ms-teams")),
}
DEFAULT_ALLOWED_APPS: List[Dict[str, str]] = [{"key": "chrome", "name": KNOWN_APPS["chrome"][0]}]
# Syntra 自己的視窗永遠可以操作
_SELF_APPS = {"python", "pythonw", "syntra"}

# 會「使用某個應用程式」的工具
APP_TOOLS = {"launch_application", "dispatch_ai_coding_prompt", "inspect_accessibility_tree", "send_ide_feedback",
             "inspect_window_background", "ui_invoke", "ui_type", "ui_click", "ui_read_text",
             "click_screen", "type_text"}


def identify_app(name: str) -> Tuple[str, str]:
    """把 exe 路徑、程式名稱或 tool_hint 轉成 (key, 顯示名稱)。"""
    raw = (name or "").strip().strip('"')
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base[:-4] if base.lower().endswith((".exe", ".lnk")) else base
    low = stem.lower().replace("_", " ").strip()
    if not low:
        return "", ""
    for key, (display, words) in KNOWN_APPS.items():
        if low == key.replace("_", " ") or any(
                (w == low) if len(w) <= 4 else (w in low) for w in words):
            return key, display
    return low, stem


def allowed_apps(settings: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    apps = _section(settings, "apps").get("allowed")
    if not isinstance(apps, list):
        return [dict(a) for a in DEFAULT_ALLOWED_APPS]
    return [a for a in apps if isinstance(a, dict) and a.get("key")]


def is_app_allowed(settings: Optional[Dict[str, Any]], key: str) -> bool:
    if not key or key in _SELF_APPS:
        return True
    return any(a.get("key") == key for a in allowed_apps(settings))


def with_app_allowed(settings: Optional[Dict[str, Any]], key: str, name: str) -> List[Dict[str, str]]:
    """回傳加入此程式後的新允許清單（不修改傳入的 settings）。"""
    apps = allowed_apps(settings)
    if key and not any(a.get("key") == key for a in apps):
        apps.append({"key": key, "name": name or key})
    return apps


def describe_app_action(tool_name: str, args: Dict[str, Any], app_name: str) -> str:
    """把工具呼叫翻成一句使用者看得懂的「要做什麼」。"""
    def clip(v: Any, n: int = 120) -> str:
        s = str(v or "").strip().replace("\n", " ")
        return s if len(s) <= n else s[:n] + "…"

    a = args or {}
    if tool_name == "launch_application":
        return f"開啟「{app_name}」"
    if tool_name == "dispatch_ai_coding_prompt":
        return f"在「{app_name}」的對話框貼上並送出這段提示詞：{clip(a.get('prompt_text'))}"
    if tool_name in ("inspect_accessibility_tree", "inspect_window_background", "ui_read_text"):
        return f"讀取「{app_name}」視窗上的文字與按鈕位置"
    if tool_name == "send_ide_feedback":
        return f"在「{app_name}」貼上並送出這段訊息：{clip(a.get('feedback_text'))}"
    if tool_name in ("ui_type", "type_text"):
        target = a.get("target_label") or a.get("element_id") or "目前的輸入框"
        return f"在「{app_name}」的「{clip(target, 40)}」輸入：{clip(a.get('text'))}"
    if tool_name in ("ui_invoke", "ui_click", "click_screen"):
        target = a.get("target_label") or a.get("element_id") or f"座標 ({a.get('x')}, {a.get('y')})"
        return f"在「{app_name}」點擊「{clip(target, 60)}」"
    return f"使用「{app_name}」執行 {tool_name}"


_GOOGLE_TOOL_SCOPE = {tool: key for key, _l, _d, _s, tools in GOOGLE_SCOPE_OPTIONS for tool in tools}
_TOOL_CATEGORY = {tool: key for key, _l, _d, _p, tools in AGENT_PERMISSION_CATEGORIES for tool in tools}
_TOOL_FEATURE = {tool: (parent, key) for parent, _l, _d, kids in FEATURE_TREE
                 for key, _kl, _kd, tools in kids for tool in tools}
_CATEGORY_LABEL = {key: label for key, label, _d, _p, _t in AGENT_PERMISSION_CATEGORIES}


# ---------------------------------------------------------------------------
# 批准視窗用的白話說明：把「工具名稱＋參數」翻成一般人看得懂的一句話
# ---------------------------------------------------------------------------
def _short(v: Any, n: int = 60) -> str:
    s = str(v if v is not None else "").strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


_RISKY_CATEGORIES = {"shell", "google_write", "system_config", "active_defense", "outbound"}

_PLAIN_ACTIONS = {
    "capture_desktop_screen": lambda a: "擷取你目前的螢幕畫面",
    "inspect_window_background": lambda a: "讀取某個視窗裡的文字內容",
    "inspect_accessibility_tree": lambda a: "讀取某個視窗上的按鈕與文字",
    "ui_read_text": lambda a: "讀取視窗上的文字",
    "list_windows": lambda a: "查看你目前開著哪些視窗",
    "list_installed_software": lambda a: "查看電腦上安裝了哪些軟體"
                                         + (f"（找「{_short(a.get('query'), 30)}」）" if a.get("query") else ""),
    "click_screen": lambda a: "在螢幕上點一下滑鼠",
    "type_text": lambda a: f"幫你打字：「{_short(a.get('text'), 40)}」",
    "ui_click": lambda a: "點擊視窗上的按鈕",
    "ui_invoke": lambda a: "按下視窗上的按鈕",
    "ui_type": lambda a: f"在視窗輸入框打字：「{_short(a.get('text'), 40)}」",
    "launch_application": lambda a: f"開啟軟體「{_short(a.get('target'), 40)}」",
    "send_ide_feedback": lambda a: "把訊息送到你的程式編輯器",
    "run_background_shell": lambda a: f"在電腦上執行一段指令：{_short(a.get('command'), 80)}",
    "run_linux_shell": lambda a: f"在 Linux 環境執行指令：{_short(a.get('command'), 80)}",
    "run_skill_script": lambda a: "執行技能附帶的腳本",
    "browser_navigate": lambda a: f"用瀏覽器開啟網頁 {_short(a.get('url'), 60)}",
    "browser_click": lambda a: "在網頁上點擊",
    "browser_type": lambda a: "在網頁上輸入文字",
    "browser_screenshot": lambda a: "擷取網頁畫面",
    "browser_extract": lambda a: "讀取網頁內容",
    "web_search": lambda a: f"上網搜尋「{_short(a.get('query'), 40)}」",
    "web_fetch": lambda a: f"讀取網頁 {_short(a.get('url'), 60)}",
    "gmail_list_messages": lambda a: "查看你的 Gmail 郵件清單",
    "gmail_read_message": lambda a: "閱讀一封 Gmail 郵件",
    "gmail_send_message": lambda a: f"用你的 Gmail 寄信給 {_short(a.get('to'), 40)}"
                                    + (f"，主旨「{_short(a.get('subject'), 30)}」" if a.get("subject") else ""),
    "gdrive_search_files": lambda a: "搜尋你的 Google 雲端硬碟",
    "gdrive_upload_file": lambda a: f"上傳檔案到你的 Google 雲端硬碟：{_short(a.get('file_path') or a.get('path'), 50)}",
    "gcalendar_list_events": lambda a: "查看你的 Google 日曆",
    "gcalendar_create_event": lambda a: f"在你的 Google 日曆新增活動「{_short(a.get('summary') or a.get('title'), 30)}」",
    "gdocs_create_or_append": lambda a: "建立或編輯 Google 文件",
    "gsheets_action": lambda a: "讀取或編輯 Google 試算表",
    "notify_discord": lambda a: "傳一則 Discord 通知",
    "dispatch_ai_coding_prompt": lambda a: "把指令送給其他 AI 編碼工具",
    "install_skill": lambda a: "安裝一個新技能",
    "configure_api_provider": lambda a: "新增或修改 AI 服務的連線設定",
    "add_domain_whitelist": lambda a: f"把網站 {_short(a.get('domain'), 40)} 加入允許清單",
    "kill_threat_process": lambda a: "強制結束一個可疑程式",
    "block_malicious_ip": lambda a: f"封鎖網路位址 {_short(a.get('ip'), 40)}",
}


def describe_tool_action(tool_name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """回傳 {what: 白話一句話, category: 類別名稱, risky: 是否會變更電腦或資料}。"""
    args = args if isinstance(args, dict) else {}
    cat = _TOOL_CATEGORY.get(tool_name, "")
    fn = _PLAIN_ACTIONS.get(tool_name)
    try:
        what = fn(args) if fn else ""
    except Exception:
        what = ""
    if not what:
        what = f"使用「{_CATEGORY_LABEL.get(cat, '進階')}」功能"
    return {"what": what, "category": _CATEGORY_LABEL.get(cat, ""), "risky": cat in _RISKY_CATEGORIES}
_FEATURE_LABEL = {key: label for _p, _pl, _pd, kids in FEATURE_TREE for key, label, _d, _t in kids}
_GOOGLE_LABEL = {key: label for key, label, _d, _s, _t in GOOGLE_SCOPE_OPTIONS}


def default_permissions() -> Dict[str, Any]:
    features: Dict[str, bool] = {}
    for parent, _l, _d, kids in FEATURE_TREE:
        features[parent] = True
        for key, _kl, _kd, _t in kids:
            features[f"{parent}.{key}"] = True
    return {
        "google_scopes": {key: True for key, *_ in GOOGLE_SCOPE_OPTIONS},
        "agent": {key: default for key, _l, _d, default, _t in AGENT_PERMISSION_CATEGORIES},
        "features": features,
        "apps": {"allowed": [dict(a) for a in DEFAULT_ALLOWED_APPS]},
    }


def _section(settings: Optional[Dict[str, Any]], name: str) -> Dict[str, Any]:
    perms = (settings or {}).get("permissions") or {}
    merged = dict(default_permissions()[name])
    sec = perms.get(name)
    if isinstance(sec, dict):
        merged.update(sec)
    return merged


def enabled_google_scopes(settings: Optional[Dict[str, Any]]) -> List[str]:
    sel = _section(settings, "google_scopes")
    return [scope for key, _l, _d, scope, _t in GOOGLE_SCOPE_OPTIONS if sel.get(key)]


def feature_enabled(settings: Optional[Dict[str, Any]], parent: str, child: Optional[str] = None) -> bool:
    feats = _section(settings, "features")
    if not feats.get(parent, True):
        return False
    return True if child is None else bool(feats.get(f"{parent}.{child}", True))


def agent_policy(settings: Optional[Dict[str, Any]], category: str) -> str:
    value = _section(settings, "agent").get(category, ALLOW)
    return value if value in (ALLOW, ASK, DENY) else ALLOW


def check_tool(settings: Optional[Dict[str, Any]], tool_name: str) -> Tuple[str, str]:
    """回傳 (allow/ask/deny, 中文原因)。功能關閉或 Google 權限未勾選一律 deny。"""
    feat = _TOOL_FEATURE.get(tool_name)
    if feat and not feature_enabled(settings, *feat):
        return DENY, f"「{_FEATURE_LABEL[feat[1]]}」功能已在 設定 → 權限與功能 中關閉"
    gkey = _GOOGLE_TOOL_SCOPE.get(tool_name)
    if gkey and not _section(settings, "google_scopes").get(gkey):
        return DENY, f"Google 權限「{_GOOGLE_LABEL[gkey]}」未在 設定 → 權限與功能 中開啟"
    cat = _TOOL_CATEGORY.get(tool_name)
    if not cat:
        return ALLOW, ""
    policy = agent_policy(settings, cat)
    if policy == DENY:
        return DENY, f"「{_CATEGORY_LABEL[cat]}」已在 設定 → 權限與功能 中設為禁止"
    if policy == ASK:
        return ASK, f"「{_CATEGORY_LABEL[cat]}」設定為每次執行前先詢問你"
    return ALLOW, ""


ANTIVIRUS_DLC_TOOLS: Tuple[str, ...] = (
    "scan_antivirus",
    "scan_byovd_and_early_boot",
    "scan_memory_injections",
    "cdr_sanitize_file",
    "sandbox_execute",
    "audit_system_security",
    "kill_threat_process",
    "block_malicious_ip",
    "threat_hunter_annihilate",
    "counter_strike_retaliate",
    "execute_os_cpr",
    "lock_file_anti_tamper",
    "unlock_file_anti_tamper",
    "self_heal_files",
    "ai_predict_and_patch_vulnerability",
    "citadel_backup_data",
)


def summarize_permissions_for_llm(
    settings: Optional[Dict[str, Any]],
    dlc_antivirus_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    在送交大語言模型（語意拆解與主迴圈）之前，快速盤點所有權限設定與選配 DLC 狀態。
    回傳 denied_tools / ask_tools 與可直接注入提示詞的 prompt_notice，明確告知模型哪些動作不可執行。
    """
    all_tools = set(_TOOL_CATEGORY.keys()) | set(_TOOL_FEATURE.keys()) | set(_GOOGLE_TOOL_SCOPE.keys()) | set(ANTIVIRUS_DLC_TOOLS)
    denied_tools: Dict[str, str] = {}
    ask_tools: Dict[str, str] = {}

    for tool_name in sorted(all_tools):
        if dlc_antivirus_enabled is False and tool_name in ANTIVIRUS_DLC_TOOLS:
            denied_tools[tool_name] = "防毒系統屬於獨立選配 DLC，目前未啟用，基礎核心不具備防毒功能"
            continue
        level, why = check_tool(settings, tool_name)
        if level == DENY:
            denied_tools[tool_name] = why
        elif level == ASK:
            ask_tools[tool_name] = why

    lines: List[str] = []
    if denied_tools:
        # 依原因分組，避免提示詞過長
        by_reason: Dict[str, List[str]] = {}
        for t, r in denied_tools.items():
            by_reason.setdefault(r, []).append(t)
        lines.append("[前置權限把關 — 下列操作已被系統或使用者拒絕，絕對不可規劃、呼叫或繞過]：")
        for reason, tools in by_reason.items():
            lines.append(f"- 禁止原因「{reason}」→ 禁用工具：{', '.join(tools)}")
        lines.append("若使用者的要求需要上述被禁止的工具，請直接告知該權限已拒絕或該 DLC 未啟用，不要硬試或假裝執行。")

    if ask_tools:
        lines.append(f"[需人工確認工具]：{', '.join(sorted(ask_tools.keys()))}（呼叫時系統會先請求使用者核准）。")

    return {
        "denied_tools": denied_tools,
        "ask_tools": ask_tools,
        "prompt_notice": "\n".join(lines),
    }
