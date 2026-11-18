# -*- coding: utf-8 -*-
"""
Syntra 星樞 · 系統設定與偏好中心 (Settings Dialog)
提供繁體中文、簡體中文、英文、日語、韓文之動態切換，
並整合 API 金鑰、Discord 整合、資安 PIN 碼、免打擾及開機自啟動設定。
"""

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
)

import os
import shutil
import webbrowser
from core.google_workspace_suite import google_suite
from ui.google_signin_button import (CONSOLE_URL, SETUP_GUIDE_HTML, GoogleLoginWorker, GoogleSignInButton,
                                     check_client_secrets, describe_import_error, prompt_cloud_profile_after_login,
                                     revoke_google_access)
from core.permissions import (ALLOW, ASK, DENY, AGENT_PERMISSION_CATEGORIES, FEATURE_TREE, GOOGLE_SCOPE_OPTIONS,
                              KNOWN_APPS, POLICY_LABELS, allowed_apps, default_permissions, enabled_google_scopes,
                              identify_app)
from core.habit_sync_engine import habit_sync_engine
from core.user_profile_manager import user_profile_manager
from core.addon_module_manager import addon_module_manager
from core.app_discovery_and_launcher import (
    compute_effective_allowed_apps,
    is_google_application,
    scan_all_local_apps,
)
from core.i18n import SUPPORTED_LANGUAGES, i18n, t
from core.settings_manager import SettingsManager
from scripts.setup_startup_and_shortcut import configure_windows_autostart
from ui.font_scaler import (
    BASE_FONT_PT,
     WordFontSizeToolbarWidget,
    WordStatusZoomWidget,
    apply_scale_to_widget_tree,
    current_app_pt,
    current_app_scale,
    next_word_size,
    pt_to_scale,
)


class SettingsDialog(QDialog):
    """
    系統設定選單對話框
    頁籤包含：
    1. 🌐 常規與語言 (General & Language) - 繁體中文、簡體中文、英文、日語、韓文
    2. 🔑 API Key 接入管理 (API Providers)
    3. 🤖 Discord Bot 雙向串接 (Discord Integration)
    4. 🛡️ 資安與交易 PIN (Security PIN & Transaction Guard)
    5. 🔕 免打擾與自啟動 (DND & Startup)
    """

    sig_settings_saved = pyqtSignal(dict)
    sig_language_changed = pyqtSignal(str)

    def __init__(
        self,
        settings_manager: SettingsManager,
        api_manager: Optional[Any] = None,
        async_worker: Optional[Any] = None,
        parent: Optional[QWidget] = None,
        initial_tab_index: int = 0,
    ):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.api_manager = api_manager
        self.async_worker = async_worker

        self.setWindowTitle(t("settings_title"))
        self.resize(760, 580)
        self.setMinimumSize(680, 500)

        # 保持現代暗色風格
        self.setStyleSheet("""
            QDialog {
                background-color: #12141c;
                color: #f1f5f9;
            }
            QTabWidget::pane {
                border: 1px solid rgba(255, 255, 255, 0.08);
                background-color: #161922;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #0e1015;
                color: #94a3b8;
                padding: 9px 18px;
                font-weight: 600;
                font-size: 13px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #161922;
                color: #60a5fa;
                border-bottom: 2px solid #60a5fa;
            }
            QGroupBox {
                font-weight: 700;
                font-size: 13px;
                color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                margin-top: 14px;
                padding-top: 16px;
                padding-left: 10px;
                padding-right: 10px;
                padding-bottom: 10px;
                background: rgba(255, 255, 255, 0.02);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #38bdf8;
            }
            QLineEdit, QComboBox {
                background-color: #1c202c;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                color: #f1f5f9;
                padding: 7px 12px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #60a5fa;
            }
            QComboBox QAbstractItemView {
                background-color: #161922;
                color: #f1f5f9;
                selection-background-color: #283044;
                selection-color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.12);
            }
            QCheckBox {
                font-size: 13px;
                color: #e2e8f0;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 4px;
                border: 1px solid #475569;
                background: #1e293b;
            }
            QCheckBox::indicator:checked {
                background-color: #0284c7;
                border-color: #38bdf8;
            }
            QPushButton#primaryBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #4f46e5);
                color: #ffffff;
                font-weight: 700;
                font-size: 13px;
                border-radius: 6px;
                padding: 8px 20px;
                border: none;
            }
            QPushButton#primaryBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4ed8, stop:1 #4338ca);
            }
            QPushButton#secondaryBtn {
                background: rgba(255, 255, 255, 0.06);
                color: #cbd5e1;
                font-size: 13px;
                border-radius: 6px;
                padding: 8px 16px;
                border: 1px solid rgba(255, 255, 255, 0.12);
            }
            QPushButton#secondaryBtn:hover {
                background: rgba(255, 255, 255, 0.12);
                color: #ffffff;
            }
        """)

        self._build_ui()
        self._load_settings_to_ui()
        self.tabs.setCurrentIndex(initial_tab_index)
        apply_scale_to_widget_tree(self, current_app_scale())

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 頂部標題說明列
        header_row = QHBoxLayout()
        header_icon = QLabel("⚙️")
        header_icon.setFont(QFont("Segoe UI Emoji", 20))
        header_row.addWidget(header_icon)

        self.lbl_header_title = QLabel(f"<b>{t('settings_title')}</b>")
        self.lbl_header_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header_row.addWidget(self.lbl_header_title)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        # 主分頁結構
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_general_tab(), t("settings_tab_general"))
        self.tabs.addTab(self._create_api_tab(), t("settings_tab_api"))
        self.tabs.addTab(self._create_discord_tab(), t("settings_tab_discord"))
        self.tabs.addTab(self._create_security_tab(), t("settings_tab_security"))
        self.tabs.addTab(self._create_dnd_tab(), t("settings_tab_dnd"))
        self.tabs.addTab(self._create_google_habit_tab(), "🌐 Google & 習慣同步")
        self.tabs.addTab(self._create_permissions_tab(), "🔐 權限與功能")
        self.tabs.addTab(self._create_addons_tab(), "🧩 選配模組 (DLC)")
        main_layout.addWidget(self.tabs, stretch=1)

        # 底部動作列 (儲存、取消)
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(10)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #4ade80; font-weight: 600; font-size: 12.5px;")
        btn_bar.addWidget(self.lbl_status)
        btn_bar.addStretch()

        self.btn_cancel = QPushButton(t("btn_cancel"))
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_save = QPushButton(t("btn_save_settings"))
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self.save_settings)
        btn_bar.addWidget(self.btn_save)

        main_layout.addLayout(btn_bar)

    def _create_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        # 1. 軟體顯示語言選擇群組
        self.grp_lang = QGroupBox(t("lang_group_title"))
        lang_layout = QVBoxLayout(self.grp_lang)
        lang_layout.setSpacing(10)

        row_sel = QHBoxLayout()
        self.lbl_lang = QLabel(t("lang_label"))
        self.lbl_lang.setFont(QFont("Segoe UI", 10, QFont.Bold))
        row_sel.addWidget(self.lbl_lang)

        self.combo_lang = QComboBox()
        self.combo_lang.setMinimumWidth(280)
        for code, name in SUPPORTED_LANGUAGES.items():
            self.combo_lang.addItem(name, code)
        self.combo_lang.currentIndexChanged.connect(self._on_language_selection_changed)
        row_sel.addWidget(self.combo_lang)
        row_sel.addStretch()
        lang_layout.addLayout(row_sel)

        self.lbl_lang_desc = QLabel(t("lang_desc"))
        self.lbl_lang_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.lbl_lang_desc.setWordWrap(True)
        lang_layout.addWidget(self.lbl_lang_desc)
        layout.addWidget(self.grp_lang)

        # 2. 開機自啟動
        self.grp_autostart = QGroupBox(t("autostart_group_title"))
        as_layout = QVBoxLayout(self.grp_autostart)
        self.chk_autostart = QCheckBox(t("autostart_check"))
        as_layout.addWidget(self.chk_autostart)
        layout.addWidget(self.grp_autostart)

        # 3. Word 風格全介面文字大小調節
        self.grp_font_size = QGroupBox("🔤 全介面文字大小調節 (Word 字級與無段縮放)")
        fs_layout = QVBoxLayout(self.grp_font_size)
        fs_layout.setSpacing(10)

        fs_row = QHBoxLayout()
        lbl_fs = QLabel("字號 (pt) 與縮放：")
        fs_row.addWidget(lbl_fs)

        cur_pt = current_app_pt()
        self.word_font_toolbar = WordFontSizeToolbarWidget(cur_pt, self)
        self.word_font_toolbar.sig_font_pt_changed.connect(self._on_dialog_font_pt_changed)
        self.word_font_toolbar.sig_step_requested.connect(self._on_dialog_font_step)
        fs_row.addWidget(self.word_font_toolbar)

        self.word_zoom_slider = WordStatusZoomWidget(cur_pt, self)
        self.word_zoom_slider.sig_font_pt_changed.connect(self._on_dialog_font_pt_changed)
        self.word_zoom_slider.sig_step_requested.connect(self._on_dialog_font_step)
        fs_row.addWidget(self.word_zoom_slider)

        btn_reset_fs = QPushButton("重設預設 (13pt / 100%)")
        btn_reset_fs.setObjectName("secondaryBtn")
        btn_reset_fs.setCursor(Qt.PointingHandCursor)
        btn_reset_fs.clicked.connect(lambda: self._on_dialog_font_pt_changed(BASE_FONT_PT))
        fs_row.addWidget(btn_reset_fs)
        fs_row.addStretch()
        fs_layout.addLayout(fs_row)

        lbl_fs_hint = QLabel(
            "💡 支援像 Microsoft Word 一樣直接點選字號 (8 ~ 72pt)、手動輸入數字、"
            "點擊 <b>A▲ / A▼</b>、拖曳縮放滑桿，或在主視窗任意位置按住 <b>Ctrl + 滑鼠滾輪</b>（以及 <b>Ctrl++ / Ctrl+- / Ctrl+0</b>）即時縮放所有文字。"
        )
        lbl_fs_hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        lbl_fs_hint.setWordWrap(True)
        fs_layout.addWidget(lbl_fs_hint)
        layout.addWidget(self.grp_font_size)

        layout.addStretch()
        return widget

    def _on_dialog_font_step(self, step: int):
        new_pt = next_word_size(current_app_pt(), step)
        self._on_dialog_font_pt_changed(new_pt)

    def _on_dialog_font_pt_changed(self, pt: float):
        self.word_font_toolbar.set_font_pt(pt)
        self.word_zoom_slider.set_font_pt(pt)
        if self.parent() is not None and hasattr(self.parent(), "set_ui_font_size"):
            self.parent().set_ui_font_size(pt)
        apply_scale_to_widget_tree(self, pt_to_scale(pt))

    def _create_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info_box = QFrame()
        info_box.setStyleSheet("background: rgba(30, 58, 138, 0.2); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; padding: 10px;")
        ib_layout = QVBoxLayout(info_box)
        ib_layout.setContentsMargins(8, 8, 8, 8)
        
        lbl_info = QLabel("<b>🔑 多組 API Provider 與模型接入中心</b><br><span style='color:#94a3b8; font-size:12px;'>支援 Google Gemini、OpenAI、Anthropic Claude、DeepSeek、本地 Ollama 等多組金鑰與自訂端點。</span>")
        lbl_info.setWordWrap(True)
        ib_layout.addWidget(lbl_info)
        layout.addWidget(info_box)

        btn_open_api_mgr = QPushButton("🔑 開啟完整 API Key 管理器 (新增 / 測試連線 / 自動獲取模型)")
        btn_open_api_mgr.setObjectName("primaryBtn")
        btn_open_api_mgr.setCursor(Qt.PointingHandCursor)
        btn_open_api_mgr.clicked.connect(self._open_embedded_api_manager)
        layout.addWidget(btn_open_api_mgr)

        # 顯示當前已配置的金鑰摘要
        self.lbl_api_summary = QLabel("讀取金鑰清單中...")
        self.lbl_api_summary.setStyleSheet("background: #0e1015; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 12px; font-size: 12.5px; color: #cbd5e1;")
        self.lbl_api_summary.setWordWrap(True)
        layout.addWidget(self.lbl_api_summary, stretch=1)

        return widget

    def _create_discord_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.chk_discord_enabled = QCheckBox(t("discord_enabled_check"))
        layout.addWidget(self.chk_discord_enabled)

        form = QFormLayout()
        form.setSpacing(10)

        self.lbl_dc_token = QLabel(t("discord_token_label"))
        self.input_dc_token = QLineEdit()
        self.input_dc_token.setEchoMode(QLineEdit.Password)
        self.input_dc_token.setPlaceholderText("貼上 Discord Bot Token...")
        form.addRow(self.lbl_dc_token, self.input_dc_token)

        self.lbl_dc_channel = QLabel(t("discord_channel_label"))
        self.input_dc_channel = QLineEdit()
        self.input_dc_channel.setPlaceholderText("例如: 123456789012345678")
        form.addRow(self.lbl_dc_channel, self.input_dc_channel)

        self.lbl_dc_webhook = QLabel(t("discord_webhook_label"))
        self.input_dc_webhook = QLineEdit()
        self.input_dc_webhook.setPlaceholderText("https://discord.com/api/webhooks/...")
        form.addRow(self.lbl_dc_webhook, self.input_dc_webhook)

        layout.addLayout(form)
        layout.addStretch()
        return widget

    def _create_security_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.grp_pin = QGroupBox(t("security_pin_group"))
        pin_layout = QVBoxLayout(self.grp_pin)
        pin_layout.setSpacing(10)

        lbl_desc = QLabel(t("security_pin_desc"))
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        lbl_desc.setWordWrap(True)
        pin_layout.addWidget(lbl_desc)

        form = QFormLayout()
        self.lbl_new_pin = QLabel(t("new_pin_label"))
        self.input_new_pin = QLineEdit()
        self.input_new_pin.setEchoMode(QLineEdit.Password)
        self.input_new_pin.setPlaceholderText("輸入新的 4~8 位數字 PIN 碼")
        form.addRow(self.lbl_new_pin, self.input_new_pin)
        pin_layout.addLayout(form)

        self.chk_redact_windows = QCheckBox(t("redact_windows_check"))
        pin_layout.addWidget(self.chk_redact_windows)

        self.chk_strict_transactions = QCheckBox(t("strict_transaction_check"))
        pin_layout.addWidget(self.chk_strict_transactions)

        layout.addWidget(self.grp_pin)
        layout.addStretch()
        return widget

    def _create_dnd_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.grp_dnd = QGroupBox(t("dnd_group_title"))
        dnd_layout = QVBoxLayout(self.grp_dnd)
        dnd_layout.setSpacing(10)

        self.chk_dnd_game = QCheckBox(t("dnd_game_check"))
        dnd_layout.addWidget(self.chk_dnd_game)

        self.chk_dnd_video = QCheckBox(t("dnd_video_check"))
        dnd_layout.addWidget(self.chk_dnd_video)

        self.chk_dnd_homework = QCheckBox(t("dnd_protect_focus"))
        dnd_layout.addWidget(self.chk_dnd_homework)

        layout.addWidget(self.grp_dnd)
        layout.addStretch()
        return widget

    def _create_google_habit_tab(self) -> QWidget:
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        # 1. Google 帳戶與 Workspace 登入授權區塊
        grp_google = QGroupBox("🔑 Google 帳戶授權與雲端服務 (Google Workspace)")
        g_layout = QVBoxLayout(grp_google)
        g_layout.setSpacing(10)

        self.lbl_google_auth_status = QLabel("")
        self.lbl_google_auth_status.setStyleSheet("font-size: 13px; font-weight: 600;")
        g_layout.addWidget(self.lbl_google_auth_status)

        btn_row_auth = QHBoxLayout()
        self.btn_google_signin = GoogleSignInButton()
        self.btn_google_signin.clicked.connect(self._on_start_google_login)
        btn_row_auth.addWidget(self.btn_google_signin)
        btn_row_auth.addStretch(1)

        btn_import_creds = QPushButton("📂 匯入 credentials.json")
        btn_import_creds.setObjectName("secondaryBtn")
        btn_import_creds.setToolTip("第一次使用前，需匯入從 Google Cloud Console 下載的 OAuth 用戶端憑證")
        btn_import_creds.clicked.connect(self._on_import_google_credentials)
        btn_row_auth.addWidget(btn_import_creds)
        g_layout.addLayout(btn_row_auth)

        # 常用 Google 服務一鍵開啟
        lbl_quick_open = QLabel("快捷開啟 Google 雲端服務（使用本機登入態）：")
        lbl_quick_open.setStyleSheet("color: #94a3b8; font-size: 12px; margin-top: 6px;")
        g_layout.addWidget(lbl_quick_open)

        btn_row_services = QHBoxLayout()
        for svc_name, svc_key in [("✉️ Gmail", "gmail"), ("📁 Drive 雲端硬碟", "drive"), ("📅 Calendar 日曆", "calendar"), ("📝 Docs 文件", "docs"), ("📊 Sheets 試算表", "sheets")]:
            btn_svc = QPushButton(svc_name)
            btn_svc.setObjectName("secondaryBtn")
            btn_svc.clicked.connect(lambda checked, s=svc_key: webbrowser.open(google_suite.get_service_url(s)))
            btn_row_services.addWidget(btn_svc)
        g_layout.addLayout(btn_row_services)

        layout.addWidget(grp_google)

        # 2. 個人習慣快速同步
        grp_habit = QGroupBox("⚡ 個人習慣與偏好快速同步 (Habits Sync)")
        h_layout = QVBoxLayout(grp_habit)
        h_layout.setSpacing(10)

        lbl_habit_desc = QLabel(
            "透過本機已登入的 Chrome / Edge 歷史快照或 Google 雲端記錄，零密碼提取你的常用工具、工作活躍時段與專案偏好，\n"
            "自動生成認知畫像注入 Agent 大腦，使助手回覆與操作完美貼合個人習慣。"
        )
        lbl_habit_desc.setStyleSheet("color: #cbd5e1; font-size: 12.5px; line-height: 1.4;")
        h_layout.addWidget(lbl_habit_desc)

        btn_row_sync = QHBoxLayout()
        btn_sync_local = QPushButton("⚡ 一鍵同步本機習慣 (Chrome / Edge 免密碼快照)")
        btn_sync_local.setStyleSheet("background-color: #059669; color: white; font-weight: 600; padding: 8px 14px;")
        btn_sync_local.clicked.connect(self._on_sync_local_habits)
        btn_row_sync.addWidget(btn_sync_local)

        btn_sync_cloud = QPushButton("☁️ 同步 Google 雲端專案與日曆")
        btn_sync_cloud.setObjectName("secondaryBtn")
        btn_sync_cloud.clicked.connect(self._on_sync_cloud_habits)
        btn_row_sync.addWidget(btn_sync_cloud)
        h_layout.addLayout(btn_row_sync)

        self.txt_habit_summary = QTextEdit()
        self.txt_habit_summary.setReadOnly(True)
        self.txt_habit_summary.setMaximumHeight(140)
        self.txt_habit_summary.setStyleSheet("""
            QTextEdit {
                background-color: #0b0d13;
                color: #38bdf8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 12px;
                padding: 6px;
            }
        """)
        h_layout.addWidget(self.txt_habit_summary)

        layout.addWidget(grp_habit)

        # 3. 個人隱私資料夾與雲端漫遊 (User Profile Vault)
        grp_vault = QGroupBox("🔒 個人隱私資料夾與雲端漫遊 (User Profile Vault)")
        v_layout = QVBoxLayout(grp_vault)
        v_layout.setSpacing(10)

        lbl_vault_desc = QLabel(
            "您的個資、長期記憶、習慣畫像與偏好設定已單獨隔離存放於專屬資料夾（預設 <code>user_profile/</code>），"
            "受 <b>.gitignore</b> 與 <b>Agent 防外傳攔截器</b>雙重保護，絕不隨程式碼或一般指令上傳。<br>"
            "您可以將此資料夾放到個人雲端（或登入 Google 備份），登入時系統會先詢問您再將資料安全連回。"
        )
        lbl_vault_desc.setWordWrap(True)
        lbl_vault_desc.setStyleSheet("color: #cbd5e1; font-size: 12.5px; line-height: 1.4;")
        v_layout.addWidget(lbl_vault_desc)

        self.lbl_profile_dir_status = QLabel("")
        self.lbl_profile_dir_status.setWordWrap(True)
        self.lbl_profile_dir_status.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")
        v_layout.addWidget(self.lbl_profile_dir_status)

        form_persona = QFormLayout()
        form_persona.setLabelAlignment(Qt.AlignLeft)
        self.input_user_nickname = QLineEdit()
        self.input_user_nickname.setPlaceholderText("例如：Tim / 老闆（存於 user_profile/personal_info.json）")
        form_persona.addRow("您的稱呼：", self.input_user_nickname)

        self.input_user_role = QLineEdit()
        self.input_user_role.setPlaceholderText("例如：全端工程師 / 產品經理 / 創業者")
        form_persona.addRow("角色與專業：", self.input_user_role)

        self.input_user_instructions = QLineEdit()
        self.input_user_instructions.setPlaceholderText("例如：回答保持簡潔、優先給程式碼、使用繁體中文")
        form_persona.addRow("個人化偏好指示：", self.input_user_instructions)
        v_layout.addLayout(form_persona)

        self.chk_cloud_auto_prompt = QCheckBox("登入雲端帳號或掛載雲端資料夾時，自動詢問是否連回個人化資料")
        self.chk_cloud_auto_prompt.setChecked(True)
        v_layout.addWidget(self.chk_cloud_auto_prompt)

        row_vault_btns1 = QHBoxLayout()
        btn_save_persona = QPushButton("💾 儲存個人化資訊")
        btn_save_persona.setObjectName("primaryBtn")
        btn_save_persona.clicked.connect(self._on_save_personal_info)
        row_vault_btns1.addWidget(btn_save_persona)

        btn_open_vault = QPushButton("📂 開啟個資資料夾")
        btn_open_vault.setObjectName("secondaryBtn")
        btn_open_vault.clicked.connect(self._on_open_profile_dir)
        row_vault_btns1.addWidget(btn_open_vault)

        btn_mount_vault = QPushButton("🔗 變更/連結本機雲端資料夾")
        btn_mount_vault.setObjectName("secondaryBtn")
        btn_mount_vault.setToolTip("可選擇 Google Drive / OneDrive / Dropbox 在本機的同步資料夾，直接實現雲端漫遊")
        btn_mount_vault.clicked.connect(self._on_change_profile_dir)
        row_vault_btns1.addWidget(btn_mount_vault)
        v_layout.addLayout(row_vault_btns1)

        row_vault_btns2 = QHBoxLayout()
        btn_cloud_backup = QPushButton("☁️ 備份個人化資料至 Google 雲端")
        btn_cloud_backup.setStyleSheet("background-color: #2563eb; color: white; font-weight: 600; padding: 7px 12px;")
        btn_cloud_backup.clicked.connect(self._on_backup_profile_to_cloud)
        row_vault_btns2.addWidget(btn_cloud_backup)

        btn_cloud_restore = QPushButton("📥 檢查雲端並詢問連回個人資料")
        btn_cloud_restore.setObjectName("secondaryBtn")
        btn_cloud_restore.clicked.connect(self._on_restore_profile_from_cloud)
        row_vault_btns2.addWidget(btn_cloud_restore)
        v_layout.addLayout(row_vault_btns2)

        layout.addWidget(grp_vault)
        layout.addStretch()

        scroll.setWidget(content)
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(scroll)

        self._refresh_google_and_habits_ui()
        return top_widget

    # ------------------------------------------------------------------
    # 🔐 權限與功能
    # ------------------------------------------------------------------
    def _create_permissions_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)
        hint_style = "color: #94a3b8; font-size: 12px; font-weight: 400;"

        # 1. Google 功能權限
        grp_g = QGroupBox("🌐 Google 功能權限")
        g_layout = QVBoxLayout(grp_g)
        g_hint = QLabel("勾選要開放給 Syntra 的 Google 功能。登入時只會向 Google 要求勾選的權限；"
                        "<b>變更後需按「套用並重新登入」才會生效</b>。")
        g_hint.setWordWrap(True)
        g_hint.setStyleSheet(hint_style)
        g_layout.addWidget(g_hint)
        self.perm_google_checks: Dict[str, QCheckBox] = {}
        for key, label, desc, _scope, _tools in GOOGLE_SCOPE_OPTIONS:
            chk = QCheckBox(f"{label}　—　{desc}")
            self.perm_google_checks[key] = chk
            g_layout.addWidget(chk)
        g_btns = QHBoxLayout()
        btn_relogin = QPushButton("套用並重新登入 Google")
        btn_relogin.setObjectName("primaryBtn")
        btn_relogin.clicked.connect(self._on_apply_google_scopes)
        btn_revoke = QPushButton("登出並撤銷 Google 授權")
        btn_revoke.setObjectName("secondaryBtn")
        btn_revoke.clicked.connect(self._on_revoke_google)
        g_btns.addWidget(btn_relogin)
        g_btns.addWidget(btn_revoke)
        g_btns.addStretch()
        g_layout.addLayout(g_btns)
        layout.addWidget(grp_g)

        # 2. AI 可使用的應用程式（自動掃描本機應用程式 + 開關切換，預設除 Google 外全部關閉）
        grp_apps = QGroupBox("📱 AI 可使用的應用程式（本機應用程式開關）")
        apps_layout = QVBoxLayout(grp_apps)
        apps_hint = QLabel(
            "系統已自動讀取電腦上安裝的所有應用程式（桌面捷徑、開始選單與系統安裝清單）。<br>"
            "• <b>預設規則：除了 Google 相關應用程式（如 Chrome、Gemini）預設開啟外，其餘應用程式預設皆為關閉</b>。<br>"
            "• 請直接勾選開關決定哪些軟體允許 AI 直接開啟與操作；未開啟的軟體在使用前會跳出「允許請求」由您決定。"
        )
        apps_hint.setWordWrap(True)
        apps_hint.setStyleSheet(hint_style)
        apps_layout.addWidget(apps_hint)

        filter_row = QHBoxLayout()
        self.input_search_apps = QLineEdit()
        self.input_search_apps.setPlaceholderText("🔍 搜尋本機應用程式（輸入名稱、發行商或來源過濾）...")
        self.input_search_apps.textChanged.connect(self._on_filter_apps_list)
        filter_row.addWidget(self.input_search_apps, stretch=1)

        btn_rescan_apps = QPushButton("🔄 重新掃描本機程式")
        btn_rescan_apps.setObjectName("secondaryBtn")
        btn_rescan_apps.clicked.connect(lambda: self._rescan_and_populate_apps(force_refresh=True))
        filter_row.addWidget(btn_rescan_apps)

        btn_reset_google_only = QPushButton("🌐 僅開啟 Google (預設)")
        btn_reset_google_only.setObjectName("secondaryBtn")
        btn_reset_google_only.setToolTip("將所有非 Google 應用程式設為關閉，僅保留 Google 相關應用程式開啟")
        btn_reset_google_only.clicked.connect(self._on_reset_apps_google_only)
        filter_row.addWidget(btn_reset_google_only)
        apps_layout.addLayout(filter_row)

        self.lbl_apps_count_summary = QLabel("")
        self.lbl_apps_count_summary.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 600;")
        apps_layout.addWidget(self.lbl_apps_count_summary)

        self.list_allowed_apps = QListWidget()
        self.list_allowed_apps.setMinimumHeight(230)
        self.list_allowed_apps.setMaximumHeight(280)
        self.list_allowed_apps.setStyleSheet(
            "QListWidget { background: #1c202c; border: 1px solid rgba(255,255,255,0.12); border-radius: 6px; color: #f1f5f9; padding: 4px; }"
            "QListWidget::item { padding: 5px 6px; border-bottom: 1px solid rgba(255,255,255,0.05); }"
            "QListWidget::item:hover { background: rgba(56, 189, 248, 0.12); }"
        )
        self.list_allowed_apps.itemChanged.connect(self._on_app_switch_toggled)
        apps_layout.addWidget(self.list_allowed_apps)

        apps_row = QHBoxLayout()
        self.combo_add_app = QComboBox()
        self.combo_add_app.setEditable(True)
        for key, (display, _words) in KNOWN_APPS.items():
            self.combo_add_app.addItem(display, key)
        self.combo_add_app.setCurrentIndex(-1)
        self.combo_add_app.lineEdit().setPlaceholderText("若清單中未列出免安裝程式，可在此輸入名稱或 .exe 路徑手動加入並開啟")
        apps_row.addWidget(self.combo_add_app, stretch=1)
        btn_add_app = QPushButton("＋ 手動加入並開啟")
        btn_add_app.setObjectName("secondaryBtn")
        btn_add_app.clicked.connect(self._on_add_allowed_app)
        apps_row.addWidget(btn_add_app)
        apps_layout.addLayout(apps_row)
        layout.addWidget(grp_apps)

        # 3. AI 代理操作權限
        grp_a = QGroupBox("🤖 AI 代理操作權限")
        a_layout = QVBoxLayout(grp_a)
        a_hint = QLabel("決定 AI 每一類操作可以「允許」直接執行、「每次詢問」先跳出批准視窗，或「禁止」。")
        a_hint.setWordWrap(True)
        a_hint.setStyleSheet(hint_style)
        a_layout.addWidget(a_hint)
        a_form = QFormLayout()
        a_form.setLabelAlignment(Qt.AlignLeft)
        self.perm_agent_combos: Dict[str, QComboBox] = {}
        for key, label, desc, _default, _tools in AGENT_PERMISSION_CATEGORIES:
            lbl = QLabel(f"<b>{label}</b><br><span style='color:#94a3b8;font-size:11.5px'>{desc}</span>")
            lbl.setWordWrap(True)
            combo = QComboBox()
            for value in (ALLOW, ASK, DENY):
                combo.addItem(POLICY_LABELS[value], value)
            combo.setMinimumWidth(120)
            self.perm_agent_combos[key] = combo
            a_form.addRow(lbl, combo)
        a_layout.addLayout(a_form)
        layout.addWidget(grp_a)

        # 4. 防護功能開關
        grp_f = QGroupBox("🛡️ 防護功能")
        f_layout = QVBoxLayout(grp_f)
        f_hint = QLabel("關閉上層功能時，底下的選項都會一起停用。<b>背景監控類功能需重新啟動 Syntra 才會生效</b>。")
        f_hint.setWordWrap(True)
        f_hint.setStyleSheet(hint_style)
        f_layout.addWidget(f_hint)
        self.perm_feature_checks: Dict[str, QCheckBox] = {}
        for parent, p_label, p_desc, kids in FEATURE_TREE:
            p_chk = QCheckBox(f"{p_label}　—　{p_desc}")
            p_chk.setStyleSheet("font-weight: 700;")
            self.perm_feature_checks[parent] = p_chk
            f_layout.addWidget(p_chk)
            child_box = QWidget()
            c_layout = QVBoxLayout(child_box)
            c_layout.setContentsMargins(28, 0, 0, 6)
            c_layout.setSpacing(4)
            for key, k_label, k_desc, _tools in kids:
                c_chk = QCheckBox(f"{k_label}　—　{k_desc}")
                self.perm_feature_checks[f"{parent}.{key}"] = c_chk
                c_layout.addWidget(c_chk)
            p_chk.toggled.connect(child_box.setEnabled)
            f_layout.addWidget(child_box)
        layout.addWidget(grp_f)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    # ------------------------------------------------------------------
    # 🧩 選配模組商店 (Mod / DLC Optional Add-ons)
    # ------------------------------------------------------------------
    def _create_addons_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        grp_builtin = QGroupBox("⚡ 主 Agent 已內建日常電腦助手功能（無須額外安裝）")
        b_layout = QVBoxLayout(grp_builtin)
        lbl_builtin = QLabel(
            "• <b>智慧桌面与下載區整理</b> (<code>daily_organize_files</code> / <code>daily_undo_organize</code>)：自動分類雜亂檔案並支援一鍵還原。<br>"
            "• <b>日常情境模式切換</b> (<code>daily_switch_scene</code>)：一鍵切換工作、會議簡報、下班追劇娛樂與休息模式。<br>"
            "• <b>數位健康與用機回顧</b> (<code>daily_wellbeing_report</code>)：統計各類應用程式使用時長與護眼建議。"
        )
        lbl_builtin.setWordWrap(True)
        lbl_builtin.setStyleSheet("color: #cbd5e1; font-size: 12.5px; line-height: 1.4;")
        b_layout.addWidget(lbl_builtin)
        layout.addWidget(grp_builtin)

        grp_dlc = QGroupBox("🧩 可選配專業模組（Mod / DLC 式：預設不強裝，要用才開）")
        d_layout = QVBoxLayout(grp_dlc)
        lbl_dlc_hint = QLabel(
            "就像防毒模組 (Guardian) 一樣，以下垂直領域模組（如<b>個人財務記帳報稅</b>、<b>學術研究文獻</b>、<b>健康打卡</b>）"
            "採選配設計。啟用前會先顯示 <code>module.json</code> 權限知情同意書，且模組產生的個資一律隔離存放於 <code>user_profile/</code>。"
        )
        lbl_dlc_hint.setWordWrap(True)
        lbl_dlc_hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        d_layout.addWidget(lbl_dlc_hint)

        self.addons_list_container = QWidget()
        self.addons_list_layout = QVBoxLayout(self.addons_list_container)
        self.addons_list_layout.setContentsMargins(0, 4, 0, 4)
        self.addons_list_layout.setSpacing(8)
        d_layout.addWidget(self.addons_list_container)

        row_dlc_btns = QHBoxLayout()
        btn_web_redeem = QPushButton("🌐 前往官網兌換 / 下載 DLC")
        btn_web_redeem.setObjectName("primaryBtn")
        btn_web_redeem.clicked.connect(self._on_open_dlc_redeem_page)
        row_dlc_btns.addWidget(btn_web_redeem)

        btn_online_redeem = QPushButton("🔑 輸入兌換碼線上解鎖")
        btn_online_redeem.setObjectName("primaryBtn")
        btn_online_redeem.clicked.connect(self._on_online_redeem_dlc)
        row_dlc_btns.addWidget(btn_online_redeem)

        btn_import_zip = QPushButton("📦 匯入 DLC 包 / 授權檔 (.zip / .json)")
        btn_import_zip.setObjectName("primaryBtn")
        btn_import_zip.clicked.connect(self._on_import_dlc_package_or_license)
        row_dlc_btns.addWidget(btn_import_zip)

        btn_scan_dl = QPushButton("🔍 掃描「下載」資料夾")
        btn_scan_dl.setObjectName("secondaryBtn")
        btn_scan_dl.clicked.connect(self._on_scan_downloads_for_dlc)
        row_dlc_btns.addWidget(btn_scan_dl)

        btn_import_dlc = QPushButton("➕ 從資料夾匯入")
        btn_import_dlc.setObjectName("secondaryBtn")
        btn_import_dlc.clicked.connect(self._on_import_external_addon)
        row_dlc_btns.addWidget(btn_import_dlc)

        btn_refresh_dlc = QPushButton("🔄 重新掃描")
        btn_refresh_dlc.setObjectName("secondaryBtn")
        btn_refresh_dlc.clicked.connect(self._refresh_addons_ui)
        row_dlc_btns.addWidget(btn_refresh_dlc)
        row_dlc_btns.addStretch()
        d_layout.addLayout(row_dlc_btns)

        layout.addWidget(grp_dlc)
        layout.addStretch()
        scroll.setWidget(content)
        self._refresh_addons_ui()
        return scroll

    def _refresh_addons_ui(self):
        if not hasattr(self, "addons_list_layout"):
            return
        while self.addons_list_layout.count():
            item = self.addons_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 官方 Security Shield DLC 獨立卡片
        from core.licensing import has_valid_dlc_license
        shield_dir = Path(__file__).resolve().parent.parent / "dlc" / "official_security_shield"
        shield_installed = shield_dir.exists()
        shield_licensed, shield_reason = has_valid_dlc_license(self.settings_manager, "syntra.dlc.security_shield")
        s_card = QFrame()
        s_card.setStyleSheet(
            "QFrame { background: #142220; border: 1px solid rgba(16,185,129,0.35); border-radius: 8px; padding: 8px; }"
        )
        s_lay = QVBoxLayout(s_card)
        s_top = QHBoxLayout()
        if shield_installed and shield_licensed:
            s_badge = "<span style='color:#10b981;font-weight:700;'>🟢 已安裝並通過 Ed25519 授權</span>"
        elif shield_installed:
            s_badge = f"<span style='color:#f59e0b;font-weight:700;'>🔒 已安裝但未授權（{shield_reason}）</span>"
        else:
            s_badge = "<span style='color:#94a3b8;font-weight:700;'>⚪ 尚未安裝（主程式維持純淨開源）</span>"
        s_lbl = QLabel(
            f"<span style='font-size:13.5px;font-weight:700;color:#f1f5f9'>🛡️ Security Shield DLC（進階防護套件）</span> — {s_badge}"
        )
        s_top.addWidget(s_lbl, stretch=1)
        if not shield_licensed:
            btn_go = QPushButton("🌐 前往官網兌換")
            btn_go.setObjectName("primaryBtn")
            btn_go.clicked.connect(self._on_open_dlc_redeem_page)
            s_top.addWidget(btn_go)
        if shield_installed:
            btn_rm_shield = QPushButton("🗑️ 刪除 Security DLC")
            btn_rm_shield.setObjectName("secondaryBtn")
            btn_rm_shield.clicked.connect(self._on_delete_official_security_dlc)
            s_top.addWidget(btn_rm_shield)
        s_lay.addLayout(s_top)
        self.addons_list_layout.addWidget(s_card)

        modules = addon_module_manager.discover_modules()
        for mod in modules:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #1c202c; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px; }"
            )
            c_lay = QVBoxLayout(card)
            c_lay.setSpacing(6)

            top_row = QHBoxLayout()
            is_en = bool(mod.get("enabled"))
            badge = "🟢 已啟用" if is_en else "⚪ 選配未啟用"
            badge_color = "#4ade80" if is_en else "#94a3b8"
            lbl_title = QLabel(
                f"<span style='font-size:13.5px;font-weight:700;color:#f1f5f9'>{mod.get('name')}</span> "
                f"<span style='font-size:11.5px;color:#64748b'>v{mod.get('version', '1.0.0')} [{mod.get('category', 'addon')}]</span> "
                f"<span style='font-size:12px;font-weight:700;color:{badge_color}'>— {badge}</span>"
            )
            top_row.addWidget(lbl_title, stretch=1)

            btn_info = QPushButton("📜 權限與範疇說明")
            btn_info.setObjectName("secondaryBtn")
            btn_info.clicked.connect(lambda _chk=False, m=mod: self._show_addon_consent_dialog(m, view_only=True))
            top_row.addWidget(btn_info)

            btn_toggle = QPushButton("⏹️ 停用模組" if is_en else "🚀 啟用模組")
            btn_toggle.setObjectName("secondaryBtn" if is_en else "primaryBtn")
            btn_toggle.clicked.connect(lambda _chk=False, m=mod: self._on_toggle_addon_module(m))
            top_row.addWidget(btn_toggle)

            btn_delete = QPushButton("🗑️ 刪除")
            btn_delete.setObjectName("secondaryBtn")
            btn_delete.clicked.connect(lambda _chk=False, m=mod: self._on_delete_addon_module(m))
            top_row.addWidget(btn_delete)
            c_lay.addLayout(top_row)

            lbl_sum = QLabel(str(mod.get("summary", "")))
            lbl_sum.setWordWrap(True)
            lbl_sum.setStyleSheet("color: #cbd5e1; font-size: 12px;")
            c_lay.addWidget(lbl_sum)

            self.addons_list_layout.addWidget(card)

    def _show_addon_consent_dialog(self, mod: Dict[str, Any], view_only: bool = False) -> bool:
        perms = mod.get("permissions") or []
        not_doing = mod.get("not_doing") or []
        perm_lines = []
        for p in perms:
            perm_lines.append(
                f"<li><b>{p.get('title', p.get('key'))}</b><br>"
                f"• 為什麼需要：{p.get('why', '')}<br>"
                f"• 作用位置：{p.get('where', '')}<br>"
                f"• 執行內容：{p.get('what', '')}</li>"
            )
        not_lines = [f"<li>❌ {n}</li>" for n in not_doing]

        html = (
            f"<h3>{mod.get('name')} (v{mod.get('version', '1.0.0')})</h3>"
            f"<p>{mod.get('summary', '')}</p>"
            f"<p><b>範疇聲明：</b>{mod.get('scope_statement', '')}</p>"
            f"<b>本模組請求的權限：</b><ul>{''.join(perm_lines) or '<li>無特殊系統權限</li>'}</ul>"
            f"<b>本模組保證不做：</b><ul>{''.join(not_lines)}</ul>"
        )
        box = QMessageBox(self)
        box.setWindowTitle("選配模組 — 權限與範疇知情同意")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        if view_only:
            box.addButton("關閉", QMessageBox.AcceptRole)
            box.exec_()
            return False
        btn_agree = box.addButton("✅ 我已了解並同意啟用", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is btn_agree

    def _on_toggle_addon_module(self, mod: Dict[str, Any]):
        mod_id = str(mod.get("id"))
        currently_enabled = bool(mod.get("enabled"))
        if not currently_enabled:
            if not self._show_addon_consent_dialog(mod, view_only=False):
                return
            res = addon_module_manager.set_module_enabled(mod_id, True)
            if not res.get("ok"):
                QMessageBox.warning(self, "無法啟用", f"🔒 {res.get('error', '請先解鎖授權')}")
                return
            self._refresh_addons_ui()
            QMessageBox.information(
                self,
                "選配模組已啟用",
                f"🎉 已啟用「{mod.get('name')}」！\n專屬工具已動態掛載進主 Agent，相關個人資料將安全隔離於 user_profile/。",
            )
            rec_mcps = res.get("recommended_mcps") or []
            if rec_mcps:
                ans = QMessageBox.question(
                    self,
                    "推薦配套工具 (一鍵掛載)",
                    f"此模組推薦搭配：{', '.join(rec_mcps)}（含 Chrome DevTools MCP 進行網頁除錯與效能測試，Apache-2.0 授權）。\n是否立即為您一鍵自動啟用？",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if ans == QMessageBox.Yes:
                    try:
                        from core.mcp_skill_manager import McpSkillManager
                        mcp_mgr = McpSkillManager()
                        for mid in rec_mcps:
                            mcp_mgr.ensure_recommended_mcp(mid, enable=True)
                        QMessageBox.information(self, "已自動啟用", f"✅ 已為您掛載並啟用推薦 MCP：{', '.join(rec_mcps)}")
                    except Exception as e:
                        QMessageBox.warning(self, "啟用失敗", f"無法自動啟用推薦 MCP：{e}")
        else:
            addon_module_manager.set_module_enabled(mod_id, False)
            self._refresh_addons_ui()
            QMessageBox.information(self, "選配模組已停用", f"已停用「{mod.get('name')}」（您的歷史資料仍安全保留於 user_profile/）。")

    def _on_import_external_addon(self):
        chosen = QFileDialog.getExistingDirectory(self, "選擇含有 module.json 的外部選配模組資料夾", "")
        if not chosen:
            return
        res = addon_module_manager.install_external_module_folder(chosen)
        if res.get("ok"):
            self._refresh_addons_ui()
            QMessageBox.information(
                self,
                "模組包加裝成功",
                f"✅ 已成功匯入選配模組：{res.get('name')} ({res.get('id')})\n可於清單中檢視權限並勾選啟用！",
            )
        else:
            QMessageBox.warning(self, "模組匯入失敗", str(res.get("error", "未知錯誤")))

    def _on_open_dlc_redeem_page(self):
        import webbrowser
        webbrowser.open("https://syntraagent.keli260530.workers.dev/redeem")

    def _install_dlc_from_path(self, file_path: Path) -> tuple[bool, str]:
        import json
        import shutil
        import zipfile
        from core.licensing import save_dlc_license_token

        base_dir = Path(__file__).resolve().parent.parent
        suffix = file_path.suffix.lower()

        if suffix in (".json", ".lic", ".txt"):
            raw = file_path.read_text(encoding="utf-8").strip()
            token = raw
            dlc_id = "syntra.dlc.security_shield"
            if raw.startswith("{"):
                data = json.loads(raw)
                token = str(data.get("license_key") or data.get("token") or "").strip()
                dlc_id = str(data.get("dlc_id") or dlc_id).strip()
            ok, payload, msg = save_dlc_license_token(dlc_id, token, settings_manager=self.settings_manager)
            if not ok:
                return False, msg
            return True, f"授權驗章通過（模組：{payload.get('dlc_id', dlc_id)}）"

        if suffix == ".zip":
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                # 安全檢查：防止 Zip Slip 路徑穿越
                for member in names:
                    if member.startswith("/") or ".." in Path(member).parts:
                        return False, f"壓縮包內含不安全路徑：{member}"

                # 1) 若壓縮包內附帶 license.json，先驗章
                lic_msg = ""
                if "license.json" in names:
                    lic_data = json.loads(zf.read("license.json").decode("utf-8"))
                    token = str(lic_data.get("license_key") or lic_data.get("token") or "").strip()
                    dlc_id = str(lic_data.get("dlc_id") or "syntra.dlc.security_shield").strip()
                    ok, payload, msg = save_dlc_license_token(dlc_id, token, settings_manager=self.settings_manager)
                    if not ok:
                        return False, f"壓縮包授權簽章無效：{msg}"
                    lic_msg = f"\n✅ 授權已驗章寫入（{payload.get('plan', 'pro')}）"

                # 2) 解壓安全檔案到專案目錄
                if any(n.startswith("dlc/") or n.startswith("core/") for n in names):
                    for info in zf.infolist():
                        if info.is_dir() or info.filename == "license.json":
                            continue
                        target = (base_dir / info.filename).resolve()
                        if base_dir.resolve() not in target.parents:
                            return False, "偵測到越權解壓路徑"
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                    return True, f"已成功安裝官方 DLC 壓縮包！{lic_msg}"

                if "module.json" in names or any(n.endswith("/module.json") for n in names):
                    import tempfile
                    with tempfile.TemporaryDirectory() as tmpdir:
                        zf.extractall(tmpdir)
                        tmp_root = Path(tmpdir)
                        mod_dir = tmp_root if (tmp_root / "module.json").exists() else next(tmp_root.glob("*/module.json")).parent
                        res = addon_module_manager.install_external_module_folder(str(mod_dir))
                        if not res.get("ok"):
                            return False, str(res.get("error", "模組格式錯誤"))
                        return True, f"已匯入擴充模組：{res.get('name')}{lic_msg}"
                return False, "壓縮包格式不符（找不到 dlc/ 或 module.json）"

        return False, f"不支援的檔案格式：{suffix}"

    def _on_online_redeem_dlc(self):
        import json
        import platform
        import urllib.error
        import urllib.request
        from PyQt5.QtWidgets import QInputDialog
        from core.licensing import save_dlc_license_token

        code, ok = QInputDialog.getText(
            self,
            "線上兌換解鎖 DLC",
            "請輸入從官網取得的 DLC 兌換碼（將直接送往後端驗證，一組碼限用一次）：",
        )
        if not ok or not code.strip():
            return

        endpoint = "https://syntraagent.onrender.com/api/redeem"
        payload = json.dumps({
            "code": code.strip(),
            "redeemed_to": platform.node() or "syntra-desktop",
        }).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Syntra-Desktop/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            try:
                detail = json.loads(err_body).get("detail") or err_body
            except Exception:
                detail = err_body or str(he)
            QMessageBox.warning(self, "兌換失敗", f"❌ 後端拒絕核銷：\n{detail}")
            return
        except Exception as e:
            QMessageBox.warning(self, "連線失敗", f"❌ 無法連線至授權伺服器：\n{e}")
            return

        token = str(data.get("license_key") or data.get("token") or "").strip()
        dlc_id = str(data.get("dlc_id") or "syntra.dlc.project_architect").strip()
        if not token:
            QMessageBox.warning(self, "兌換失敗", "❌ 後端未回傳有效授權憑證。")
            return

        v_ok, v_payload, v_msg = save_dlc_license_token(dlc_id, token, settings_manager=self.settings_manager)
        ckey = str(data.get("content_key") or "").strip()
        if v_ok and ckey:
            from core.licensing import save_dlc_content_key
            save_dlc_content_key(dlc_id, ckey, settings_manager=self.settings_manager)
        self._refresh_addons_ui()
        if v_ok:
            QMessageBox.information(self, "解鎖成功", f"🎉 已通過後端核銷並驗章解鎖模組：{v_payload.get('dlc_id', dlc_id)}")
        else:
            QMessageBox.warning(self, "驗章失敗", f"❌ {v_msg}")

    def _on_import_dlc_package_or_license(self):
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "選擇官網下載的 DLC 壓縮包或授權檔",
            str(Path.home() / "Downloads"),
            "DLC / 授權檔 (*.zip *.json *.lic *.txt);;All Files (*)",
        )
        if not chosen:
            return
        ok, msg = self._install_dlc_from_path(Path(chosen))
        self._refresh_addons_ui()
        if ok:
            QMessageBox.information(self, "DLC 匯入成功", f"🎉 {msg}")
        else:
            QMessageBox.warning(self, "DLC 匯入失敗", f"❌ {msg}")

    def _on_scan_downloads_for_dlc(self):
        dl_dir = Path.home() / "Downloads"
        if not dl_dir.exists():
            QMessageBox.information(self, "掃描結果", "找不到使用者的「下載」資料夾。")
            return
        candidates = sorted(
            list(dl_dir.glob("syntra-dlc-*.zip")) + list(dl_dir.glob("syntra-license-*.json")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            QMessageBox.information(
                self,
                "未偵測到 DLC 檔案",
                "「下載」資料夾內尚未發現 syntra-dlc-*.zip 或 syntra-license-*.json。\n可點「🌐 前往官網兌換 / 下載 DLC」取得。",
            )
            return
        latest = candidates[0]
        reply = QMessageBox.question(
            self,
            "偵測到下載的 DLC 檔案",
            f"在「下載」資料夾發現最新檔案：\n{latest.name}\n\n要立即驗章並套用至 Syntra 嗎？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            ok, msg = self._install_dlc_from_path(latest)
            self._refresh_addons_ui()
            if ok:
                QMessageBox.information(self, "套用成功", f"🎉 {msg}")
            else:
                QMessageBox.warning(self, "套用失敗", f"❌ {msg}")

    def _on_delete_addon_module(self, mod: Dict[str, Any]):
        import shutil
        mod_id = str(mod.get("id") or "")
        mod_name = str(mod.get("name") or mod_id)
        mod_dir = Path(str(mod.get("dir") or ""))
        reply = QMessageBox.question(
            self,
            "確認刪除模組",
            f"確定要停用並永久刪除選配模組「{mod_name}」嗎？\n資料夾：{mod_dir}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        addon_module_manager.set_module_enabled(mod_id, False)
        if mod_dir.exists() and mod_dir.is_dir():
            shutil.rmtree(mod_dir, ignore_errors=True)
        self._refresh_addons_ui()
        QMessageBox.information(self, "模組已移除", f"🗑️ 已刪除模組「{mod_name}」。")

    def _on_delete_official_security_dlc(self):
        import json
        import shutil
        base_dir = Path(__file__).resolve().parent.parent
        shield_dir = base_dir / "dlc" / "official_security_shield"
        reply = QMessageBox.question(
            self,
            "確認移除 Security Shield DLC",
            "確定要移除本機的 Security Shield DLC 防護套件與本機授權憑證嗎？\n（主程式本體將完整保留，日後可隨時重新匯入）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if shield_dir.exists():
            shutil.rmtree(shield_dir, ignore_errors=True)
        lic_file = base_dir / "data" / "dlc_licenses.json"
        if lic_file.exists():
            try:
                data = json.loads(lic_file.read_text(encoding="utf-8"))
                data.pop("syntra.dlc.security_shield", None)
                lic_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        self._refresh_addons_ui()
        QMessageBox.information(self, "已移除", "🗑️ 已刪除本機 Security Shield DLC。")

    def _load_permissions_to_ui(self):
        raw = self.settings_manager.get_raw()
        perms = default_permissions()
        for section in perms:
            saved = (raw.get("permissions") or {}).get(section)
            if isinstance(saved, dict):
                perms[section].update(saved)
        for key, chk in self.perm_google_checks.items():
            chk.setChecked(bool(perms["google_scopes"].get(key, True)))
        for key, combo in self.perm_agent_combos.items():
            idx = combo.findData(perms["agent"].get(key, ALLOW))
            combo.setCurrentIndex(max(idx, 0))
        for key, chk in self.perm_feature_checks.items():
            chk.setChecked(bool(perms["features"].get(key, True)))
        for parent, *_ in FEATURE_TREE:  # 父項關閉時讓子項呈現停用狀態
            p_chk = self.perm_feature_checks[parent]
            p_chk.toggled.emit(p_chk.isChecked())
        self._rescan_and_populate_apps(force_refresh=False, raw_settings=raw)

    def _format_app_switch_label(
        self,
        name: str,
        checked: bool,
        source: str = "",
        publisher: str = "",
        is_google: bool = False,
    ) -> str:
        status = "🟢 [開啟]" if checked else "⚪ [關閉]"
        g_tag = " 🌐 Google" if is_google else ""
        meta_parts = [p for p in (source, publisher) if p]
        meta_str = f"  —  {' · '.join(meta_parts)}" if meta_parts else ""
        return f"{status}{g_tag}  {name}{meta_str}"

    def _rescan_and_populate_apps(self, force_refresh: bool = False, raw_settings: Optional[Dict[str, Any]] = None):
        raw = raw_settings if raw_settings is not None else self.settings_manager.get_raw()
        eff_allowed = compute_effective_allowed_apps(raw)
        allowed_keys = {a["key"] for a in eff_allowed if a.get("key")}

        scanned = scan_all_local_apps(force_refresh=force_refresh)
        self.list_allowed_apps.blockSignals(True)
        try:
            self.list_allowed_apps.clear()
            seen_keys = set()
            for app in scanned:
                key = app["key"]
                seen_keys.add(key)
                name = app.get("name") or key
                source = app.get("source") or "本機應用程式"
                publisher = app.get("publisher") or ""
                is_g = bool(app.get("is_google"))
                is_checked = key in allowed_keys
                self._insert_app_switch_item(
                    key=key,
                    name=name,
                    checked=is_checked,
                    source=source,
                    publisher=publisher,
                    is_google=is_g,
                    launch_target=app.get("launch_target", ""),
                )

            # 若使用者曾手動加入過不在掃描清單中的自訂程式，也一併保留顯示
            for custom in eff_allowed:
                ckey = custom.get("key", "")
                if ckey and ckey not in seen_keys:
                    cname = custom.get("name") or ckey
                    is_g = is_google_application(ckey, cname)
                    self._insert_app_switch_item(
                        key=ckey,
                        name=cname,
                        checked=True,
                        source="自訂加入",
                        publisher="",
                        is_google=is_g,
                    )
        finally:
            self.list_allowed_apps.blockSignals(False)

        self._update_apps_summary_label()
        if hasattr(self, "input_search_apps") and self.input_search_apps.text().strip():
            self._on_filter_apps_list(self.input_search_apps.text())

    def _insert_app_switch_item(
        self,
        key: str,
        name: str,
        checked: bool,
        source: str = "本機應用程式",
        publisher: str = "",
        is_google: bool = False,
        launch_target: str = "",
    ):
        item = QListWidgetItem(
            self._format_app_switch_label(name, checked, source=source, publisher=publisher, is_google=is_google)
        )
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        item.setData(Qt.UserRole, key)
        item.setData(Qt.UserRole + 1, name)
        item.setData(Qt.UserRole + 2, source)
        item.setData(Qt.UserRole + 3, publisher)
        item.setData(Qt.UserRole + 4, bool(is_google))
        if launch_target:
            item.setToolTip(f"應用程式：{name}\n識別碼：{key}\n執行目標：{launch_target}")
        self.list_allowed_apps.addItem(item)

    def _on_app_switch_toggled(self, item: QListWidgetItem):
        checked = item.checkState() == Qt.Checked
        name = item.data(Qt.UserRole + 1) or item.data(Qt.UserRole) or ""
        source = item.data(Qt.UserRole + 2) or ""
        publisher = item.data(Qt.UserRole + 3) or ""
        is_g = bool(item.data(Qt.UserRole + 4))
        self.list_allowed_apps.blockSignals(True)
        try:
            item.setText(self._format_app_switch_label(name, checked, source=source, publisher=publisher, is_google=is_g))
        finally:
            self.list_allowed_apps.blockSignals(False)
        self._update_apps_summary_label()

    def _update_apps_summary_label(self):
        if not hasattr(self, "lbl_apps_count_summary"):
            return
        total = self.list_allowed_apps.count()
        enabled_cnt = sum(
            1 for i in range(total) if self.list_allowed_apps.item(i).checkState() == Qt.Checked
        )
        self.lbl_apps_count_summary.setText(
            f"📦 已自動讀取本機 {total} 款應用程式 ｜ 🟢 目前已開啟 {enabled_cnt} 款 ‧ ⚪ 已關閉 {total - enabled_cnt} 款（預設僅開啟 Google）"
        )

    def _on_filter_apps_list(self, text: str):
        q = (text or "").strip().lower()
        for i in range(self.list_allowed_apps.count()):
            it = self.list_allowed_apps.item(i)
            haystack = " ".join([
                str(it.data(Qt.UserRole) or ""),
                str(it.data(Qt.UserRole + 1) or ""),
                str(it.data(Qt.UserRole + 2) or ""),
                str(it.data(Qt.UserRole + 3) or ""),
                str(it.toolTip() or ""),
            ]).lower()
            it.setHidden(bool(q and q not in haystack))

    def _on_reset_apps_google_only(self):
        self.list_allowed_apps.blockSignals(True)
        try:
            for i in range(self.list_allowed_apps.count()):
                it = self.list_allowed_apps.item(i)
                is_g = bool(it.data(Qt.UserRole + 4))
                it.setCheckState(Qt.Checked if is_g else Qt.Unchecked)
                name = it.data(Qt.UserRole + 1) or ""
                source = it.data(Qt.UserRole + 2) or ""
                publisher = it.data(Qt.UserRole + 3) or ""
                it.setText(self._format_app_switch_label(name, is_g, source=source, publisher=publisher, is_google=is_g))
        finally:
            self.list_allowed_apps.blockSignals(False)
        self._update_apps_summary_label()

    def _add_app_item(self, key: str, name: str):
        for i in range(self.list_allowed_apps.count()):
            it = self.list_allowed_apps.item(i)
            if it.data(Qt.UserRole) == key:
                it.setCheckState(Qt.Checked)
                return
        is_g = is_google_application(key, name)
        self._insert_app_switch_item(
            key=key,
            name=name,
            checked=True,
            source="手動加入",
            publisher="",
            is_google=is_g,
        )
        self._update_apps_summary_label()

    def _on_add_allowed_app(self):
        text = self.combo_add_app.currentText().strip()
        if not text:
            return
        idx = self.combo_add_app.findText(text)
        key, name = (self.combo_add_app.itemData(idx), text) if idx >= 0 else identify_app(text)
        if key:
            self._add_app_item(key, name)
        self.combo_add_app.setCurrentIndex(-1)
        self.combo_add_app.clearEditText()

    def _on_remove_allowed_app(self):
        for item in self.list_allowed_apps.selectedItems():
            item.setCheckState(Qt.Unchecked)

    def _collect_permissions(self) -> Dict[str, Any]:
        allowed_list = []
        denied_list = []
        for i in range(self.list_allowed_apps.count()):
            item = self.list_allowed_apps.item(i)
            key = item.data(Qt.UserRole)
            name = item.data(Qt.UserRole + 1)
            if not key:
                continue
            if item.checkState() == Qt.Checked:
                allowed_list.append({"key": key, "name": name})
            else:
                denied_list.append(key)
        return {
            "google_scopes": {k: c.isChecked() for k, c in self.perm_google_checks.items()},
            "agent": {k: c.currentData() for k, c in self.perm_agent_combos.items()},
            "features": {k: c.isChecked() for k, c in self.perm_feature_checks.items()},
            "apps": {"allowed": allowed_list, "denied": denied_list},
        }

    def _on_apply_google_scopes(self):
        self.settings_manager.update_settings({"permissions": self._collect_permissions()})
        if not enabled_google_scopes(self.settings_manager.get_raw()):
            QMessageBox.warning(self, "Google 功能權限", "至少要勾選一項 Google 功能才能登入。")
            return
        self._on_start_google_login()

    def _on_revoke_google(self):
        ans = QMessageBox.question(
            self, "登出並撤銷 Google 授權",
            "會通知 Google 撤銷 Syntra 的所有存取權，並刪除本機的登入憑證。\n"
            "之後 Gmail、雲端硬碟、日曆等功能都要重新登入才能使用。確定嗎？")
        if ans != QMessageBox.Yes:
            return
        ok, msg = revoke_google_access(google_suite)
        (QMessageBox.information if ok else QMessageBox.warning)(self, "登出並撤銷 Google 授權", msg)
        self._refresh_google_and_habits_ui()

    def _refresh_google_and_habits_ui(self):
        if not hasattr(self, "lbl_google_auth_status"):
            return
        if hasattr(self, "btn_google_signin"):
            self.btn_google_signin.set_signed_in(google_suite.is_authenticated())
        if google_suite.is_authenticated():
            self.lbl_google_auth_status.setText("🟢 <b>Google 帳號狀態：</b>已完成授權 (Workspace 全套 API 啟用中)")
            self.lbl_google_auth_status.setStyleSheet("color: #4ade80; font-size: 13px;")
        elif os.path.exists(google_suite.creds_path):
            self.lbl_google_auth_status.setText("🟡 <b>Google 帳號狀態：</b>已配置憑證檔，請點擊「使用 Google 帳戶登入」完成一次性登入")
            self.lbl_google_auth_status.setStyleSheet("color: #fbbf24; font-size: 13px;")
        else:
            self.lbl_google_auth_status.setText("⚪ <b>Google 帳號狀態：</b>尚未配置憑證 (可點擊「匯入 credentials.json」或直接開啟服務)")
            self.lbl_google_auth_status.setStyleSheet("color: #94a3b8; font-size: 13px;")

        ctx = habit_sync_engine.load_prompt_context()
        if ctx:
            self.txt_habit_summary.setPlainText(ctx)
        else:
            self.txt_habit_summary.setPlainText("尚未同步個人習慣。點擊上方「一鍵同步本機習慣」即可 3 秒內自動提取！")

        if hasattr(self, "lbl_profile_dir_status"):
            st = user_profile_manager.get_status()
            self.lbl_profile_dir_status.setText(
                f"🛡️ <b>目前個資隔離路徑：</b><code>{st['profile_dir']}</code><br>"
                f"（長期記憶：{st['memory_count']} 筆 ｜ 習慣畫像：{'已建立' if st['has_habits'] else '未建立'} ｜ 排程：{st['schedules_count']} 項）"
            )
            info = st.get("personal_info", {})
            self.input_user_nickname.setText(str(info.get("nickname", "")))
            self.input_user_role.setText(str(info.get("role", "")))
            self.input_user_instructions.setText(str(info.get("custom_instructions", "")))
            self.chk_cloud_auto_prompt.setChecked(bool(info.get("cloud_auto_prompt_on_login", True)))

    def _on_import_google_credentials(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "選取從 Google Cloud 下載的 credentials.json",
            "",
            "JSON Files (*.json)"
        )
        if file_path:
            err = check_client_secrets(file_path)
            if err:
                QMessageBox.warning(self, "憑證格式不符", err)
                return
            target_dir = os.path.dirname(google_suite.creds_path)
            os.makedirs(target_dir, exist_ok=True)
            shutil.copyfile(file_path, google_suite.creds_path)
            self._refresh_google_and_habits_ui()
            self._start_google_browser_login()  # 匯入完直接跳出 Google 登入畫面

    def _on_start_google_login(self):
        # 已登入時再按 = 重新登入（例如換帳號）
        if not os.path.exists(google_suite.creds_path):
            self._show_google_setup_guide()
            return
        self._start_google_browser_login()

    def _show_google_setup_guide(self):
        box = QMessageBox(self)
        box.setWindowTitle("第一次使用 Google 登入")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.setText(SETUP_GUIDE_HTML)
        btn_console = box.addButton("開啟 Google Cloud Console", QMessageBox.ActionRole)
        btn_import = box.addButton("匯入 credentials.json", QMessageBox.AcceptRole)
        box.addButton("稍後再說", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is btn_console:
            webbrowser.open(CONSOLE_URL)
        elif box.clickedButton() is btn_import:
            self._on_import_google_credentials()

    def _start_google_browser_login(self):
        if getattr(self, "_google_login_worker", None) is not None and self._google_login_worker.isRunning():
            return
        scopes = enabled_google_scopes(self.settings_manager.get_raw())
        if not scopes:
            QMessageBox.warning(self, "Google 登入", "所有 Google 功能權限都已關閉，請先到「🔐 權限與功能」勾選至少一項。")
            return
        # 先在主執行緒確認 Google / requests 套件能載入，失敗時直接顯示根本原因（含 __cause__），
        # 不必等到瀏覽器登入流程中途才失敗。
        try:
            import requests  # noqa: F401
            import google.auth.transport.requests  # noqa: F401
            import google_auth_oauthlib.flow  # noqa: F401
        except Exception as e:
            QMessageBox.warning(self, "Google 登入未完成", describe_import_error(e))
            return
        self.btn_google_signin.set_waiting(True)
        self.lbl_google_auth_status.setText("🔵 <b>Google 帳號狀態：</b>已在瀏覽器開啟 Google 登入頁，請選擇帳戶並允許存取…")
        self.lbl_google_auth_status.setStyleSheet("color: #60a5fa; font-size: 13px;")
        self._google_login_worker = GoogleLoginWorker(google_suite, scopes, self)
        self._google_login_worker.done.connect(self._on_google_login_done)
        self._google_login_worker.start()

    def _on_google_login_done(self, ok: bool, err: str):
        self.btn_google_signin.setEnabled(True)
        self._refresh_google_and_habits_ui()
        if ok:
            prompt_cloud_profile_after_login(self, google_suite, self.settings_manager)
        else:
            QMessageBox.warning(self, "Google 登入未完成", err)
        self._refresh_google_and_habits_ui()

    def _on_save_personal_info(self):
        user_profile_manager.update_personal_info({
            "nickname": self.input_user_nickname.text().strip(),
            "role": self.input_user_role.text().strip(),
            "custom_instructions": self.input_user_instructions.text().strip(),
            "cloud_auto_prompt_on_login": self.chk_cloud_auto_prompt.isChecked(),
        })
        self._refresh_google_and_habits_ui()
        QMessageBox.information(
            self,
            "個人化資訊已儲存",
            f"✅ 您的個人化資訊已安全寫入隔離資料夾：\n{user_profile_manager.personal_info_path}\n（此資料夾受防上傳保護，不會隨專案外洩）",
        )

    def _on_open_profile_dir(self):
        path = str(user_profile_manager.profile_dir)
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception:
            webbrowser.open(path)

    def _on_change_profile_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self,
            "選擇個人化與個資存放資料夾（可選 Google Drive / OneDrive 本機同步資料夾）",
            str(user_profile_manager.profile_dir),
        )
        if not chosen:
            return
        target_path = Path(chosen)
        has_existing = (
            (target_path / "personal_info.json").exists()
            or (target_path / "long_term_memory.json").exists()
            or (target_path / "user_habit_profile.json").exists()
        )
        copy_local = True
        if has_existing:
            ans = QMessageBox.question(
                self,
                "偵測到既有個人化資料",
                f"在您選擇的雲端/目標資料夾中偵測到既有的個人化設定與記憶：\n{chosen}\n\n"
                "是否要直接連回並載入該資料夾內的個人化資料？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ans == QMessageBox.Yes:
                copy_local = False
        res = user_profile_manager.set_custom_profile_dir(chosen, copy_existing=copy_local)
        self._refresh_google_and_habits_ui()
        if res.get("found_existing_profile") and not copy_local:
            QMessageBox.information(self, "已連回個人資料夾", f"🎉 已成功連回並載入位於以下路徑的個人化資料：\n{res['profile_dir']}")
        else:
            QMessageBox.information(self, "個資資料夾已更新", f"✅ 個資與個人化資料夾已切換至：\n{res['profile_dir']}")

    def _on_backup_profile_to_cloud(self):
        if not google_suite.is_authenticated():
            QMessageBox.warning(self, "尚未登入 Google", "請先點擊上方「使用 Google 帳戶登入」完成授權，才能將個人化資料備份至您的雲端。")
            return
        res = user_profile_manager.sync_to_cloud(google_suite, settings_manager=self.settings_manager)
        if res.get("success"):
            s = res.get("summary", {})
            QMessageBox.information(
                self,
                "雲端備份成功",
                f"☁️ 已將個人化資料（已剔除敏感金鑰）安全備份至您的 Google Drive `Syntra_User_Profile` 資料夾！\n"
                f"• 長期記憶：{s.get('memory_count', 0)} 筆\n"
                f"• 排程設定：{s.get('schedules_count', 0)} 項\n"
                f"• 永久保存對話：{s.get('saved_sessions_count', 0)} 筆",
            )
        else:
            QMessageBox.warning(self, "雲端備份未完成", str(res.get("error", "未知錯誤")))

    def _on_restore_profile_from_cloud(self):
        if not google_suite.is_authenticated():
            QMessageBox.warning(self, "尚未登入 Google", "請先點擊上方「使用 Google 帳戶登入」完成授權，才能從雲端連回個人資料。")
            return
        prompt_cloud_profile_after_login(self, google_suite, self.settings_manager)
        self._refresh_google_and_habits_ui()

    def _on_sync_local_habits(self):
        res = habit_sync_engine.sync_from_local_browser("chrome")
        if res.get("success"):
            QMessageBox.information(self, "習慣同步成功", "⚡ 已成功自本機 Chrome/Edge 提取高頻工具與工作作息！\n已更新注入 Agent 大腦。")
        else:
            QMessageBox.warning(self, "同步提示", f"同步未完成：{res.get('error')}")
        self._refresh_google_and_habits_ui()

    def _on_sync_cloud_habits(self):
        res = habit_sync_engine.sync_from_google_suite(google_suite)
        if res.get("success"):
            QMessageBox.information(self, "雲端同步成功", "☁️ 已成功自 Google 日曆與雲端硬碟提取專案偏好！")
        else:
            QMessageBox.warning(self, "同步提示", f"雲端同步未完成：{res.get('error')}")
        self._refresh_google_and_habits_ui()

    def _load_settings_to_ui(self):
        """將目前持久化設定載入控制項中"""
        data = self.settings_manager.get_all(mask_secrets=True)

        # 語言
        current_lang = data.get("language") or self.settings_manager.get_language()
        idx = self.combo_lang.findData(current_lang)
        if idx >= 0:
            self.combo_lang.blockSignals(True)
            self.combo_lang.setCurrentIndex(idx)
            self.combo_lang.blockSignals(False)

        # 開機自啟動
        self.chk_autostart.setChecked(bool(data.get("autostart_enabled", True)))

        # Discord
        disc = data.get("discord", {})
        self.chk_discord_enabled.setChecked(bool(disc.get("enabled", False)))
        self.input_dc_channel.setText(str(disc.get("channel_id", "")))
        self.input_dc_webhook.setText(str(disc.get("webhook_url", "")))
        if disc.get("bot_token_masked"):
            self.input_dc_token.setPlaceholderText(f"已儲存 ({disc.get('bot_token_masked')})")

        # 安全 PIN
        sec = data.get("security", {})
        self.chk_redact_windows.setChecked(bool(sec.get("redact_sensitive_windows", True)))
        self.chk_strict_transactions.setChecked(bool(sec.get("strict_transaction_block", True)))

        # 勿擾
        dnd = data.get("dnd", {})
        self.chk_dnd_game.setChecked(bool(dnd.get("auto_detect_game", True)))
        self.chk_dnd_video.setChecked(bool(dnd.get("auto_detect_video", True)))
        self.chk_dnd_homework.setChecked(bool(dnd.get("protect_homework_focus", True)))

        self._refresh_api_summary()
        self._refresh_google_and_habits_ui()
        self._load_permissions_to_ui()

    def _refresh_api_summary(self):
        if self.api_manager:
            providers = self.api_manager.get_providers(mask_keys=True)
            active_count = len(providers)
            with_key = sum(1 for p in providers if p.get("has_key"))
            lines = [f"<b>當前已登記 Provider 數量：</b>{active_count} 個 (其中 {with_key} 個已填寫 Key)\n"]
            for p in providers:
                k_stat = "✅ 已配金鑰" if p.get("has_key") else "❌ 未配金鑰"
                lines.append(f"• <b>{p.get('name')}</b> ({p.get('id')}): {k_stat} | 模型數: {len(p.get('models', []))}")
            self.lbl_api_summary.setText("<br>".join(lines))

    def _open_embedded_api_manager(self):
        if hasattr(self.parent(), "open_api_manager_dialog"):
            self.parent().open_api_manager_dialog()
            self._refresh_api_summary()
        self._refresh_google_and_habits_ui()

    def _on_language_selection_changed(self, idx: int):
        """當使用者在下拉選單切換語言時，立即切換全域 i18n 並即時重繪對話框與全應用介面"""
        lang_code = self.combo_lang.currentData()
        if not lang_code:
            return
        # 切換語言並發出通知
        i18n.set_language(lang_code, notify=True)
        self.sig_language_changed.emit(lang_code)
        self.retranslate_ui()

    def retranslate_ui(self):
        """更新本對話框所有元件字串"""
        self.setWindowTitle(t("settings_title"))
        self.lbl_header_title.setText(f"<b>{t('settings_title')}</b>")
        self.tabs.setTabText(0, t("settings_tab_general"))
        self.tabs.setTabText(1, t("settings_tab_api"))
        self.tabs.setTabText(2, t("settings_tab_discord"))
        self.tabs.setTabText(3, t("settings_tab_security"))
        self.tabs.setTabText(4, t("settings_tab_dnd"))

        self.grp_lang.setTitle(t("lang_group_title"))
        self.lbl_lang.setText(t("lang_label"))
        self.lbl_lang_desc.setText(t("lang_desc"))

        self.grp_autostart.setTitle(t("autostart_group_title"))
        self.chk_autostart.setText(t("autostart_check"))

        self.chk_discord_enabled.setText(t("discord_enabled_check"))
        self.lbl_dc_token.setText(t("discord_token_label"))
        self.lbl_dc_channel.setText(t("discord_channel_label"))
        self.lbl_dc_webhook.setText(t("discord_webhook_label"))

        self.grp_pin.setTitle(t("security_pin_group"))
        self.lbl_new_pin.setText(t("new_pin_label"))
        self.chk_redact_windows.setText(t("redact_windows_check"))
        self.chk_strict_transactions.setText(t("strict_transaction_check"))

        self.grp_dnd.setTitle(t("dnd_group_title"))
        self.chk_dnd_game.setText(t("dnd_game_check"))
        self.chk_dnd_video.setText(t("dnd_video_check"))
        self.chk_dnd_homework.setText(t("dnd_protect_focus"))

        self.btn_cancel.setText(t("btn_cancel"))
        self.btn_save.setText(t("btn_save_settings"))

    def save_settings(self):
        """收集設定並持久化寫入 settings.json"""
        selected_lang = self.combo_lang.currentData()
        autostart = self.chk_autostart.isChecked()

        payload: Dict[str, Any] = {
            "language": selected_lang,
            "autostart_enabled": autostart,
            "discord": {
                "enabled": self.chk_discord_enabled.isChecked(),
                "channel_id": self.input_dc_channel.text().strip(),
                "webhook_url": self.input_dc_webhook.text().strip(),
            },
            "security": {
                "redact_sensitive_windows": self.chk_redact_windows.isChecked(),
                "strict_transaction_block": self.chk_strict_transactions.isChecked(),
            },
            "dnd": {
                "auto_detect_game": self.chk_dnd_game.isChecked(),
                "auto_detect_video": self.chk_dnd_video.isChecked(),
                "protect_homework_focus": self.chk_dnd_homework.isChecked(),
            },
            "permissions": self._collect_permissions(),
        }

        # Discord Token
        dc_token = self.input_dc_token.text().strip()
        if dc_token:
            payload["discord"]["bot_token"] = dc_token

        # 新 PIN 碼
        new_pin = self.input_new_pin.text().strip()
        if new_pin:
            payload["security"]["new_pin"] = new_pin

        # 更新 settings_manager
        self.settings_manager.update_settings(payload)

        # 設定開機自啟
        try:
            configure_windows_autostart(autostart)
        except Exception:
            pass

        # 確保語言切換並發送信號
        i18n.set_language(selected_lang, notify=True)
        self.sig_settings_saved.emit(payload)

        QMessageBox.information(
            self,
            t("settings_title"),
            t("msg_settings_saved") + "\n" + t("msg_lang_changed", lang=SUPPORTED_LANGUAGES.get(selected_lang, selected_lang)),
        )
        self.accept()
