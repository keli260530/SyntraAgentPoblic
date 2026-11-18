# -*- coding: utf-8 -*-
"""
Syntra 星樞 · 國際化多語言支援模組 (i18n)
支援：繁體中文 (zh_TW)、簡體中文 (zh_CN)、英文 (en)、日語 (ja)、韓文 (ko)
"""

from typing import Any, Callable, Dict, List, Optional

SUPPORTED_LANGUAGES: Dict[str, str] = {
    "zh_TW": "繁體中文 (Traditional Chinese)",
    "zh_CN": "简体中文 (Simplified Chinese)",
    "en": "English",
    "ja": "日本語 (Japanese)",
    "ko": "한국어 (Korean)",
}

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "zh_TW": {
        # 標題與品牌
        "app_title": "Syntra 星樞 · 桌面智能 Agent 與安全監控中心",
        "brand_name": "Syntra 星樞",
        "brand_subtitle": "桌面智能 Agent",
        # 選單欄
        "menu_file": "檔案(&F)",
        "menu_settings": "設定(&S)",
        "menu_language": "🌐 語言 / Language",
        "menu_help": "說明(&H)",
        "menu_new_chat": "➕ 開啟新對話 (Ctrl+T)",
        "menu_new_window": "🪟 多開視窗 (Ctrl+N)",
        "menu_api_settings": "🔑 API 金鑰管理...",
        "menu_system_settings": "⚙️ 系統偏好設定...",
        "menu_kill_switch": "🛑 緊急中止 (Ctrl+Alt+Q)",
        "menu_exit": "❌ 結束 Syntra 星樞",
        # 頂部工具列
        "btn_settings": "⚙️ 系統設定",
        "btn_api_settings": "🔑 設定 API",
        "btn_new_window": "🪟 多開視窗 (Ctrl+N)",
        "btn_new_window_tip": "開啟獨立的新應用程式視窗，具備獨立對話與多工協同",
        "btn_sec_center": "🛡️ CDR 隔離防護",
        "btn_sec_center_tip": "切換至 CDR 格式重構、沙箱執行與網址通報中心",
        "btn_dnd_on": "🔕 免打擾: 開",
        "btn_dnd_off": "🔔 免打擾: 關",
        "btn_kill": "🛑 緊急中止 (Ctrl+Alt+Q)",
        "lbl_context_normal": "🟢 專注 / 正常運作",
        "lbl_context_game": "🎮 遊戲模式 / 免打擾",
        "lbl_context_video": "🎬 觀影模式 / 免打擾",
        # 側邊欄標籤與按鈕
        "tab_quick": "⚡ 快速",
        "tab_explorer": "📁 總管",
        "tab_history": "📜 歷史",
        "tab_schedule": "⏰ 排程",
        "sidebar_quick_header": "快速執行",
        "btn_q_capture": "🖥️ 截圖當前畫面給 AI",
        "btn_q_monitor": "🔍 背景檢查程式碼 AI 視窗",
        "btn_q_git": "🌿 背景審查 Git 與語法錯誤",
        "btn_q_search": "🌐 聯網搜尋並摘要報告",
        "btn_q_structure": "📁 載入當前目錄架構給 AI",
        "lbl_status_models": "可用模型：{count} 個",
        "lbl_status_models_empty": "可用模型：0 個 (請點擊設定金鑰)",
        "btn_manage_api": "🔑 多組 API Key 接入管理",
        "btn_sidebar_settings": "⚙️ 系統設定選單",
        # 聊天輸入卡片
        "input_placeholder": "Ask anything, @ 提及視窗/檔案, / 快捷指令...",
        "btn_send": "發送",
        "tip_context": "新增上下文：附加檔案、資料夾、視窗或網址",
        "tip_model": "切換目前使用的 AI 模型",
        "tip_mode": "設定指令審查防護層級",
        "tip_snap": "即時擷取視窗畫面附加到此對話",
        "tip_send": "送出指令 (Enter)",
        # 右側面板標籤
        "tab_stream": "🖥️ 螢幕串流與監督",
        "tab_mcp": "🧩 Skills & MCP",
        "tab_web": "🌐 上網通報",
        "tab_security": "🛡️ CDR 沙箱防毒",
        "live_stream_header": "🖥️ 即時視窗（點選卡片立即切換）：",
        "btn_refresh": "🔄 重新整理",
        "btn_record": "🔴 錄影",
        "btn_record_stop": "⏹️ 停止錄影",
        "recording_status": "🔴 錄影中: {duration}s ({frames} frames)",
        "supervisor_header": "🤖 自動閉環監督設定 (含 3 次卡關熔斷)",
        "sup_goal_placeholder": "監督當前活動視窗上的 AI 寫程式進度，審查有無語法錯誤",
        "sup_verify_placeholder": "背景驗證指令 (選填，如 pytest -q 或 npm test)",
        "btn_start_sup": "🚀 啟動自動監督",
        "btn_stop_sup": "🛑 停止監督",
        "btn_resume_sup": "🔄 重置失敗計數並重試 (3 次)",
        "skills_table_title": "🧩 本地 Skills 技能倉庫",
        "skills_col_name": "技能名稱",
        "skills_col_type": "類別",
        "skills_col_desc": "說明與路徑",
        "mcp_table_title": "⚡ 本地 MCP Servers (模型上下文協議)",
        "mcp_col_name": "MCP 名稱",
        "mcp_col_cmd": "啟動指令",
        "mcp_col_status": "狀態",
        "btn_add_mcp": "➕ 新增自訂 MCP Server",
        "web_audit_title": "🌐 上網透明通報紀錄",
        # 設定視窗
        "settings_title": "⚙️ 系統設定與偏好中心",
        "settings_tab_general": "🌐 常規與語言",
        "settings_tab_api": "🔑 API Key 管理",
        "settings_tab_discord": "🤖 Discord Bot",
        "settings_tab_security": "🛡️ 資安與交易 PIN",
        "settings_tab_dnd": "🔕 勿擾與自啟動",
        "lang_group_title": "🌐 軟體介面語言 (Language)",
        "lang_label": "選擇顯示語言：",
        "lang_desc": "支援繁體中文、簡體中文、英文、日語、韓文，切換後立即生效並自動儲存。",
        "autostart_group_title": "🚀 Windows 開機自啟動",
        "autostart_check": "開機時自動在系統背景托盤啟動 Syntra 星樞",
        "dnd_group_title": "🔕 智能免打擾感測",
        "dnd_game_check": "自動感測全螢幕遊戲並啟動免打擾 (降速背景進程)",
        "dnd_video_check": "自動感測全螢幕影片播放 (YouTube / Netflix / VLC 等)",
        "dnd_protect_focus": "保護寫程式與文書專注視窗",
        "discord_enabled_check": "啟用 Discord 雙向遠端串接與通知推播",
        "discord_token_label": "Discord Bot Token:",
        "discord_channel_label": "通報與控制 Channel ID:",
        "discord_webhook_label": "Discord Webhook URL (可選):",
        "security_pin_group": "🛡️ 交易與資安防護 PIN 碼",
        "security_pin_desc": "當 Agent 偵測到交易、購物、付款或敏感視窗時，必須輸入安全 PIN 碼核准 (預設為 0000)。",
        "new_pin_label": "設定新的 PIN 碼 (留空代表不變更):",
        "redact_windows_check": "自動模糊與遮蔽敏感視窗畫面 (密碼庫、銀行網頁等)",
        "strict_transaction_check": "嚴格阻斷未經授權的自動付款與交易行為",
        "btn_save_settings": "💾 儲存並套用設定",
        "btn_cancel": "取消",
        "msg_settings_saved": "✅ 設定已成功儲存！",
        "msg_lang_changed": "語言已成功切換為：{lang}",
        # 托盤
        "tray_show": "🖥️ 顯示主視窗",
        "tray_new_win": "🪟 多開視窗",
        "tray_settings": "⚙️ 偏好設定...",
        "tray_quit": "❌ 結束 Syntra 星樞",
    },
    "zh_CN": {
        # 标题与品牌
        "app_title": "Syntra 星枢 · 桌面智能 Agent 与安全监控中心",
        "brand_name": "Syntra 星枢",
        "brand_subtitle": "桌面智能 Agent",
        # 菜单栏
        "menu_file": "文件(&F)",
        "menu_settings": "设置(&S)",
        "menu_language": "🌐 语言 / Language",
        "menu_help": "帮助(&H)",
        "menu_new_chat": "➕ 开启新对话 (Ctrl+T)",
        "menu_new_window": "🪟 多开窗口 (Ctrl+N)",
        "menu_api_settings": "🔑 API 密钥管理...",
        "menu_system_settings": "⚙️ 系统偏好设置...",
        "menu_kill_switch": "🛑 紧急中止 (Ctrl+Alt+Q)",
        "menu_exit": "❌ 退出 Syntra 星枢",
        # 顶部工具栏
        "btn_settings": "⚙️ 系统设置",
        "btn_api_settings": "🔑 设置 API",
        "btn_new_window": "🪟 多开窗口 (Ctrl+N)",
        "btn_new_window_tip": "开启独立的新应用窗口，具备独立对话与多工协同",
        "btn_sec_center": "🛡️ CDR 隔离防护",
        "btn_sec_center_tip": "切换至 CDR 格式重构、沙箱执行与网址通报中心",
        "btn_dnd_on": "🔕 免打扰: 开",
        "btn_dnd_off": "🔔 免打扰: 关",
        "btn_kill": "🛑 紧急中止 (Ctrl+Alt+Q)",
        "lbl_context_normal": "🟢 专注 / 正常运作",
        "lbl_context_game": "🎮 游戏模式 / 免打扰",
        "lbl_context_video": "🎬 观影模式 / 免打扰",
        # 侧边栏
        "tab_quick": "⚡ 快速",
        "tab_explorer": "📁 资源",
        "tab_history": "📜 历史",
        "tab_schedule": "⏰ 排程",
        "sidebar_quick_header": "快速执行",
        "btn_q_capture": "🖥️ 截图当前画面给 AI",
        "btn_q_monitor": "🔍 后台检查代码 AI 窗口",
        "btn_q_git": "🌿 后台审查 Git 与语法错误",
        "btn_q_search": "🌐 联网搜索并摘要报告",
        "btn_q_structure": "📁 加载当前目录结构给 AI",
        "lbl_status_models": "可用模型：{count} 个",
        "lbl_status_models_empty": "可用模型：0 个 (请点击设置密钥)",
        "btn_manage_api": "🔑 多组 API Key 接入管理",
        "btn_sidebar_settings": "⚙️ 系统设置菜单",
        # 聊天输入
        "input_placeholder": "Ask anything, @ 提及窗口/文件, / 快捷指令...",
        "btn_send": "发送",
        "tip_context": "新增上下文：附加文件、文件夹、窗口或网址",
        "tip_model": "切换当前使用的 AI 模型",
        "tip_mode": "设置指令审查防护层级",
        "tip_snap": "实时截取窗口画面附加到此对话",
        "tip_send": "发送指令 (Enter)",
        # 右侧面板
        "tab_stream": "🖥️ 屏幕串流与监督",
        "tab_mcp": "🧩 Skills & MCP",
        "tab_web": "🌐 上网通报",
        "tab_security": "🛡️ CDR 沙箱防毒",
        "live_stream_header": "🖥️ 实时窗口（点击卡片立即切换）：",
        "btn_refresh": "🔄 刷新",
        "btn_record": "🔴 录像",
        "btn_record_stop": "⏹️ 停止录像",
        "recording_status": "🔴 录像中: {duration}s ({frames} frames)",
        "supervisor_header": "🤖 自动闭环监督设定 (含 3 次卡关熔断)",
        "sup_goal_placeholder": "监督当前活动窗口上的 AI 写代码进度，审查有无语法错误",
        "sup_verify_placeholder": "后台验证指令 (选填，如 pytest -q 或 npm test)",
        "btn_start_sup": "🚀 启动自动监督",
        "btn_stop_sup": "🛑 停止监督",
        "btn_resume_sup": "🔄 重置失败计数并重试 (3 次)",
        "skills_table_title": "🧩 本地 Skills 技能仓库",
        "skills_col_name": "技能名称",
        "skills_col_type": "类别",
        "skills_col_desc": "说明与路径",
        "mcp_table_title": "⚡ 本地 MCP Servers (模型上下文协议)",
        "mcp_col_name": "MCP 名称",
        "mcp_col_cmd": "启动指令",
        "mcp_col_status": "状态",
        "btn_add_mcp": "➕ 新增自定义 MCP Server",
        "web_audit_title": "🌐 上网透明通报记录",
        # 设置窗口
        "settings_title": "⚙️ 系统设置与偏好中心",
        "settings_tab_general": "🌐 常规与语言",
        "settings_tab_api": "🔑 API Key 管理",
        "settings_tab_discord": "🤖 Discord Bot",
        "settings_tab_security": "🛡️ 安全与交易 PIN",
        "settings_tab_dnd": "🔕 免打扰与自启动",
        "lang_group_title": "🌐 软件界面语言 (Language)",
        "lang_label": "选择显示语言：",
        "lang_desc": "支持繁体中文、简体中文、英文、日语、韩文，切换后立即生效并自动保存。",
        "autostart_group_title": "🚀 Windows 开机自启动",
        "autostart_check": "开机时自动在系统后台托盘启动 Syntra 星枢",
        "dnd_group_title": "🔕 智能免打扰感测",
        "dnd_game_check": "自动感测全屏游戏并启动免打扰 (降低后台进程优先级)",
        "dnd_video_check": "自动感测全屏视频播放 (YouTube / Netflix / VLC 等)",
        "dnd_protect_focus": "保护编写代码与文档专注窗口",
        "discord_enabled_check": "启用 Discord 双向远程串联与通知推送",
        "discord_token_label": "Discord Bot Token:",
        "discord_channel_label": "通报与控制 Channel ID:",
        "discord_webhook_label": "Discord Webhook URL (可选):",
        "security_pin_group": "🛡️ 交易与安全防护 PIN 码",
        "security_pin_desc": "当 Agent 检测到交易、购物、支付或敏感窗口时，必须输入安全 PIN 码核准 (默认 0000)。",
        "new_pin_label": "设置新的 PIN 码 (留空代表不修改):",
        "redact_windows_check": "自动模糊与遮蔽敏感窗口画面 (密码库、银行网页等)",
        "strict_transaction_check": "严格阻断未经授权的自动支付与交易行为",
        "btn_save_settings": "💾 保存并应用设置",
        "btn_cancel": "取消",
        "msg_settings_saved": "✅ 设置已成功保存！",
        "msg_lang_changed": "语言已成功切换为：{lang}",
        # 托盘
        "tray_show": "🖥️ 显示主窗口",
        "tray_new_win": "🪟 多开窗口",
        "tray_settings": "⚙️ 偏好设置...",
        "tray_quit": "❌ 退出 Syntra 星枢",
    },
    "en": {
        # Title and Branding
        "app_title": "Syntra Hub · Desktop Intelligent Agent & Security Sentinel",
        "brand_name": "Syntra Hub",
        "brand_subtitle": "Desktop Intelligent Agent",
        # Menus
        "menu_file": "&File",
        "menu_settings": "&Settings",
        "menu_language": "🌐 &Language",
        "menu_help": "&Help",
        "menu_new_chat": "➕ New Chat Session (Ctrl+T)",
        "menu_new_window": "🪟 New Window (Ctrl+N)",
        "menu_api_settings": "🔑 API Key Management...",
        "menu_system_settings": "⚙️ System Preferences...",
        "menu_kill_switch": "🛑 Emergency Kill (Ctrl+Alt+Q)",
        "menu_exit": "❌ Exit Syntra Hub",
        # Top Bar
        "btn_settings": "⚙️ Settings",
        "btn_api_settings": "🔑 API Keys",
        "btn_new_window": "🪟 New Window (Ctrl+N)",
        "btn_new_window_tip": "Spawn an independent workspace window for multitasking",
        "btn_sec_center": "🛡️ CDR Sandbox Shield",
        "btn_sec_center_tip": "Switch to CDR sanitization, sandbox executor, and network audit",
        "btn_dnd_on": "🔕 DND: ON",
        "btn_dnd_off": "🔔 DND: OFF",
        "btn_kill": "🛑 Emergency Kill (Ctrl+Alt+Q)",
        "lbl_context_normal": "🟢 Focus / Normal Active",
        "lbl_context_game": "🎮 Gaming Mode / DND",
        "lbl_context_video": "🎬 Video Mode / DND",
        # Sidebar
        "tab_quick": "⚡ Quick",
        "tab_explorer": "📁 Explorer",
        "tab_history": "📜 History",
        "tab_schedule": "⏰ Schedule",
        "sidebar_quick_header": "Quick Actions",
        "btn_q_capture": "🖥️ Send Screenshot to AI",
        "btn_q_monitor": "🔍 Inspect Coding AI Window",
        "btn_q_git": "🌿 Background Git & Syntax Check",
        "btn_q_search": "🌐 Web Search & Summary",
        "btn_q_structure": "📁 Load Workspace Tree to AI",
        "lbl_status_models": "Available Models: {count}",
        "lbl_status_models_empty": "Available Models: 0 (Click to configure key)",
        "btn_manage_api": "🔑 Manage API Providers & Keys",
        "btn_sidebar_settings": "⚙️ System Settings Menu",
        # Chat Input
        "input_placeholder": "Ask anything, @ to mention window/file, / for slash commands...",
        "btn_send": "Send",
        "tip_context": "Add context: attach file, folder, window or browser URL",
        "tip_model": "Switch AI model",
        "tip_mode": "Set permission and security mode",
        "tip_snap": "Quickly capture active window and attach to chat",
        "tip_send": "Send prompt (Enter)",
        # Right Panel
        "tab_stream": "🖥️ Screen & Supervision",
        "tab_mcp": "🧩 Skills & MCP",
        "tab_web": "🌐 Web Audit",
        "tab_security": "🛡️ CDR Sandbox Shield",
        "live_stream_header": "🖥️ Active Windows (Click to switch):",
        "btn_refresh": "🔄 Refresh",
        "btn_record": "🔴 Record",
        "btn_record_stop": "⏹️ Stop Record",
        "recording_status": "🔴 Recording: {duration}s ({frames} frames)",
        "supervisor_header": "🤖 Automated Supervision (3-strike circuit breaker)",
        "sup_goal_placeholder": "Supervise active window coding progress and verify syntax",
        "sup_verify_placeholder": "Background verification command (e.g., pytest -q or npm test)",
        "btn_start_sup": "🚀 Start Supervision",
        "btn_stop_sup": "🛑 Stop Supervision",
        "btn_resume_sup": "🔄 Reset Circuit Breaker & Retry",
        "skills_table_title": "🧩 Local Skills Catalog",
        "skills_col_name": "Skill Name",
        "skills_col_type": "Category",
        "skills_col_desc": "Description & Path",
        "mcp_table_title": "⚡ Local MCP Servers",
        "mcp_col_name": "MCP Server",
        "mcp_col_cmd": "Command",
        "mcp_col_status": "Status",
        "btn_add_mcp": "➕ Add Custom MCP Server",
        "web_audit_title": "🌐 Network Transparency & Audit Logs",
        # Settings Dialog
        "settings_title": "⚙️ System Preferences & Settings",
        "settings_tab_general": "🌐 General & Language",
        "settings_tab_api": "🔑 API Keys",
        "settings_tab_discord": "🤖 Discord Bot",
        "settings_tab_security": "🛡️ Security & PIN",
        "settings_tab_dnd": "🔕 DND & Autostart",
        "lang_group_title": "🌐 Interface Display Language",
        "lang_label": "Select UI Language:",
        "lang_desc": "Supports Traditional Chinese, Simplified Chinese, English, Japanese, and Korean. Changes apply immediately.",
        "autostart_group_title": "🚀 Windows Startup",
        "autostart_check": "Launch Syntra Hub automatically in system tray on boot",
        "dnd_group_title": "🔕 Smart Do Not Disturb (DND)",
        "dnd_game_check": "Auto-detect full screen gaming (lowers background process priority)",
        "dnd_video_check": "Auto-detect full screen video playback (YouTube / Netflix / VLC)",
        "dnd_protect_focus": "Protect coding and document focus windows",
        "discord_enabled_check": "Enable Discord bot bridge and remote notifications",
        "discord_token_label": "Discord Bot Token:",
        "discord_channel_label": "Channel ID for notifications and commands:",
        "discord_webhook_label": "Discord Webhook URL (optional):",
        "security_pin_group": "🛡️ Transaction & Security PIN",
        "security_pin_desc": "Requires security PIN when transactions or sensitive windows are detected (default: 0000).",
        "new_pin_label": "Set new security PIN (leave empty to keep unchanged):",
        "redact_windows_check": "Auto-blur sensitive windows (passwords, banking portals, etc.)",
        "strict_transaction_check": "Strictly block unauthorized automated transactions and purchases",
        "btn_save_settings": "💾 Save & Apply Settings",
        "btn_cancel": "Cancel",
        "msg_settings_saved": "✅ Settings saved successfully!",
        "msg_lang_changed": "Language switched to: {lang}",
        # Tray
        "tray_show": "🖥️ Show Main Window",
        "tray_new_win": "🪟 New Window",
        "tray_settings": "⚙️ Preferences...",
        "tray_quit": "❌ Exit Syntra Hub",
    },
    "ja": {
        # タイトルとブランド
        "app_title": "Syntra 星枢 · デスクトップ知能エージェント＆セキュリティ監視センター",
        "brand_name": "Syntra 星枢",
        "brand_subtitle": "デスクトップ知能 Agent",
        # メニューバー
        "menu_file": "ファイル(&F)",
        "menu_settings": "設定(&S)",
        "menu_language": "🌐 言語 / Language",
        "menu_help": "ヘルプ(&H)",
        "menu_new_chat": "➕ 新規チャットを開始 (Ctrl+T)",
        "menu_new_window": "🪟 新規ウィンドウ (Ctrl+N)",
        "menu_api_settings": "🔑 APIキー管理...",
        "menu_system_settings": "⚙️ システム環境設定...",
        "menu_kill_switch": "🛑 緊急停止 (Ctrl+Alt+Q)",
        "menu_exit": "❌ Syntra 星枢を終了",
        # トップツールバー
        "btn_settings": "⚙️ システム設定",
        "btn_api_settings": "🔑 API設定",
        "btn_new_window": "🪟 新規ウィンドウ (Ctrl+N)",
        "btn_new_window_tip": "独立した新しいウィンドウを開き、マルチタスクを並行処理します",
        "btn_sec_center": "🛡️ CDRサンドボックス防御",
        "btn_sec_center_tip": "CDRファイル再構築、サンドボックス実行、通信監視センターへ切替",
        "btn_dnd_on": "🔕 応答不可: オン",
        "btn_dnd_off": "🔔 応答不可: オフ",
        "btn_kill": "🛑 緊急停止 (Ctrl+Alt+Q)",
        "lbl_context_normal": "🟢 集中 / 正常稼働",
        "lbl_context_game": "🎮 ゲームモード / 応答不可",
        "lbl_context_video": "🎬 動画鑑賞中 / 応答不可",
        # サイドバー
        "tab_quick": "⚡ クイック",
        "tab_explorer": "📁 エクスプローラー",
        "tab_history": "📜 履歴",
        "tab_schedule": "⏰ スケジュール",
        "sidebar_quick_header": "クイック実行",
        "btn_q_capture": "🖥️ 画面キャプチャをAIに送信",
        "btn_q_monitor": "🔍 背景でコードAIウィンドウを監視",
        "btn_q_git": "🌿 Gitと構文エラーを自動検査",
        "btn_q_search": "🌐 ネット検索と要約レポート",
        "btn_q_structure": "📁 プロジェクト構造をAIに読込",
        "lbl_status_models": "利用可能なモデル: {count}個",
        "lbl_status_models_empty": "利用可能なモデル: 0個 (キーを設定してください)",
        "btn_manage_api": "🔑 複数APIキー連携管理",
        "btn_sidebar_settings": "⚙️ システム設定メニュー",
        # チャット入力
        "input_placeholder": "何でも質問、@ でウィンドウ/ファイル参照、/ でコマンド...",
        "btn_send": "送信",
        "tip_context": "コンテキスト追加：ファイル、フォルダ、ウィンドウまたはURL",
        "tip_model": "使用するAIモデルを切り替え",
        "tip_mode": "コマンド承認とセキュリティ保護レベルを設定",
        "tip_snap": "アクティブウィンドウをキャプチャしてチャットに添付",
        "tip_send": "送信 (Enter)",
        # 右パネル
        "tab_stream": "🖥️ 画面配信と監視",
        "tab_mcp": "🧩 スキル＆MCP",
        "tab_web": "🌐 ネット通信監視",
        "tab_security": "🛡️ CDRサンドボックス防御",
        "live_stream_header": "🖥️ 実行中ウィンドウ（クリックで即座に切り替え）：",
        "btn_refresh": "🔄 更新",
        "btn_record": "🔴 録画",
        "btn_record_stop": "⏹️ 録画停止",
        "recording_status": "🔴 録画中: {duration}s ({frames} frames)",
        "supervisor_header": "🤖 自動フィードバック監視 (3回連続失敗で遮断)",
        "sup_goal_placeholder": "アクティブウィンドウのAIコード進行状況を監視し構文を確認",
        "sup_verify_placeholder": "バックグラウンド検証コマンド (任意、pytest -q または npm test)",
        "btn_start_sup": "🚀 自動監視を開始",
        "btn_stop_sup": "🛑 監視を停止",
        "btn_resume_sup": "🔄 失敗カウントをリセットして再試行",
        "skills_table_title": "🧩 ローカル Skills ライブラリ",
        "skills_col_name": "スキル名",
        "skills_col_type": "分類",
        "skills_col_desc": "説明とパス",
        "mcp_table_title": "⚡ ローカル MCP Servers",
        "mcp_col_name": "MCP サーバー名",
        "mcp_col_cmd": "起動コマンド",
        "mcp_col_status": "状態",
        "btn_add_mcp": "➕ カスタム MCP を追加",
        "web_audit_title": "🌐 ネットワーク通信透明性ログ",
        # 設定ウィンドウ
        "settings_title": "⚙️ システム環境設定センター",
        "settings_tab_general": "🌐 一般と言語",
        "settings_tab_api": "🔑 APIキー管理",
        "settings_tab_discord": "🤖 Discord連携",
        "settings_tab_security": "🛡️ セキュリティ＆PIN",
        "settings_tab_dnd": "🔕 応答不可＆自動起動",
        "lang_group_title": "🌐 表示言語 (Language)",
        "lang_label": "言語を選択：",
        "lang_desc": "繁体字、簡体字、英語、日本語、韓国語に対応。切り替えは即座に反映され保存されます。",
        "autostart_group_title": "🚀 Windows 自動起動",
        "autostart_check": "Windows起動時にシステムトレイで自動的に起動する",
        "dnd_group_title": "🔕 スマート応答不可 (DND)",
        "dnd_game_check": "全画面ゲームを自動検知して応答不可にする (バックグラウンド負荷低減)",
        "dnd_video_check": "全画面動画再生を自動検知 (YouTube / Netflix / VLC など)",
        "dnd_protect_focus": "コーディングや作業ウィンドウの集中を保護",
        "discord_enabled_check": "Discord Bot双方向連携と通知プッシュを有効化",
        "discord_token_label": "Discord Bot Token:",
        "discord_channel_label": "通知・操作用 Channel ID:",
        "discord_webhook_label": "Discord Webhook URL (任意):",
        "security_pin_group": "🛡️ 取引＆セキュリティ保護 PINコード",
        "security_pin_desc": "決済や機密ウィンドウを検知した際、PINコード認証を要求します (初期値: 0000)。",
        "new_pin_label": "新しいPINコードを設定 (空白なら変更なし):",
        "redact_windows_check": "機密ウィンドウ（パスワード管理、銀行等）を自動ぼかし処理",
        "strict_transaction_check": "未承認の自動決済・購入行為を厳格にブロック",
        "btn_save_settings": "💾 設定を保存して適用",
        "btn_cancel": "キャンセル",
        "msg_settings_saved": "✅ 設定が正常に保存され、適用されました！",
        "msg_lang_changed": "言語が切り替わりました：{lang}",
        # トレイ
        "tray_show": "🖥️ メインウィンドウを表示",
        "tray_new_win": "🪟 新規ウィンドウ",
        "tray_settings": "⚙️ 環境設定...",
        "tray_quit": "❌ Syntra 星枢を終了",
    },
    "ko": {
        # 제목 및 브랜드
        "app_title": "Syntra 성추 · 데스크톱 지능형 에이전트 및 보안 관제 센터",
        "brand_name": "Syntra 성추",
        "brand_subtitle": "데스크톱 지능형 Agent",
        # 메뉴 표시줄
        "menu_file": "파일(&F)",
        "menu_settings": "설정(&S)",
        "menu_language": "🌐 언어 / Language",
        "menu_help": "도움말(&H)",
        "menu_new_chat": "➕ 새 대화 시작 (Ctrl+T)",
        "menu_new_window": "🪟 새 창 열기 (Ctrl+N)",
        "menu_api_settings": "🔑 API 키 관리...",
        "menu_system_settings": "⚙️ 시스템 환경설정...",
        "menu_kill_switch": "🛑 비상 정지 (Ctrl+Alt+Q)",
        "menu_exit": "❌ Syntra 성추 종료",
        # 상단 도구 모음
        "btn_settings": "⚙️ 시스템 설정",
        "btn_api_settings": "🔑 API 설정",
        "btn_new_window": "🪟 새 창 열기 (Ctrl+N)",
        "btn_new_window_tip": "독립된 새 창을 열어 멀티태스킹을 병렬 수행합니다",
        "btn_sec_center": "🛡️ CDR 샌드박스 보안",
        "btn_sec_center_tip": "CDR 파일 재구성, 샌드박스 실행 및 통신 감사 센터로 전환",
        "btn_dnd_on": "🔕 방해금지: 켜짐",
        "btn_dnd_off": "🔔 방해금지: 꺼짐",
        "btn_kill": "🛑 비상 정지 (Ctrl+Alt+Q)",
        "lbl_context_normal": "🟢 집중 / 정상 작동",
        "lbl_context_game": "🎮 게임 모드 / 방해금지",
        "lbl_context_video": "🎬 동영상 시청 / 방해금지",
        # 사이드바
        "tab_quick": "⚡ 빠른 실행",
        "tab_explorer": "📁 탐색기",
        "tab_history": "📜 히스토리",
        "tab_schedule": "⏰ 예약 작업",
        "sidebar_quick_header": "빠른 실행",
        "btn_q_capture": "🖥️ 현재 화면 캡처하여 AI 전송",
        "btn_q_monitor": "🔍 백그라운드 코드 AI 창 점검",
        "btn_q_git": "🌿 백그라운드 Git 및 문법 검사",
        "btn_q_search": "🌐 웹 검색 및 요약 보고서",
        "btn_q_structure": "📁 현재 프로젝트 구조 AI 로드",
        "lbl_status_models": "사용 가능한 모델: {count}개",
        "lbl_status_models_empty": "사용 가능한 모델: 0개 (키 설정 필요)",
        "btn_manage_api": "🔑 다중 API 키 연동 관리",
        "btn_sidebar_settings": "⚙️ 시스템 설정 메뉴",
        # 채팅 입력
        "input_placeholder": "무엇이든 질문, @ 로 창/파일 언급, / 로 단축 명령어...",
        "btn_send": "전송",
        "tip_context": "컨텍스트 추가: 파일, 폴더, 창 또는 웹 URL",
        "tip_model": "현재 사용하는 AI 모델 변경",
        "tip_mode": "명령어 승인 및 보안 모드 설정",
        "tip_snap": "활성 창 화면을 캡처하여 대화에 첨부",
        "tip_send": "명령어 전송 (Enter)",
        # 우측 패널
        "tab_stream": "🖥️ 화면 스트리밍 및 감독",
        "tab_mcp": "🧩 스킬 및 MCP",
        "tab_web": "🌐 웹 통신 기록",
        "tab_security": "🛡️ CDR 샌드박스 보안",
        "live_stream_header": "🖥️ 활성 창 목록 (클릭하여 즉시 전환)：",
        "btn_refresh": "🔄 새로고침",
        "btn_record": "🔴 녹화",
        "btn_record_stop": "⏹️ 녹화 중지",
        "recording_status": "🔴 녹화 중: {duration}s ({frames} frames)",
        "supervisor_header": "🤖 자동 피드백 감독 (3회 연속 실패 시 차단)",
        "sup_goal_placeholder": "활성 창의 AI 코딩 진행 상황 감독 및 문법 오류 점검",
        "sup_verify_placeholder": "백그라운드 검증 명령 (선택사항, 예: pytest -q 또는 npm test)",
        "btn_start_sup": "🚀 자동 감독 시작",
        "btn_stop_sup": "🛑 감독 중지",
        "btn_resume_sup": "🔄 실패 횟수 재설정 후 재시도 (3회)",
        "skills_table_title": "🧩 로컬 Skills 저장소",
        "skills_col_name": "스킬 이름",
        "skills_col_type": "분류",
        "skills_col_desc": "설명 및 경로",
        "mcp_table_title": "⚡ 로컬 MCP Servers",
        "mcp_col_name": "MCP 이름",
        "mcp_col_cmd": "실행 명령",
        "mcp_col_status": "상태",
        "btn_add_mcp": "➕ 사용자 정의 MCP 추가",
        "web_audit_title": "🌐 네트워크 투명성 감사 기록",
        # 설정 창
        "settings_title": "⚙️ 시스템 환경설정 센터",
        "settings_tab_general": "🌐 일반 및 언어",
        "settings_tab_api": "🔑 API 키 관리",
        "settings_tab_discord": "🤖 Discord 연동",
        "settings_tab_security": "🛡️ 보안 및 결제 PIN",
        "settings_tab_dnd": "🔕 방해금지 및 자동시작",
        "lang_group_title": "🌐 인터페이스 표시 언어 (Language)",
        "lang_label": "표시 언어 선택：",
        "lang_desc": "번체 중국어, 간체 중국어, 영어, 일본어, 한국어를 지원하며 설정 즉시 전체 화면에 적용됩니다.",
        "autostart_group_title": "🚀 Windows 자동 시작",
        "autostart_check": "부팅 시 시스템 트레이에서 Syntra 성추 자동 실행",
        "dnd_group_title": "🔕 스마트 방해금지 (DND)",
        "dnd_game_check": "전체 화면 게임 자동 감지 및 방해금지 전환 (백그라운드 부하 저하)",
        "dnd_video_check": "전체 화면 동영상 재생 자동 감지 (YouTube / Netflix / VLC 등)",
        "dnd_protect_focus": "코딩 및 작업 창 집중 모드 보호",
        "discord_enabled_check": "Discord 봇 양방향 원격 연동 및 알림 푸시 활성화",
        "discord_token_label": "Discord Bot Token:",
        "discord_channel_label": "알림 및 제어 Channel ID:",
        "discord_webhook_label": "Discord Webhook URL (선택사항):",
        "security_pin_group": "🛡️ 결제 및 보안 보호 PIN 번호",
        "security_pin_desc": "결제 또는 민감한 창이 감지되면 보안 PIN 승인이 필요합니다 (기본값: 0000).",
        "new_pin_label": "새로운 PIN 번호 설정 (비워두면 변경 없음):",
        "redact_windows_check": "민감한 창 화면 자동 블러 처리 (비밀번호 관리자, 은행 웹사이트 등)",
        "strict_transaction_check": "무단 자동 결제 및 거래 행위 엄격 차단",
        "btn_save_settings": "💾 설정 저장 및 적용",
        "btn_cancel": "취소",
        "msg_settings_saved": "✅ 설정이 성공적으로 저장 및 적용되었습니다!",
        "msg_lang_changed": "언어가 변경되었습니다: {lang}",
        # 트레이
        "tray_show": "🖥️ 메인 창 표시",
        "tray_new_win": "🪟 새 창 열기",
        "tray_settings": "⚙️ 환경설정...",
        "tray_quit": "❌ Syntra 성추 종료",
    },
}


class I18nManager:
    """
    全域多語言管理單例
    負責語言切換、文字翻譯查詢以及通知監聽器 (Listener 回呼) 即時刷新 UI
    """

    _instance: Optional["I18nManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, default_lang: str = "zh_TW"):
        if getattr(self, "_initialized", False):
            return
        self._current_lang = default_lang if default_lang in SUPPORTED_LANGUAGES else "zh_TW"
        self._listeners: List[Callable[[str], None]] = []
        self._settings_manager = None
        self._initialized = True

    def init_from_settings(self, settings_manager: Any):
        """與 SettingsManager 連動並載入持久化儲存的語言"""
        self._settings_manager = settings_manager
        if hasattr(settings_manager, "get_language"):
            lang = settings_manager.get_language()
            if lang in SUPPORTED_LANGUAGES:
                self._current_lang = lang
        elif hasattr(settings_manager, "get_raw"):
            lang = settings_manager.get_raw().get("language", "zh_TW")
            if lang in SUPPORTED_LANGUAGES:
                self._current_lang = lang

    def get_language(self) -> str:
        return self._current_lang

    def get_supported_languages(self) -> Dict[str, str]:
        return SUPPORTED_LANGUAGES.copy()

    def set_language(self, lang_code: str, notify: bool = True):
        if lang_code not in SUPPORTED_LANGUAGES:
            return
        if self._current_lang == lang_code and not notify:
            return
        self._current_lang = lang_code
        if self._settings_manager and hasattr(self._settings_manager, "update_settings"):
            try:
                self._settings_manager.update_settings({"language": lang_code})
            except Exception:
                pass
        if notify:
            for cb in list(self._listeners):
                try:
                    cb(lang_code)
                except Exception:
                    pass

    def t(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        取得當前語言之字串翻譯
        若找不到則 fallback 回繁體中文，最後 fallback 回 default 或 key
        """
        table = TRANSLATIONS.get(self._current_lang, {})
        val = table.get(key)
        if val is None:
            # Fallback to zh_TW
            val = TRANSLATIONS.get("zh_TW", {}).get(key, default or key)
        if kwargs:
            try:
                val = val.format(**kwargs)
            except Exception:
                pass
        return val

    def register_listener(self, callback: Callable[[str], None]):
        """註冊語言切換時的 UI 更新回呼"""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unregister_listener(self, callback: Callable[[str], None]):
        if callback in self._listeners:
            self._listeners.remove(callback)


# 全域單例與快捷翻譯函式
i18n = I18nManager()


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    return i18n.t(key, default=default, **kwargs)
