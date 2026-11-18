import re
from typing import Any, Dict, List, Optional, Tuple


class SlashCommandManager:
    """
    Antigravity 原生風格斜線指令管理器：
    1. 支援 /goal, /grill-me, /plan, /teamwork, /learn, /browser 等核心指令。
    2. 自動提取指令與參數，將特化執行框架（System Prompt 或 User Directive）注入 Agent 對話。
    3. 提供選單補齊清單供 UI 自動彈出使用。
    """

    COMMANDS = {
        "/goal": {
            "name": "/goal",
            "title": "目標導向自主模式",
            "syntax": "/goal <目標任務描述>",
            "desc": "以極高完成度自主執行到底，主動驗證、自主修正，直至目標徹底達成不輕易停下。",
            "badge": "🎯 GOAL",
            "prompt_prefix": (
                "【啟動 GOAL 自主達成模式】\n"
                "你現在進入最高專注度的「目標自主達成」模式。請遵守以下鐵律：\n"
                "1. 徹底拆解目標任務，主動調用工具進行終端測試、代碼檢查或驗證。\n"
                "2. 絕不半途停下並丟回給使用者，除非遇到需要安全授權或致命無法繞過的瓶頸。\n"
                "3. 每次操作後必須自我驗證成果，確保產出真實可用。\n\n"
                "目標任務：\n"
            ),
        },
        "/grill-me": {
            "name": "/grill-me",
            "title": "架構質詢模式",
            "syntax": "/grill-me <設計構想/主題>",
            "desc": "扮演嚴格的資深首席架構師，針對邊界條件、安全性、架構盲點對你進行深入連珠砲提問。",
            "badge": "🔥 GRILL-ME",
            "prompt_prefix": (
                "【啟動 GRILL-ME 架構質詢模式】\n"
                "你現在是一位極其嚴謹、敏銳、不留情面的資深首席架構師。\n"
                "先不要急著給出解決方案或大量代碼，請針對使用者的構想，提出 3~5 個最核心、最可能崩潰的「架構盲點、邊界條件、資安威脅或效能瓶頸」問題，反向質詢使用者以對齊決策。\n\n"
                "待質詢的主題/構想：\n"
            ),
        },
        "/plan": {
            "name": "/plan",
            "title": "規劃藍圖模式",
            "syntax": "/plan <需求或功能>",
            "desc": "制定詳盡的 Step-by-step 執行藍圖、依賴分析、潛在風險評估與回滾機制，待確認後執行。",
            "badge": "📋 PLAN",
            "prompt_prefix": (
                "【啟動 PLAN 藍圖規劃模式】\n"
                "請先暫停直接寫代碼，為以下任務產出結構嚴謹的執行藍圖：\n"
                "1. 核心需求與邊界分析\n"
                "2. 具體 Step-by-step 執行步驟（標註依賴與預期產出）\n"
                "3. 潛在風險點與回滾機制\n"
                "4. 驗證與測試策略\n\n"
                "任務內容：\n"
            ),
        },
        "/teamwork": {
            "name": "/teamwork",
            "title": "多角色協同模式",
            "syntax": "/teamwork <複雜專案任務>",
            "desc": "模擬團隊協同：由架構師、資深工程師、安全審查員多維度激辯與分工推進。",
            "badge": "👥 TEAMWORK",
            "prompt_prefix": (
                "【啟動 TEAMWORK 多角色團隊模式】\n"
                "你現在代表一支頂尖工程團隊進行協同合作，請在回覆中以三種專屬角色推進：\n"
                "- 🏛️ [架構師 Architect]：規劃系統邊界、模組拆分與長期可維護性。\n"
                "- 💻 [資深工程師 Engineer]：提供乾淨、健壯、生產級的具體實作程式碼。\n"
                "- 🛡️ [安全與審查員 Reviewer]：挑剔 edge case、資安隱患、防呆機制與測試驗證。\n\n"
                "專案任務：\n"
            ),
        },
        "/learn": {
            "name": "/learn",
            "title": "經驗固化與技能學習",
            "syntax": "/learn <學到的經驗/修正/專案規範>",
            "desc": "將使用者的修正指引或關鍵經驗，自動固化並沉澱為持久化本機 Skill 或 Rule。",
            "badge": "🧠 LEARN",
            "prompt_prefix": (
                "【啟動 LEARN 經驗固化模式】\n"
                "使用者提供了一項寶貴的修正指引或專案規則。請深入分析此經驗，並使用 `install_skill` 或呼叫學習工具將此規則固化儲存為本地技能/規則庫，以便在未來的對話中永久生效。\n\n"
                "學習內容：\n"
            ),
        },
        "/google": {
            "name": "/google",
            "title": "Google MCP 權威查證模式",
            "syntax": "/google <查詢問題或關鍵字>",
            "desc": "瀏覽器受限或需要權威多來源比對時，優先調用已掛載的 Google MCP 服務或權威搜尋並附上可展開查證連結。",
            "badge": "🔎 GOOGLE",
            "prompt_prefix": (
                "【啟動 GOOGLE MCP 多來源權威查證】\n"
                "請優先使用系統已掛載的 Google MCP 服務（或 `web_search` / `web_fetch`）進行多項目搜尋交叉比對，"
                "引用官方／權威來源佐證，並確保最終連結與內容完全一致。\n\n"
                "查詢需求：\n"
            ),
        },
        "/browser": {
            "name": "/browser",
            "title": "深度網頁瀏覽模式",
            "syntax": "/browser <網址或目標資訊>",
            "desc": "主動調用 Browser 工具鏈造訪真實網頁，執行截圖、DOM 結構提取、互動點擊與內容分析。",
            "badge": "🌐 BROWSER",
            "prompt_prefix": (
                "【啟動 BROWSER 深度瀏覽模式】\n"
                "請直接調用 `browser_navigate`、`browser_extract` 或 `browser_screenshot` 等瀏覽器工具鏈，真實造訪該網址或搜尋目標，擷取完整內容或分析頁面結構，並清楚列出網頁摘要。\n\n"
                "目標網址/瀏覽需求：\n"
            ),
        },
        "/screen": {
            "name": "/screen",
            "title": "即時螢幕擷取",
            "syntax": "/screen <分析指令>",
            "desc": "即時擷取當前桌面或選定視窗之最新畫面，並將影像送交 AI Vision 進行深度辨識與分析。",
            "badge": "📸 SCREEN",
            "prompt_prefix": (
                "【啟動 SCREEN 視覺分析】\n"
                "已擷取當前即時螢幕畫面。請根據畫面內容，執行使用者所要求的操作分析或視覺比對：\n\n"
            ),
        },
        "/uia": {
            "name": "/uia",
            "title": "無障礙語意樹代替截圖",
            "syntax": "/uia <操作指示或目標元素>",
            "desc": "以作業系統原生無障礙 API (Windows UI Automation) 提取完整結構樹、元素 ID 與原始文字，代替畫面截圖操作。",
            "badge": "♿ UIA",
            "prompt_prefix": (
                "【啟動 UIA 作業系統無障礙模式】\n"
                "請優先調用 inspect_accessibility_tree 工具讀取當前視窗或桌面的無障礙結構樹，代替傳統截圖！\n"
                "利用樹中的元素 ID（例如 #1, #2）直接使用 ui_invoke 或 ui_type 進行原生操作，若需點擊則使用 ui_click：\n\n"
            ),
        },
        "/compact": {
            "name": "/compact",
            "title": "壓縮對話上下文",
            "syntax": "/compact",
            "desc": "精簡與摘要長對話歷史，清理冗餘輸出，釋放 LLM Token 上下文視窗。",
            "badge": "📦 COMPACT",
            "prompt_prefix": (
                "【啟動 COMPACT 上下文精簡】\n"
                "請對我們至今的所有對話進行結構化濃縮摘要：保留所有關鍵結論、技術決策、已完成事項與待辦任務，刪除中間冗餘除錯細節。\n"
            ),
        },
        "/review": {
            "name": "/review",
            "title": "安全性與代碼審查",
            "syntax": "/review <程式碼或模組>",
            "desc": "針對當前專案程式碼進行嚴格的安全性、記憶體洩漏、邊界條件與 SOLID 架構審查。",
            "badge": "🛡️ REVIEW",
            "prompt_prefix": (
                "【啟動 REVIEW 嚴格審查】\n"
                "請以最嚴格的資深安全審查員角度，審查指定的程式碼與架構，指出潛在的漏洞、例外風險與效能隱患，並提供修復代碼。\n\n"
            ),
        },
        "/mcp": {
            "name": "/mcp",
            "title": "本機 MCP 管理與調度",
            "syntax": "/mcp <伺服器名稱或指令>",
            "desc": "查詢電腦上已安裝的 Model Context Protocol (MCP) 伺服器並進行調度與工具測試。",
            "badge": "🧩 MCP",
            "prompt_prefix": (
                "【調用 MCP 伺服器工具】\n"
                "請檢視當前已連線的 MCP 伺服器與技能工具，並根據以下需求執行工具調用：\n\n"
            ),
        },
        "/status": {
            "name": "/status",
            "title": "系統狀態與防護檢視",
            "syntax": "/status",
            "desc": "檢視目前 Syntra 星樞 常駐狀態、免打擾狀態、防毒稽核與目前 API 配額。",
            "badge": "⚡ STATUS",
            "prompt_prefix": (
                "【查詢系統狀態】\n"
                "請回報目前的系統運行狀態、連線狀況與已啟用的保護模組概況。\n"
            ),
        },
    }

    @classmethod
    def get_command_list(cls) -> List[Dict[str, str]]:
        """提供前端 UI 呈現自動補齊選單"""
        return [
            {
                "cmd": k,
                "title": v["title"],
                "syntax": v["syntax"],
                "desc": v["desc"],
                "badge": v["badge"],
            }
            for k, v in cls.COMMANDS.items()
        ]

    @classmethod
    def parse_and_transform(cls, user_input: str) -> Tuple[bool, Optional[str], str, str]:
        """
        解析使用者輸入是否包含斜線指令。
        回傳：(is_command, command_key, transformed_prompt, badge_label)
        """
        stripped = user_input.strip()
        if not stripped.startswith("/"):
            return False, None, user_input, ""

        parts = stripped.split(maxsplit=1)
        cmd_candidate = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd_candidate in cls.COMMANDS:
            cmd_info = cls.COMMANDS[cmd_candidate]
            transformed = f"{cmd_info['prompt_prefix']}{args if args else '（請依照此模式指引我）'}"
            return True, cmd_candidate, transformed, cmd_info["badge"]

        # 未知指令維持原樣
        return False, None, user_input, ""
