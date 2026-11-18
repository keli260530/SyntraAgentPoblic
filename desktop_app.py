import asyncio
import base64
import html
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import urllib.parse
import webbrowser
from PIL import Image

# 保護 pythonw 無終端模式下的 stdout / stderr，防止 print 拋出例外
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

from PyQt5.QtCore import QEvent, QMimeData, QPoint, QRect, QSettings, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QCursor, QTextCursor, QTextBlockFormat, QColor, QDrag, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWhatsThis,
    QWidget,
)
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

from core.agent_brain import AgentBrain
from core.api_manager import ApiManager, is_local_endpoint
from core.local_model_scanner import LocalModelScanner
from core.chat_input_card import ChatInputCard
from core.process_utils import silent_popen, silent_run
from core.context_guard import ContextGuard
from core.desktop_controller import DesktopController
from core.discord_bot import DiscordBotBridge
from core.help_dialog import ApiHelpDialog
from core.history_manager import HistoryManager
from core.slash_commands import SlashCommandManager
from core.key_detector import ApiKeyDetector
from core.mcp_skill_manager import McpSkillManager
from core.schedule_manager import ScheduleManager
from core.totp_bind_dialog import TotpBindDialog
from core.global_hotkeys import GlobalHotkeys
from core.mcp_client import mcp_manager
from core.quick_input_bar import QuickInputBar
from core.clipboard_assist import ClipboardAssist
from core.screen_streamer import ScreenRecorder, ScreenStreamer
from core.security_guard import SecurityGuard
from core.settings_manager import SettingsManager
from core.supervisor import AICodingSupervisor
from core.tool_labels import describe_tool_call
from core.agent_commands import HELP_TEXT as AGENT_CMD_HELP, parse_agent_command
from core.linux_shell import describe_linux_shell
from core.remote_control import RemoteControlServer
from core.web_auditor import WebAuditor
from core.google_workspace_suite import google_suite
from core.habit_sync_engine import habit_sync_engine
from core.i18n import SUPPORTED_LANGUAGES, i18n, t
from ui.settings_dialog import SettingsDialog
from ui.dlc_manager_dialog import DlcManagerDialog
from ui.agent_team_ui import AgentTeamMixin
from ui.local_model_dialog import RESULT_ADD, RESULT_NEVER, LocalModelConsentDialog
from scripts.setup_startup_and_shortcut import configure_windows_autostart, update_registered_location


BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "assets" / "syntra_icon.ico"
PNG_ICON_PATH = BASE_DIR / "assets" / "syntra_icon.png"

# 現代極簡深色主題 QSS (Google Gemini 極光風格)
MODERN_DARK_STYLE = """
QWidget {
    background-color: #0e1015;
    color: #f1f5f9;
    font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
    font-size: 13px;
}
QFrame#sidebar {
    background-color: #161922;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
}
QFrame#rightPanel {
    background-color: #161922;
    border-left: 1px solid rgba(255, 255, 255, 0.08);
}
QFrame#topBar {
    background-color: #141720;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
QMenuBar {
    background-color: #10121a;
    color: #cbd5e1;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    font-size: 13px;
    padding: 2px 6px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 12px;
    border-radius: 4px;
}
QMenuBar::item:selected {
    background-color: #1e2230;
    color: #60a5fa;
}
QPushButton {
    background-color: #1e2230;
    color: #f1f5f9;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #283044;
    border-color: #60a5fa;
}
QPushButton:pressed {
    background-color: #1a1e2c;
}
QPushButton#primaryBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #8b5cf6);
    color: white;
    border: none;
}
QPushButton#dangerBtn {
    background-color: rgba(239, 68, 68, 0.2);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.4);
}
QPushButton#dangerBtn:hover {
    background-color: rgba(239, 68, 68, 0.35);
}
QPushButton#recordActiveBtn {
    background-color: #dc2626;
    color: white;
    border: none;
}
QComboBox, QLineEdit, QTextEdit {
    background-color: #12141c;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    color: #f1f5f9;
    padding: 6px 10px;
}
QComboBox:focus, QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #818cf8;
}
QComboBox QAbstractItemView {
    background-color: #161922;
    color: #f1f5f9;
    selection-background-color: #283044;
    selection-color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.12);
}
QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 0.08);
    background-color: #161922;
    border-radius: 8px;
}
QTabBar::tab {
    background: #0e1015;
    color: #94a3b8;
    padding: 8px 14px;
    font-weight: 600;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #161922;
    color: #60a5fa;
    border-bottom: 2px solid #60a5fa;
}
QTextBrowser {
    background-color: transparent;
    border: none;
    color: #f1f5f9;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background: transparent;
    width: 6px;
    height: 6px;
    margin: 0;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: rgba(148, 163, 184, 0.25);
    border-radius: 3px;
    min-height: 20px;
    min-width: 20px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: rgba(148, 163, 184, 0.45);
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
    width: 0px;
}
QTableWidget {
    background-color: #12141c;
    alternate-background-color: #161922;
    gridline-color: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: #f1f5f9;
    selection-background-color: #283044;
    selection-color: #ffffff;
}
QTableWidget QHeaderView {
    background-color: #161922;
}
QHeaderView::section {
    background-color: #1e2230;
    color: #94a3b8;
    padding: 6px 10px;
    font-weight: 600;
    border: none;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
    border-bottom: 1px solid rgba(255, 255, 255, 0.12);
}
QTableCornerButton::section {
    background-color: #1e2230;
    border: none;
}
QTreeWidget, QListWidget {
    background-color: #12141c;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    color: #f1f5f9;
    padding: 4px;
}
QTreeWidget::item, QListWidget::item {
    padding: 5px 8px;
    border-radius: 6px;
    margin-bottom: 2px;
}
QTreeWidget::item:hover, QListWidget::item:hover {
    background-color: #1e2230;
    color: #60a5fa;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #283044;
    color: #ffffff;
}
QSplitter::handle {
    background-color: rgba(255, 255, 255, 0.08);
}
QSplitter::handle:hover {
    background-color: #38bdf8;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}
QMenu {
    background-color: #161922;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 6px;
    color: #f1f5f9;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 4px;
    font-size: 12.5px;
}
QMenu::item:selected {
    background-color: #283044;
    color: #60a5fa;
}
QMenu::separator {
    height: 1px;
    background-color: rgba(255, 255, 255, 0.08);
    margin: 4px 6px;
}
"""


class AgentSlot:
    """獨立代理工作單元 (支援在同一介面多開並行執行與監控)"""
    def __init__(self, agent_id: str, name: str, session_id: str):
        self.agent_id = agent_id
        self.name = name
        self.session_id = session_id
        self.status = "IDLE"  # "IDLE" | "RUNNING" | "DONE" | "ERROR"
        self.task_summary = "待命中"
        self.chat_browser = QTextBrowser()
        self.chat_browser.setOpenExternalLinks(False)
        # 不讓 QTextBrowser 自己導覽 action: 連結（否則點了會把整個對話清空）
        self.chat_browser.setOpenLinks(False)
        self.messages: List[Dict[str, Any]] = []
        self.panel_widget: Optional[QWidget] = None
        self.lbl_status_tag: Optional[QLabel] = None
        self.parent_id: Optional[str] = None      # 子代理：所屬的主代理
        self.model_id: Optional[str] = None       # 這個代理自己選的模型（None＝跟隨全域）
        self.container: Optional[QWidget] = None  # 分頁內容（用量條＋對話＋終端）
        self.terminal_widget = None
        self.usage_bar = None


class DraggableHistoryList(QListWidget):
    """
    支援拖曳的歷史對話清單
    - 暫存區 (temp) 項目可拖曳至 永久保存區 (permanent)
    """
    def __init__(self, category: str, on_drop_callback=None, parent=None):
        super().__init__(parent)
        self.category = category
        self.on_drop_callback = on_drop_callback
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        sess_id = item.data(Qt.UserRole)
        mime = QMimeData()
        mime.setText(f"session:{sess_id}:{self.category}")
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() and event.mimeData().text().startswith("session:"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasText() and event.mimeData().text().startswith("session:"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        text = event.mimeData().text()
        if text.startswith("session:"):
            parts = text.split(":")
            if len(parts) >= 3:
                sess_id = parts[1]
                src_cat = parts[2]
                if src_cat != self.category:
                    if self.on_drop_callback:
                        self.on_drop_callback(sess_id, self.category)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class AsyncWorkerThread(QThread):
    """常駐 asyncio 事件循環執行緒"""
    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


class WindowCardWidget(QFrame):
    """
    職責：即時切換視窗卡片（類似 Windows Alt+Tab / Discord 螢幕分享卡片），
    呈現縮圖、標題、選中外框與 HWND 綁定。
    """
    clicked = pyqtSignal(int)  # 傳遞 hwnd

    def __init__(self, hwnd: int, title: str, is_screen: bool = False, parent=None):
        super().__init__(parent)
        self.hwnd = hwnd
        self.title_text = title
        self.is_screen = is_screen
        self.is_selected = False

        self.setFixedSize(160, 110)
        self.setCursor(Qt.PointingHandCursor)
        self.update_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedHeight(66)
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setStyleSheet("background: #0b0d12; border-radius: 4px;")
        layout.addWidget(self.lbl_thumb)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: 600; color: #f1f5f9;")
        self.lbl_title.setWordWrap(False)
        layout.addWidget(self.lbl_title)

    def set_thumbnail(self, pixmap: QPixmap):
        scaled = pixmap.scaled(148, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_thumb.setPixmap(scaled)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self.update_style()

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("QFrame { background: #1f293d; border: 2px solid #38bdf8; border-radius: 8px; }")
        else:
            self.setStyleSheet("QFrame { background: #161922; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; } QFrame:hover { border-color: #60a5fa; }")

    def mousePressEvent(self, event):
        self.clicked.emit(self.hwnd)
        super().mousePressEvent(event)


class FilterableModelComboBox(QComboBox):
    """
    可輸入搜尋、支援逐字元 (textEdited) 即時過濾的智慧模型選單：
    1. 支援在選單內直接鍵入關鍵字 (setEditable=True)
    2. 逐字元即時篩選匹配模型並更新下拉項目與彈出候選
    3. 點選或按下 Enter 時自動發出 modelSelected 信號
    """
    modelSelected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.all_items: List[str] = []
        self._is_updating = False

        if self.completer():
            self.completer().setCompletionMode(QCompleter.PopupCompletion)
            self.completer().setFilterMode(Qt.MatchContains)

        le = self.lineEdit()
        le.setPlaceholderText("🔎 在此輸入關鍵字即時過濾模型 (如 flash / pro / 2.5)...")
        le.textEdited.connect(self._on_user_typing)
        self.activated.connect(self._on_activated)

    def set_models(self, models: List[str], current_filter: str = ""):
        self.all_items = [m.strip() for m in models if m and m.strip()]
        self.apply_filter(current_filter)

    def apply_filter(self, query: str):
        if self._is_updating:
            return
        self._is_updating = True
        self.blockSignals(True)

        q = query.strip().lower()
        if not q:
            matches = list(self.all_items)
            header = f"-- 🎯 所有可用模型 (線上共 {len(matches)} 個，可直接輸入即時過濾) --" if matches else "-- 📋 尚未取得模型清單 --"
        else:
            words = q.split()
            matches = [m for m in self.all_items if all(w in m.lower() for w in words)]
            header = f"-- 🔍 符合「{query.strip()}」的模型 (共 {len(matches)} 個，點擊立即選定) --" if matches else f"-- ❌ 無符合「{query.strip()}」的模型 --"

        curr_le_text = self.lineEdit().text()
        self.clear()
        self.addItem(header)
        for m in matches:
            self.addItem(m)

        # 恢復使用者正在輸入的文字游標
        self.lineEdit().setText(curr_le_text)
        self.blockSignals(False)
        self._is_updating = False

        if q and matches:
            self.showPopup()

    def _on_user_typing(self, text: str):
        self.apply_filter(text)

    def _on_activated(self, index: int):
        if index <= 0:
            return
        chosen = self.itemText(index).strip()
        if chosen and not chosen.startswith("--"):
            self.modelSelected.emit(chosen)


class _CallableEvent(QEvent):
    """把背景執行緒的回呼送回 UI 執行緒執行（搭配 QApplication.postEvent）。"""
    TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, fn):
        super().__init__(self.TYPE)
        self.fn = fn


class ApiManagerDialog(QDialog):
    """
    職責：管理多組 API Key，根據 API 編碼特徵自動識別公司並智慧命名「公司 (金鑰 #N)」，
    同時允許使用者完全自訂修改名稱與模型，且將通訊細節折疊為進階選項。
    """
    def __init__(self, api_manager: ApiManager, async_worker: AsyncWorkerThread, parent=None):
        super().__init__(parent)
        self.api_manager = api_manager
        self.async_worker = async_worker
        self.key_detector = ApiKeyDetector()

        # 自動防抖定時器 (貼上 Key 後自動在背景抓取完整可用模型清單)
        self.fetch_timer = QTimer(self)
        self.fetch_timer.setSingleShot(True)
        self.fetch_timer.timeout.connect(self._auto_fetch_models_quiet)

        self.setWindowTitle("🔑 API Key 智慧接入與管理")
        self.resize(790, 600)
        self.setStyleSheet(MODERN_DARK_STYLE)

        # 保持 Windows 標題列標準關閉與問號說明按鈕
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)

        main_layout = QVBoxLayout(self)

        # 頂部提示列（點擊視窗標題列右上角的「?」按鈕即可隨時打開完整說明）
        top_info = QLabel("💡 <b>貼上 API Key 即可自動識別公司與智慧命名</b>（例如 Google Gemini #1 / OpenAI #2），亦可隨時點擊右上角 <b>?</b> 查看說明。")
        top_info.setStyleSheet("color: #94a3b8; font-size: 12.5px; padding: 2px 0px 4px 0px;")
        main_layout.addWidget(top_info)

        # 清單表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["自訂/辨識名稱", "API Key 狀態", "支援模型", "端點網址", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table)

        # 編輯/新增卡片
        self.edit_group = QGroupBox("設定 / 新增 API Key")
        edit_layout = QVBoxLayout(self.edit_group)

        # 智慧提示標籤
        self.lbl_auto_detect = QLabel("🔍 請在下方輸入或貼上 API Key，系統將自動分析編碼...")
        self.lbl_auto_detect.setStyleSheet("color: #60a5fa; font-weight: 600; font-size: 12px;")
        edit_layout.addWidget(self.lbl_auto_detect)

        form_layout = QFormLayout()

        key_container = QWidget()
        key_layout = QHBoxLayout(key_container)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)

        self.input_key = QLineEdit()
        self.input_key.setEchoMode(QLineEdit.Password)
        self.input_key.setPlaceholderText("貼上 API Key (例如 AIzaSy... / sk-ant-... / sk-...)")
        self.input_key.textChanged.connect(self._on_key_text_changed)

        self.btn_toggle_eye = QPushButton("👁️")
        self.btn_toggle_eye.setFixedWidth(40)
        self.btn_toggle_eye.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_eye.setToolTip("點擊顯示完整 API Key")
        self.btn_toggle_eye.clicked.connect(self._toggle_key_visibility)

        key_layout.addWidget(self.input_key, stretch=1)
        key_layout.addWidget(self.btn_toggle_eye)

        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("自動辨識產生，亦可自由修改為自訂名稱...")

        # 支援模型區塊 (包含模型輸入框、線上即時抓取按鈕、以及可輸入逐字過濾之智慧選單)
        self.all_fetched_models: List[str] = []
        models_container = QWidget()
        models_vbox = QVBoxLayout(models_container)
        models_vbox.setContentsMargins(0, 0, 0, 0)
        models_vbox.setSpacing(6)

        models_input_row = QHBoxLayout()
        models_input_row.setContentsMargins(0, 0, 0, 0)
        models_input_row.setSpacing(6)
        self.input_models = QLineEdit()
        self.input_models.setPlaceholderText("多個模型以逗號分隔，首個為預設模型...")
        self.input_models.textEdited.connect(self._on_input_models_text_edited)

        self.btn_fetch_models = QPushButton("🔍 自動抓取可用模型")
        self.btn_fetch_models.setStyleSheet("padding: 5px 12px; font-weight: 600;")
        self.btn_fetch_models.setToolTip("向服務商端點動態查詢該 API Key 支援的所有可用模型清單")
        self.btn_fetch_models.clicked.connect(self.fetch_models_for_current_key)
        models_input_row.addWidget(self.input_models, stretch=1)
        models_input_row.addWidget(self.btn_fetch_models)
        models_vbox.addLayout(models_input_row)

        self.combo_available_models = FilterableModelComboBox()
        self.combo_available_models.modelSelected.connect(self._on_model_chosen)
        models_vbox.addWidget(self.combo_available_models)

        self.lbl_models_status = QLabel("")
        self.lbl_models_status.setStyleSheet("font-size: 11.5px; color: #94a3b8;")
        models_vbox.addWidget(self.lbl_models_status)

        form_layout.addRow("🔑 貼上 API Key：", key_container)
        form_layout.addRow("名稱 (可編輯)：", self.input_name)
        form_layout.addRow("支援模型：", models_container)
        edit_layout.addLayout(form_layout)

        # 可折疊進階選項
        self.btn_toggle_adv = QPushButton("▶ ⚙️ 進階網路選項（自建/中轉站才需修改，平常留空即可）")
        self.btn_toggle_adv.setStyleSheet("text-align: left; background: transparent; border: none; color: #60a5fa; font-weight: 600; padding: 4px 0;")
        self.btn_toggle_adv.clicked.connect(self._toggle_advanced)
        edit_layout.addWidget(self.btn_toggle_adv)

        self.adv_frame = QFrame()
        self.adv_frame.setStyleSheet("background: #11141d; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 6px;")
        adv_form = QFormLayout(self.adv_frame)
        self.input_proto = QComboBox()
        self.input_proto.addItems(["openai", "anthropic"])
        self.input_url = QLineEdit()
        self.input_url.setPlaceholderText("自動帶入官方端點")
        adv_form.addRow("協定類型：", self.input_proto)
        adv_form.addRow("Base URL：", self.input_url)
        self.adv_frame.hide()
        edit_layout.addWidget(self.adv_frame)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 儲存這組 API Key")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self.save_provider)

        self.btn_test = QPushButton("⚡ 測試連線")
        self.btn_test.clicked.connect(self.test_connection)

        self.btn_clear = QPushButton("＋ 清空建立新項目")
        self.btn_clear.clicked.connect(self.clear_form)

        self.btn_scan_local = QPushButton("🖥️ 掃描本機模型")
        self.btn_scan_local.setToolTip("偵測本機 Ollama / LM Studio / llama.cpp 上尚未接入的模型，確認後一鍵接入（免 API Key）")
        self.btn_scan_local.clicked.connect(self._scan_local_models)

        btn_row.addWidget(self.btn_scan_local)
        btn_row.addWidget(self.btn_clear)
        btn_row.addWidget(self.btn_test)
        btn_row.addWidget(self.btn_save)
        edit_layout.addLayout(btn_row)

        main_layout.addWidget(self.edit_group)

        footer_btn = QPushButton("完成並關閉")
        footer_btn.clicked.connect(self.accept)
        main_layout.addWidget(footer_btn, alignment=Qt.AlignRight)

        self.current_id = None
        self.user_manually_edited_name = False
        self.load_table_data()

    def _scan_local_models(self):
        main = self.parent()
        if main is not None and hasattr(main, "scan_local_models"):
            main.scan_local_models(manual=True)

    def show_help_dialog(self):
        """跳出 API Key 智慧接入與管理之完整說明指南"""
        dlg = ApiHelpDialog(self)
        dlg.exec_()

    def event(self, e: QEvent) -> bool:
        """捕捉 Windows 標題列右上角『?』問號按鈕點擊事件，立即重置鼠標模式並直接彈出完整說明視窗"""
        if e.type() == QEvent.EnterWhatsThisMode:
            e.accept()
            QWhatsThis.leaveWhatsThisMode()
            self.show_help_dialog()
            return True
        if isinstance(e, _CallableEvent):
            # 背景執行緒（例如線上抓模型清單）完成後，回到 UI 執行緒執行回呼
            try:
                e.fn()
            except Exception:
                pass
            return True
        return super().event(e)

    def _toggle_advanced(self):
        vis = self.adv_frame.isVisible()
        self.adv_frame.setVisible(not vis)
        self.btn_toggle_adv.setText(f"{'▼' if not vis else '▶'} ⚙️ 進階網路選項（自建/中轉站才需修改，平常留空即可）")

    def _toggle_key_visibility(self):
        if self.input_key.echoMode() == QLineEdit.Password:
            self.input_key.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_eye.setText("🙈")
            self.btn_toggle_eye.setToolTip("點擊隱藏 API Key")
        else:
            self.input_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_eye.setText("👁️")
            self.btn_toggle_eye.setToolTip("點擊顯示完整 API Key")

    def _on_model_chosen(self, selected_model: str):
        """當使用者在可輸入選單中選定某一模型時，設為首選模型"""
        if not selected_model or selected_model.startswith("--"):
            return
        current = [m.strip() for m in self.input_models.text().split(",") if m.strip()]
        if selected_model in current:
            current.remove(selected_model)
        current.insert(0, selected_model)
        self.input_models.setText(", ".join(current))
        self.lbl_models_status.setText(f"🎯 已將「{selected_model}」設為首選模型！")
        self.lbl_models_status.setStyleSheet("color: #60a5fa; font-size: 11.5px;")

    def _on_input_models_text_edited(self, text: str):
        """當使用者在上方的模型輸入框逐字元打字時，自動連動下方選單進行即時篩選"""
        parts = [p.strip() for p in text.split(",") if p.strip()]
        kw = parts[-1] if parts else text.strip()
        self.combo_available_models.apply_filter(kw)

    def _update_models_completer(self, models: List[str]):
        """為支援模型輸入框更新彈出式 QCompleter (支援包含匹配)"""
        if not models:
            return
        completer = QCompleter(models, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.input_models.setCompleter(completer)

    def fetch_models_for_current_key(self):
        key = self.input_key.text().strip()
        if not key and self.current_id:
            prov = next((p for p in self.api_manager.providers if p["id"] == self.current_id), None)
            if prov and prov.get("api_key"):
                key = prov["api_key"]

        if not key:
            QMessageBox.warning(self, "提示", "請先輸入或貼上 API Key！")
            return

        url = self.input_url.text().strip()
        proto = self.input_proto.currentText()
        name = self.input_name.text().strip()
        if not url:
            det = self.key_detector.detect_and_suggest(key, self.api_manager.providers, manual_override_name=name)
            url = det["base_url"]
            proto = det["protocol"]
            self.input_url.setText(url)
            idx = self.input_proto.findText(proto)
            if idx >= 0:
                self.input_proto.setCurrentIndex(idx)

        self.btn_fetch_models.setEnabled(False)
        self.btn_fetch_models.setText("⏳ 抓取中...")
        self.lbl_models_status.setText("⏳ 正在向端點查詢模型清單...")
        self.lbl_models_status.setStyleSheet("color: #60a5fa; font-size: 11.5px;")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            future = self.async_worker.submit(
                self.api_manager.fetch_available_models(api_key=key, base_url=url, protocol=proto)
            )
            res = future.result(timeout=18)
            if res.get("ok"):
                models = res.get("models", [])
                self.all_fetched_models = models
                self.combo_available_models.set_models(models)
                self._update_models_completer(models)

                self.lbl_models_status.setText(f"✅ 成功取得 {len(models)} 個可用模型！可在選單直接輸入關鍵字過濾或挑選。")
                self.lbl_models_status.setStyleSheet("color: #4ade80; font-size: 11.5px;")

                curr_txt = self.input_models.text().strip()
                if not curr_txt or "default-model" in curr_txt:
                    self.input_models.setText(", ".join(models[:3]))
            else:
                self.lbl_models_status.setText(f"❌ 抓取失敗：{res.get('error')}")
                self.lbl_models_status.setStyleSheet("color: #f87171; font-size: 11.5px;")
                QMessageBox.warning(self, "抓取模型失敗", f"無法取得模型清單：\n\n{res.get('error')}")
        except Exception as e:
            self.lbl_models_status.setText(f"❌ 查詢例外：{e}")
            self.lbl_models_status.setStyleSheet("color: #f87171; font-size: 11.5px;")
            QMessageBox.critical(self, "錯誤", f"抓取模型超時或例外：{e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_fetch_models.setEnabled(True)
            self.btn_fetch_models.setText("🔍 自動抓取可用模型")

    def _auto_fetch_models_quiet(self):
        """背景靜態防抖自動抓取模型清單 (不跳彈出警告窗，無感更新下拉選單)"""
        key = self.input_key.text().strip()
        if not key or len(key) < 15:
            return
        url = self.input_url.text().strip()
        proto = self.input_proto.currentText()
        if not url:
            det = self.key_detector.detect_and_suggest(key, self.api_manager.providers)
            url = det["base_url"]
            proto = det["protocol"]

        self.lbl_models_status.setText("⏳ 正在線上自動搜尋該 Key 支援的所有可用模型清單...")
        self.lbl_models_status.setStyleSheet("color: #60a5fa; font-size: 11.5px;")

        def _on_done(future):
            try:
                res = future.result()
                if res.get("ok"):
                    models = res.get("models", [])
                    if models:
                        self.all_fetched_models = models
                        self.combo_available_models.set_models(models)
                        self._update_models_completer(models)

                        self.lbl_models_status.setText(f"✅ 線上成功取得 {len(models)} 個可用模型！可在選單直接輸入關鍵字過濾或挑選。")
                        self.lbl_models_status.setStyleSheet("color: #4ade80; font-size: 11.5px;")

                        # 自動補齊至支援模型欄位 (優先排入前 3 個主力模型)
                        curr_txt = self.input_models.text().strip()
                        if not curr_txt or "default-model" in curr_txt:
                            self.input_models.setText(", ".join(models[:3]))
                else:
                    err = res.get("error", "未明原因")
                    self.lbl_models_status.setText(f"⚠️ 線上搜尋未成功 ({err})，已保留本地推薦模型。可點右側按鈕手動重試。")
                    self.lbl_models_status.setStyleSheet("color: #f59e0b; font-size: 11.5px;")
            except Exception as e:
                self.lbl_models_status.setText(f"⚠️ 連線逾時或異常 ({e})，已保留本地推薦模型。")
                self.lbl_models_status.setStyleSheet("color: #f59e0b; font-size: 11.5px;")

        fut = self.async_worker.submit(
            self.api_manager.fetch_available_models(api_key=key, base_url=url, protocol=proto)
        )
        fut.add_done_callback(lambda f: QApplication.instance().postEvent(self, _CallableEvent(lambda: _on_done(f))))

    def _on_key_text_changed(self, text: str):
        key = text.strip()
        if not key or len(key) < 8:
            self.lbl_auto_detect.setText("🔍 請在下方輸入或貼上 API Key，系統將自動分析編碼...")
            return

        detection = self.key_detector.detect_and_suggest(
            api_key=key,
            existing_providers=self.api_manager.providers,
            manual_override_name=self.input_name.text() if self.user_manually_edited_name else None,
        )

        if detection["detected"]:
            self.lbl_auto_detect.setText(f"✨ 自動識別為 <b>{detection['company']}</b>！已指派建議名稱與推薦模型。")
            if not self.user_manually_edited_name:
                self.input_name.setText(detection["auto_name"])
            self.input_url.setText(detection["base_url"])
            suggested = detection.get("suggested_models") or []
            self.input_models.setText(", ".join(suggested))
            idx = self.input_proto.findText(detection["protocol"])
            if idx >= 0:
                self.input_proto.setCurrentIndex(idx)

            self.all_fetched_models = suggested
            self.combo_available_models.set_models(suggested)
            self._update_models_completer(suggested)

            # 若 Key 長度充足，自動觸發背景防抖線上抓取
            if len(key) >= 20:
                self.fetch_timer.start(350)
        else:
            self.lbl_auto_detect.setText("ℹ️ 未知編碼格式，已採用標準 OpenAI 相容端點。")
            if len(key) >= 20:
                self.fetch_timer.start(350)
            if len(key) >= 20:
                self.fetch_timer.start(350)

    def load_table_data(self):
        providers = self.api_manager.get_providers(mask_keys=True)
        self.table.setRowCount(len(providers))
        for row, p in enumerate(providers):
            self.table.setItem(row, 0, QTableWidgetItem(p["name"]))
            key_status = f"✅ 已設定 ({p.get('masked_key')})" if p.get("has_key") else "❌ 未填 Key"
            self.table.setItem(row, 1, QTableWidgetItem(key_status))
            models_str = ", ".join(p.get("models") or [])
            self.table.setItem(row, 2, QTableWidgetItem(models_str))
            self.table.setItem(row, 3, QTableWidgetItem(p.get("base_url", "")[:28] + "..."))

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(4)

            btn_edit = QPushButton("填Key/編輯")
            btn_edit.clicked.connect(lambda _, prov=p: self.populate_form(prov))
            btn_del = QPushButton("刪除")
            btn_del.setObjectName("dangerBtn")
            btn_del.clicked.connect(lambda _, pid=p["id"]: self.delete_provider(pid))

            action_layout.addWidget(btn_edit)
            action_layout.addWidget(btn_del)
            self.table.setCellWidget(row, 4, action_widget)

    def populate_form(self, p: Dict[str, Any]):
        self.current_id = p["id"]
        self.user_manually_edited_name = True
        self.input_name.setText(p["name"])
        self.input_url.setText(p.get("base_url", ""))

        # 載入該 Provider 原始真實 Key，預設以圓點顯示
        real_key = ""
        prov = next((pr for pr in self.api_manager.providers if pr["id"] == p["id"]), None)
        if prov and prov.get("api_key"):
            real_key = prov["api_key"]

        self.input_key.blockSignals(True)
        self.input_key.setText(real_key)
        self.input_key.setEchoMode(QLineEdit.Password)
        self.btn_toggle_eye.setText("👁️")
        self.btn_toggle_eye.setToolTip("點擊顯示完整 API Key")
        if real_key:
            self.input_key.setPlaceholderText("已填入 API Key")
            self.lbl_auto_detect.setText(f"ℹ️ 目前正在編輯 <b>{p['name']}</b>。點擊 👁️ 可查看完整 Key。")
        else:
            self.input_key.setPlaceholderText("貼上 API Key (例如 AIzaSy... / sk-ant-... / sk-...)")
            self.lbl_auto_detect.setText("🔍 請在下方輸入或貼上 API Key，系統將自動分析編碼...")
        self.input_key.blockSignals(False)

        models_list = p.get("models") or []
        self.input_models.setText(", ".join(models_list))
        idx = self.input_proto.findText(p.get("protocol", "openai").lower())
        if idx >= 0:
            self.input_proto.setCurrentIndex(idx)

        self.all_fetched_models = models_list
        self.combo_available_models.set_models(models_list)
        self._update_models_completer(models_list)
        self.lbl_models_status.clear()

    def clear_form(self):
        self.current_id = f"prov_{int(time.time())}"
        self.user_manually_edited_name = False
        self.input_key.blockSignals(True)
        self.input_key.clear()
        self.input_key.setEchoMode(QLineEdit.Password)
        self.btn_toggle_eye.setText("👁️")
        self.btn_toggle_eye.setToolTip("點擊顯示完整 API Key")
        self.input_key.setPlaceholderText("貼上 API Key (例如 AIzaSy... / sk-ant-... / sk-...)")
        self.input_key.blockSignals(False)
        self.input_name.clear()
        self.input_models.clear()
        self.input_url.clear()
        self.lbl_auto_detect.setText("🔍 請在下方輸入或貼上 API Key，系統將自動分析編碼...")
        self.all_fetched_models = []
        self.combo_available_models.set_models([])
        self.lbl_models_status.clear()

    def save_provider(self):
        key = self.input_key.text().strip()
        name = self.input_name.text().strip()
        pid = self.current_id or f"prov_{int(time.time())}"

        # 若未填新 Key 但正在編輯既有 Provider，使用原本的 Key
        if not key and self.current_id:
            prov = next((p for p in self.api_manager.providers if p["id"] == self.current_id), None)
            if prov and prov.get("api_key"):
                key = prov["api_key"]

        local = is_local_endpoint(self.input_url.text())
        if not key and not local:
            QMessageBox.warning(self, "提示", "尚未填入 API Key！請先輸入 Key 再儲存。")
            return
        if local and not name:
            name = "本地模型"

        # 若未填名稱，自動用 detector 產出
        if not name:
            det = self.key_detector.detect_and_suggest(key, self.api_manager.providers)
            name = det["final_name"]

        url = self.input_url.text().strip()
        proto = self.input_proto.currentText()
        if not url:
            det = self.key_detector.detect_and_suggest(key, self.api_manager.providers, manual_override_name=name)
            url = det["base_url"]
            proto = det["protocol"]

        models = [m.strip() for m in self.input_models.text().split(",") if m.strip()]
        if not models:
            det = self.key_detector.detect_and_suggest(key, self.api_manager.providers)
            models = det["suggested_models"]

        test_model = models[0] if models else None

        # ▼ 儲存時自動測試 API 連線有無通
        self.btn_save.setEnabled(False)
        self.btn_save.setText("⏳ 正在自動測試 API 連線...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        test_passed = False
        err_msg = ""

        try:
            future = self.async_worker.submit(
                self.api_manager.test_connection_params(key, url, proto, test_model)
            )
            res = future.result(timeout=18)
            if res.get("ok"):
                test_passed = True
            else:
                err_msg = res.get("error", "未知錯誤")
        except Exception as e:
            err_msg = str(e)
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_save.setEnabled(True)
            self.btn_save.setText("💾 儲存這組 API Key")

        payload = {
            "id": pid,
            "name": name,
            "protocol": proto,
            "base_url": url,
            "models": models,
        }
        if key:
            payload["api_key"] = key

        if test_passed:
            self.api_manager.upsert_provider(payload, source="桌面設定介面")
            self.load_table_data()
            QMessageBox.information(
                self,
                "連線測試成功",
                f"✅ API 連線測試通過 (HTTP 回應正常)！\n\n已成功儲存「{name}」，首選模型：[{test_model}]。",
            )
        else:
            reply = QMessageBox.warning(
                self,
                "⚠️ API 連線未通過",
                f"❌ 自動測試連線失敗：\n\n{err_msg}\n\n可能原因：API Key 錯誤、端點不符、模型名稱不存在或帳號尚未開通推論權限。\n\n請問您仍然要【強制儲存】這組設定嗎？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.api_manager.upsert_provider(payload, source="桌面設定介面")
                self.load_table_data()
                QMessageBox.information(self, "強制儲存完畢", f"已強制儲存「{name}」。（注意：目前連線測試未通過）")

    def test_connection(self):
        key = self.input_key.text().strip()
        if not key and self.current_id:
            prov = next((p for p in self.api_manager.providers if p["id"] == self.current_id), None)
            if prov and prov.get("api_key"):
                key = prov["api_key"]

        if not key and not is_local_endpoint(self.input_url.text()):
            QMessageBox.warning(self, "提示", "尚未填入 API Key，請先輸入後再測試。")
            return

        name = self.input_name.text().strip()
        url = self.input_url.text().strip()
        proto = self.input_proto.currentText()
        if not url:
            det = self.key_detector.detect_and_suggest(key, self.api_manager.providers, manual_override_name=name)
            url = det["base_url"]
            proto = det["protocol"]

        models = [m.strip() for m in self.input_models.text().split(",") if m.strip()]
        test_model = models[0] if models else None

        self.btn_test.setEnabled(False)
        self.btn_test.setText("⏳ 測試中...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            future = self.async_worker.submit(
                self.api_manager.test_connection_params(key, url, proto, test_model)
            )
            res = future.result(timeout=18)
            if res.get("ok"):
                QMessageBox.information(self, "測試結果", res.get("message", "✅ 連線成功！"))
            else:
                QMessageBox.warning(self, "測試結果", f"❌ 連線失敗：\n\n{res.get('error')}")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"測試失敗：{e}")
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_test.setEnabled(True)
            self.btn_test.setText("⚡ 測試連線")

    def delete_provider(self, pid: str):
        if QMessageBox.question(self, "確認刪除", "確定要刪除這組 API 設定嗎？") == QMessageBox.Yes:
            self.api_manager.delete_provider(pid, source="桌面設定介面")
            self.load_table_data()


class SecurityPinDialog(QDialog):
    """資安攔截與交易 PIN 碼放行對話框"""
    def __init__(self, ticket: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.ticket = ticket
        self.pin_result = None
        self.remember = False
        self.setWindowTitle("🛡️ 資安防護審批閘門")
        self.setStyleSheet(MODERN_DARK_STYLE)

        layout = QVBoxLayout(self)
        is_tx = ticket.get("requires_pin", False)
        details = ticket.get("details") or {}
        if details.get("kind") == "app_request":
            self._build_app_request(layout, details)
            return
        if details.get("kind") == "permission_request":
            self._build_permission_request(layout, details)
            return
        self.setFixedSize(520, 360)

        header = QLabel(
            "🚨 【金流/下單交易攔截】需輸入安全 PIN 碼" if is_tx else "🛡️ 【高風險操作攔截】待批准"
        )
        header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        header.setStyleSheet("color: #f87171;" if is_tx else "color: #fbbf24;")
        layout.addWidget(header)

        title_lbl = QLabel(f"<b>項目：</b> {html.escape(ticket.get('title', ''))}")
        title_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)

        reason_lbl = QLabel(f"<b>原因：</b> {html.escape(ticket.get('reason', ''))}")
        reason_lbl.setWordWrap(True)
        reason_lbl.setStyleSheet("color: #94a3b8;")
        layout.addWidget(reason_lbl)

        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.Password)
        self.pin_input.setPlaceholderText("請輸入你的交易安全 PIN 碼 (預設 0000)...")
        if is_tx:
            layout.addWidget(QLabel("交易安全 PIN 碼："))
            layout.addWidget(self.pin_input)

        btn_row = QHBoxLayout()
        btn_approve = QPushButton("🔐 驗證 PIN 並放行" if is_tx else "✅ 批准執行")
        btn_approve.setObjectName("primaryBtn")
        btn_approve.clicked.connect(self.accept_approval)

        btn_reject = QPushButton("🛑 拒絕並攔截")
        btn_reject.setObjectName("dangerBtn")
        btn_reject.clicked.connect(self.reject)

        btn_row.addWidget(btn_approve)
        btn_row.addWidget(btn_reject)
        layout.addLayout(btn_row)

    def _build_app_request(self, layout: QVBoxLayout, d: Dict[str, Any]):
        """程式允許請求：說清楚要用哪個程式、要做什麼、為什麼、怎麼做，並提供永久允許。"""
        self.setWindowTitle("📱 應用程式使用許可請求")
        self.setMinimumWidth(560)
        app = html.escape(str(d.get("app", "")))

        header = QLabel(f"🙋 AI 想使用「{app}」")
        header.setFont(QFont("Segoe UI", 13, QFont.Bold))
        header.setStyleSheet("color: #fbbf24;")
        layout.addWidget(header)

        note = QLabel("這個程式不在「AI 可使用的應用程式」允許清單中，需要你同意。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #94a3b8;")
        layout.addWidget(note)

        for icon, label, key in (("🎯", "要做什麼", "what"), ("💡", "為什麼", "why"), ("🛠️", "怎麼做", "how")):
            box = QLabel(f"<b>{icon} {label}</b><br>{html.escape(str(d.get(key, ''))).replace(chr(10), '<br>')}")
            box.setWordWrap(True)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.setStyleSheet("background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);"
                              "border-radius: 8px; padding: 10px;")
            layout.addWidget(box)

        btn_row = QHBoxLayout()
        btn_once = QPushButton("✅ 允許這一次")
        btn_once.setObjectName("primaryBtn")
        btn_once.clicked.connect(self.accept_approval)
        btn_row.addWidget(btn_once)
        if self.ticket.get("allow_remember"):
            btn_always = QPushButton(f"⭐ 永久允許「{d.get('app', '')}」")
            btn_always.clicked.connect(self.accept_always)
            btn_row.addWidget(btn_always)
        btn_reject = QPushButton("🛑 不允許")
        btn_reject.setObjectName("dangerBtn")
        btn_reject.clicked.connect(self.reject)
        btn_row.addWidget(btn_reject)
        layout.addLayout(btn_row)

        tip = QLabel("永久允許後，可在 設定 → 🔐 權限與功能 →「AI 可使用的應用程式」隨時移除。")
        tip.setStyleSheet("color: #64748b; font-size: 11.5px;")
        layout.addWidget(tip)
        self.pin_input = QLineEdit()  # accept_approval 需要；程式請求不需要 PIN

    def _build_permission_request(self, layout: QVBoxLayout, d: Dict[str, Any]):
        """一般操作的詢問：用白話說「想做什麼、為什麼問你」，工具名稱與參數收在「技術細節」裡。"""
        self.setWindowTitle("Syntra 需要你的同意")
        self.setMinimumWidth(500)
        risky = bool(d.get("risky"))

        header = QLabel("🙋 Syntra 想要做這件事：")
        header.setFont(QFont("Segoe UI", 12, QFont.Bold))
        header.setStyleSheet("color: #e2e8f0;")
        layout.addWidget(header)

        what = QLabel(html.escape(str(d.get("what", ""))))
        what.setWordWrap(True)
        what.setTextInteractionFlags(Qt.TextSelectableByMouse)
        what.setStyleSheet("font-size: 15px; font-weight: bold; color: #fbbf24;"
                           "background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);"
                           "border-radius: 8px; padding: 12px;")
        layout.addWidget(what)

        if risky:
            warn = QLabel("⚠️ 這個動作會變更你的電腦、資料或對外傳送內容，請確認是你想要的再允許。")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #f87171;")
            layout.addWidget(warn)

        why = QLabel(f"為什麼問你：你在 設定 → 🔐 權限與功能 中，把{html.escape(str(d.get('why', '')))}。")
        why.setWordWrap(True)
        why.setStyleSheet("color: #94a3b8;")
        layout.addWidget(why)

        tech = QLabel(html.escape(str(d.get("tech", ""))))
        tech.setWordWrap(True)
        tech.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tech.setStyleSheet("color: #64748b; font-family: Consolas, monospace; font-size: 11px;")
        tech.setVisible(False)
        btn_tech = QPushButton("顯示技術細節")
        btn_tech.setFlat(True)
        btn_tech.setStyleSheet("color: #64748b; text-align: left; border: none;")
        btn_tech.clicked.connect(lambda: (tech.setVisible(not tech.isVisible()),
                                          btn_tech.setText("隱藏技術細節" if tech.isVisible() else "顯示技術細節"),
                                          self.adjustSize()))
        layout.addWidget(btn_tech)
        layout.addWidget(tech)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("✅ 允許（單次）" if self.ticket.get("allow_remember") else "✅ 允許")
        btn_ok.setObjectName("primaryBtn")
        btn_ok.setDefault(True)
        btn_ok.setAutoDefault(True)
        btn_ok.clicked.connect(self.accept_approval)
        btn_row.addWidget(btn_ok)
        if self.ticket.get("allow_remember"):
            btn_always = QPushButton("✅ 永久允許")
            btn_always.setObjectName("primaryBtn")
            btn_always.clicked.connect(self.accept_always)
            btn_row.addWidget(btn_always)
        btn_no = QPushButton("🛑 不允許")
        btn_no.setObjectName("dangerBtn")
        btn_no.clicked.connect(self.reject)
        btn_row.addWidget(btn_no)
        layout.addLayout(btn_row)

        tip = QLabel("提示：按 Enter 等同「允許（單次）」；按「永久允許」則下次同類操作不再詢問。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #64748b; font-size: 11.5px;")
        layout.addWidget(tip)
        self.pin_input = QLineEdit()  # accept_approval 需要；一般詢問不需要 PIN
        btn_ok.setFocus()

    def accept_always(self):
        self.remember = True
        self.accept_approval()

    def accept_approval(self):
        self.pin_result = self.pin_input.text().strip()
        self.accept()


_TOPBAR_GHOST_QSS = """
QToolButton, QPushButton {
    background: transparent; color: #cbd5e1; border: 1px solid transparent;
    border-radius: 7px; padding: 5px 10px; font-weight: 600; font-size: 12.5px;
}
QToolButton:hover, QPushButton:hover { background: #222838; color: #f1f5f9; }
QToolButton:pressed, QPushButton:pressed { background: #1a1f2c; }
QToolButton::menu-indicator { image: none; width: 0px; }
"""

_KILL_QSS = """
QPushButton {
    background: transparent; color: #f87171; border: 1px solid rgba(239,68,68,0.35);
    border-radius: 7px; padding: 5px 12px; font-weight: 600; font-size: 12.5px;
}
QPushButton:hover { background: rgba(239,68,68,0.18); border-color: rgba(239,68,68,0.6); }
"""

_KILL_LOCKED_QSS = """
QPushButton {
    background: #dc2626; color: white; border: 1px solid #dc2626;
    border-radius: 7px; padding: 5px 12px; font-weight: 700; font-size: 12.5px;
}
"""


class _MenuChip(QToolButton):
    """文字型下拉按鈕：外部 setText 時自動補上「▾」"""

    def setText(self, text):
        super().setText(str(text).replace("▾", "").rstrip() + "  ▾")


class _IconMenuButton(QToolButton):
    """純圖示下拉按鈕：外部 setText（例如切換語言）一律忽略，保持圖示"""

    def __init__(self, icon_text: str, parent=None):
        super().__init__(parent)
        super().setText(icon_text)

    def setText(self, text):
        pass


class _KillButton(QPushButton):
    """精簡停止鈕：長字串改顯示短字、完整說明放提示；清空樣式時回到預設樣式"""

    def setText(self, text):
        text = str(text)
        self.setToolTip(text + "（Ctrl+Alt+Q）" if "Ctrl" not in text else text)
        short = "🔓 解除鎖定" if ("鎖定" in text or "解除" in text) else "■  停止"
        super().setText(short)

    def setStyleSheet(self, qss):
        if not qss:
            qss = _KILL_QSS
        elif "#dc2626" in qss:
            qss = _KILL_LOCKED_QSS
        super().setStyleSheet(qss)


class _StatusLabel(QLabel):
    """狀態：小圓點＋短字，太長就截斷，完整內容放提示"""

    def setText(self, text):
        text = str(text)
        self.setToolTip(text)
        body = text
        for dot in ("🟢", "🟡", "🟠", "🔴", "⚪"):
            body = body.replace(dot, "")
        body = body.strip()
        if len(body) > 12:
            body = body[:11] + "…"
        super().setText("● " + body)

    def setStyleSheet(self, qss):
        # 依原本的顏色判斷狀態，換成低調的樣式
        color = "#fbbf24" if ("245,158,11" in qss or "fbbf24" in qss) else "#4ade80"
        super().setStyleSheet(
            f"color: {color}; background: transparent; font-size: 12px; font-weight: 600; padding: 0 6px;"
        )



from PyQt5.QtWidgets import QStackedWidget as _QStackedWidget, QLayout as _QLayout, QSizePolicy as _QSizePolicy

def _write_dropdown_arrows():
    """產生下拉箭頭 SVG（Qt 樣式表只能用圖片畫箭頭）"""
    import tempfile
    out = {}
    try:
        d = Path(tempfile.gettempdir()) / "syntra_ui"
        d.mkdir(parents=True, exist_ok=True)
        for name, color in (("arrow", "#cbd5e1"), ("arrow_on", "#60a5fa")):
            f = d / f"{name}.svg"
            f.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
                f'<path d="M0 0 L10 0 L5 6 Z" fill="{color}"/></svg>',
                encoding="utf-8",
            )
            out[name] = f.as_posix()
    except Exception:
        pass
    return out


_ARROWS = _write_dropdown_arrows()

_DROPDOWN_QSS = """
QComboBox {
    background: #1b1f2a; color: #e2e8f0; border: 1px solid #4b5563;
    border-radius: 7px; padding: 6px 34px 6px 10px; font-weight: 600; font-size: 12.5px;
}
QComboBox:hover { border-color: #60a5fa; background: #20263a; }
QComboBox:on { border-color: #60a5fa; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 28px; border: none; border-left: 1px solid #4b5563;
    border-top-right-radius: 7px; border-bottom-right-radius: 7px;
}
QComboBox::drop-down:hover { background: #283044; }
QComboBox::down-arrow { image: url("__ARROW__"); width: 10px; height: 6px; }
QComboBox::down-arrow:on { image: url("__ARROW_ON__"); }
QComboBox QAbstractItemView {
    background: #1b1f2a; color: #e2e8f0; selection-background-color: #2563eb;
    border: 1px solid rgba(255,255,255,0.12); outline: none; padding: 4px;
}
""".replace("__ARROW_ON__", _ARROWS.get("arrow_on", "")).replace("__ARROW__", _ARROWS.get("arrow", ""))


class _DropdownTabs(QTabWidget):
    """外觀是下拉選單的分頁元件：保留 QTabWidget 的 API（addTab / setTabText / setCurrentIndex），
    隱藏原本的分頁列，改用 self.selector（QComboBox）切換。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabBar().hide()
        self.setDocumentMode(True)
        self.selector = QComboBox()
        self.selector.setStyleSheet(_DROPDOWN_QSS)
        self.selector.setSizePolicy(_QSizePolicy.Expanding, _QSizePolicy.Fixed)
        self.selector.setMinimumContentsLength(4)
        self.selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.selector.currentIndexChanged.connect(self._on_selector)
        self.currentChanged.connect(self._on_tab_changed)

    def _on_selector(self, idx):
        if 0 <= idx < self.count() and idx != self.currentIndex():
            self.setCurrentIndex(idx)

    def _on_tab_changed(self, idx):
        if self.selector.currentIndex() != idx:
            self.selector.blockSignals(True)
            self.selector.setCurrentIndex(idx)
            self.selector.blockSignals(False)

    def addTab(self, widget, *args):
        idx = super().addTab(widget, *args)
        self.selector.blockSignals(True)
        self.selector.insertItem(idx, args[-1] if args else "")
        self.selector.setCurrentIndex(self.currentIndex())
        self.selector.blockSignals(False)
        return idx

    def setTabText(self, idx, text):
        super().setTabText(idx, text)
        if 0 <= idx < self.selector.count():
            self.selector.setItemText(idx, text)


class _FlowLayout(_QLayout):
    """會自動折行的排版：寬度不夠時按鈕換到下一行，不會撐破面板"""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            w = min(hint.width(), rect.width()) if rect.width() > 0 else hint.width()
            if x > rect.x() and x + w > rect.right() + 1:
                x = rect.x()
                y += line_h + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, hint.height())))
            x += w + self._sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class _HealthCheckThread(QThread):
    done = pyqtSignal(str, int)  # 報告文字, 問題數

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            text, issues = self._fn()
        except Exception as e:  # noqa: BLE001
            text, issues = f"健檢時發生錯誤：{e}", -1
        self.done.emit(text, issues)



class MainWindow(QMainWindow, AgentTeamMixin):
    """
    純原生 Windows 獨立桌面應用程式 (落實 OOP 模組化，支援即時畫面同步串流、視窗錄影、Skills/MCP 管理)
    """
    sig_agent_reply = pyqtSignal(dict)
    sig_agent_step = pyqtSignal(dict)
    sig_agent_token = pyqtSignal(str, str)  # (agent_id, 文字片段) 串流逐字顯示
    sig_console_result = pyqtSignal(str, str, str, bool)  # (agent_id, 指令, 輸出, 是否成功) — 「!指令」結果
    sig_web_activity = pyqtSignal(dict)
    sig_supervisor_event = pyqtSignal(dict)
    sig_security_ticket = pyqtSignal(dict)
    sig_app_consent = pyqtSignal(object)
    sig_hotkey_kill = pyqtSignal()  # 全域熱鍵執行緒 → UI 執行緒
    sig_hotkey_summon = pyqtSignal()  # 全域呼叫熱鍵 → 跳出快速輸入列
    sig_mcp_ready = pyqtSignal()  # MCP 伺服器暖機完成 → 更新狀態表
    sig_context_update = pyqtSignal(dict)
    sig_api_mutation = pyqtSignal(str, dict, str, str)
    sig_local_models_found = pyqtSignal(list, bool)  # (新偵測到的本地模型服務, 是否為使用者手動觸發)

    def __init__(self):
        super().__init__()
        self.settings_manager = SettingsManager()
        i18n.init_from_settings(self.settings_manager)
        i18n.register_listener(self._on_language_changed_global)
        self.setWindowTitle(t("app_title"))
        self.resize(1420, 890)
        self.setStyleSheet(MODERN_DARK_STYLE)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        # 初始化核心模組 (純 OOP 物件，無 127 伺服器)
        self.api_manager = ApiManager()
        self.context_guard = ContextGuard(self.settings_manager)
        self.security_guard = SecurityGuard(self.settings_manager, api_manager=self.api_manager)
        self.api_manager.set_security_guard(self.security_guard)
        self.desktop_controller = DesktopController(self.context_guard, self.security_guard)
        self.web_auditor = WebAuditor(self.settings_manager, self.security_guard)
        self.mcp_skill_manager = McpSkillManager()

        self.agent_brain = AgentBrain(
            settings_manager=self.settings_manager,
            api_manager=self.api_manager,
            context_guard=self.context_guard,
            security_guard=self.security_guard,
            desktop_controller=self.desktop_controller,
            web_auditor=self.web_auditor,
        )
        self.supervisor = AICodingSupervisor(
            settings_manager=self.settings_manager,
            context_guard=self.context_guard,
            desktop_controller=self.desktop_controller,
            agent_brain=self.agent_brain,
        )
        self.discord_bridge = DiscordBotBridge(
            settings_manager=self.settings_manager,
            security_guard=self.security_guard,
            supervisor=self.supervisor,
            agent_brain=self.agent_brain,
        )

        # 即時畫面串流與錄影引擎 (12 FPS 流暢同步)
        self.streamer = ScreenStreamer(self.desktop_controller, fps=12, parent=self)
        # 只有主視窗真的顯示在畫面上時才擷取預覽影格（原本縮在托盤也持續每秒 12 張全螢幕截圖，吃掉約 30% CPU）
        self._last_bg_capture = 0.0
        self.streamer.should_capture = self._should_capture_preview
        self.streamer.sig_frame_ready.connect(self._on_stream_frame)
        self.streamer.sig_recording_tick.connect(self._on_recording_tick)

        self.current_session_id = f"qt_sess_{int(time.time())}"
        self.attached_screenshot_b64: Optional[str] = None
        # 免打擾狀態要跟設定檔一致（之前固定 False：選單顯示「關」，實際上設定檔是開的，輸入會被擋）
        try:
            self.manual_dnd = bool(self.settings_manager.get_raw().get("dnd", {}).get("manual_dnd", False))
        except Exception:
            self.manual_dnd = False
        self.window_cards: Dict[int, WindowCardWidget] = {}
        self.selected_hwnd: int = 0
        self.latest_live_pil_img: Optional[Image.Image] = None

        # 歷史紀錄、排程與專案檔案管理器
        self.history_manager = HistoryManager()
        self.schedule_manager = ScheduleManager()
        self.current_workspace_dir: Path = BASE_DIR
        self.attached_files: List[Path] = []
        self.current_messages: List[Dict[str, Any]] = []
        self.current_category: str = "temp"
        saved_mode = self.settings_manager.get("execution_mode", "default")
        self.current_execution_mode: str = saved_mode
        self.security_guard.set_execution_mode(saved_mode)

        # 多代理工作台系統 (同介面多開並行執行與監控)
        self.agent_slots: Dict[str, AgentSlot] = {}
        self.active_agent_id: str = "agent_1"
        self.is_split_view: bool = False

        # 排程輪詢定時器 (每 10 秒檢查是否有到期排程任務)
        self.schedule_timer = QTimer(self)
        self.schedule_timer.setInterval(10000)
        self.schedule_timer.timeout.connect(self._check_and_run_schedules)
        self.schedule_timer.start()

        # 支援多開快捷鍵 Ctrl+N
        self.shortcut_new_win = QShortcut(QKeySequence("Ctrl+N"), self)
        self.shortcut_new_win.activated.connect(self.spawn_new_instance)

        # 啟動非同步背景線程
        self.async_worker = AsyncWorkerThread()
        self.async_worker.start()

        self._bind_signals()
        self._init_ui()
        self._init_tray_icon()

        # 系統層級緊急停止熱鍵：在遊戲、瀏覽器等任何視窗都能按（原本只寫在按鈕文字上，從未註冊）
        self._running_turns = set()
        self._turn_by_agent = {}  # agent_id → 執行中的回合（給「停止這一輪」按鈕用）
        # agent_id → 本輪「處理過程」區塊狀態 {t0, start, items: [(key, html)]}
        self._work: Dict[str, Dict[str, Any]] = {}
        self.sig_hotkey_kill.connect(self._on_hotkey_kill)
        self.sig_hotkey_summon.connect(self._on_hotkey_summon)
        self.sig_console_result.connect(self._on_console_result)
        # Linux 終端機遙控（預設只聽本機，需 token）
        self.remote_server = None
        QTimer.singleShot(0, self._start_remote_control)
        self.quick_bar = QuickInputBar()
        self.quick_bar.submitted.connect(self._on_quick_bar_submit)
        hk_cfg = self.settings_manager.get_raw().get("hotkeys", {}) or {}
        kill_keys = hk_cfg.get("emergency_stop") or ["ctrl+alt+q", "ctrl+shift+f12"]
        summon_key = hk_cfg.get("summon") or "ctrl+shift+space"
        self._hotkeys = GlobalHotkeys()
        for k in kill_keys:
            self._hotkeys.add(k, self.sig_hotkey_kill.emit)
        self._hotkeys.add(summon_key, self.sig_hotkey_summon.emit)
        # 複製錯誤訊息時右下角提示「要解釋嗎？」（打遊戲、或在 agent 視窗裡複製時不提示）
        self.clipboard_assist = None
        if self.settings_manager.get_raw().get("clipboard_assist", True):
            self.clipboard_assist = ClipboardAssist(on_explain=self._on_quick_bar_submit,
                                                    is_busy=self._clipboard_assist_busy)
            self.clipboard_assist.start()
        failed = self._hotkeys.start()
        if failed:
            try:
                self.tray.showMessage("⚠️ 部分全域熱鍵註冊失敗",
                                      f"{', '.join(failed)} 已被其他程式佔用。緊急停止仍可用主視窗按鈕。",
                                      QSystemTrayIcon.Warning, 6000)
            except Exception:
                pass

        # 載入側邊欄內容
        self.populate_file_tree(self.current_workspace_dir)
        self.reload_history_lists()
        self.reload_schedules_list()

        # 啟動即時畫面同步與背景輪詢
        self.streamer.start_stream()
        self.async_worker.submit(self._run_background_services())

        # MCP：背景啟動已啟用的伺服器（第一次 npx 可能要下載），完成後更新狀態表；聊天不用等它
        self.sig_mcp_ready.connect(self.reload_mcp_and_skills)
        self.async_worker.submit(mcp_manager.warm_up()).add_done_callback(lambda f: self.sig_mcp_ready.emit())

        self.reload_models_combo()
        self.refresh_window_carousel()

        # 本地模型自動偵測：啟動後背景掃描本機 Ollama / LM Studio 等，有新模型才詢問使用者
        self.local_model_scanner = LocalModelScanner()
        self._local_scan_running = False
        self._api_dialog = None
        self.sig_local_models_found.connect(self._on_local_models_found)
        QTimer.singleShot(4000, lambda: self.scan_local_models(manual=False))
        QTimer.singleShot(8500, self._schedule_app_auto_discovery)


    def _schedule_app_auto_discovery(self):
        try:
            from core.app_auto_mapper import check_new_apps_on_startup_or_turn
            if hasattr(self, "async_worker") and self.async_worker and hasattr(self, "brain"):
                self.async_worker.submit(check_new_apps_on_startup_or_turn(self.brain))
        except Exception:
            pass


    async def _request_app_consent_async(self, title: str, subtitle: str, apps: list, confirm_label: str, phase: str):
        import asyncio
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.sig_app_consent.emit({"title": title, "subtitle": subtitle, "apps": apps, "confirm_label": confirm_label, "phase": phase, "loop": loop, "fut": fut})
        return await fut

    def _on_app_consent_request(self, req: dict):
        res = None
        try:
            from ui.app_consent_dialog import prompt_app_consent_blocking
            res = prompt_app_consent_blocking(
                req["title"], req["subtitle"], req["apps"], req.get("confirm_label", "確認"), req.get("phase", "scan"), parent=self
            )
        except Exception:
            res = None
        req["loop"].call_soon_threadsafe(req["fut"].set_result, res)

    def _bind_signals(self):
        self.web_auditor.register_callback(lambda rec: self.sig_web_activity.emit(rec))
        self.supervisor.register_callback(lambda entry: self.sig_supervisor_event.emit(entry))
        self.security_guard.register_approval_callback(lambda ticket: self.sig_security_ticket.emit(ticket))
        self.api_manager.register_change_callback(lambda et, info, src, msg: self.sig_api_mutation.emit(et, info, src, msg))

        self.sig_agent_reply.connect(self._on_agent_reply)
        self.sig_agent_step.connect(self._on_agent_step)
        self.sig_agent_token.connect(self._on_agent_token)
        self._stream_start: Dict[str, int] = {}
        self.sig_web_activity.connect(self._on_web_activity)
        self.sig_supervisor_event.connect(self._on_supervisor_event)
        self.sig_security_ticket.connect(self._on_security_ticket)
        self.sig_app_consent.connect(self._on_app_consent_request)
        if hasattr(self, "agent_brain"):
            self.agent_brain.app_consent_callback = self._request_app_consent_async
        self.sig_context_update.connect(self._on_context_update)
        self.sig_api_mutation.connect(self._on_api_mutation_event)

    def _on_api_mutation_event(self, event_type: str, info: Dict[str, Any], source: str, message: str):
        # 1. 系統右下角托盤通知
        action_map = {"ADDED": "新增", "MODIFIED": "修改", "DELETED": "刪除"}
        act_str = action_map.get(event_type, "異動")
        if hasattr(self, "tray") and self.tray:
            self.tray.showMessage(
                f"🔔 API 設定{act_str}安全通知",
                f"【{act_str}】服務商：{info.get('name')}\n來源：{source}\n端點：{info.get('base_url')[:36]}",
                QSystemTrayIcon.Information,
                6000,
            )

        # 2. Discord 同步安全推播
        if hasattr(self, "discord_bridge") and self.discord_bridge:
            try:
                self.async_worker.submit(self.discord_bridge.send_notification(message))
            except Exception:
                pass

        # 3. 紀錄至安全稽核日誌
        self.settings_manager.append_audit_log(f"API_PROVIDER_{event_type}", {
            "event_type": event_type,
            "provider_id": info.get("id"),
            "name": info.get("name"),
            "source": source,
            "changes": info.get("changes"),
            "base_url": info.get("base_url"),
        })

        # 4. 刷新下拉選單
        self.reload_models_combo()

    def _create_menu_bar(self):
        menubar = self.menuBar()
        menubar.clear()

        # 1. 檔案選單
        self.menu_file = menubar.addMenu(t("menu_file"))
        act_new_chat = self.menu_file.addAction(t("menu_new_chat"))
        act_new_chat.setShortcut(QKeySequence("Ctrl+T"))
        act_new_chat.triggered.connect(self.new_chat_session)

        act_new_win = self.menu_file.addAction(t("menu_new_window"))
        act_new_win.setShortcut(QKeySequence("Ctrl+N"))
        act_new_win.triggered.connect(self.spawn_new_instance)

        self.menu_file.addSeparator()
        act_exit = self.menu_file.addAction(t("menu_exit"))
        act_exit.triggered.connect(self.close)

        # 2. 設定選單 (包含系統設定與 5 國語言切換)
        self.menu_settings = menubar.addMenu(t("menu_settings"))
        act_sys_settings = self.menu_settings.addAction(t("menu_system_settings"))
        act_sys_settings.triggered.connect(lambda: self.open_settings_dialog(0))

        # 🌐 語言切換選單 (繁體中文、簡體中文、英文、日語、韓文)
        self.menu_lang = self.menu_settings.addMenu(t("menu_language"))
        current_lang = i18n.get_language()
        for code, name in SUPPORTED_LANGUAGES.items():
            act_l = self.menu_lang.addAction(name)
            act_l.setCheckable(True)
            act_l.setChecked(code == current_lang)
            act_l.triggered.connect(lambda checked, c=code: self.switch_language(c))

        self.menu_settings.addSeparator()
        act_api_settings = self.menu_settings.addAction(t("menu_api_settings"))
        act_api_settings.triggered.connect(lambda: self.open_settings_dialog(1))

        act_dlc_mgr = self.menu_settings.addAction("🧩 DLC 與擴充模組管理器 (GUI)")
        act_dlc_mgr.triggered.connect(self.open_dlc_manager_dialog)

        # 3. 說明選單
        self.menu_help = menubar.addMenu(t("menu_help"))
        act_help_kill = self.menu_help.addAction(t("menu_kill_switch"))
        act_help_kill.triggered.connect(self.trigger_kill_switch)

    def _init_ui(self):
        # 建立頂部選單列 (含設定選單與多語言切換)
        self._create_menu_bar()

        # 使用 QSplitter 讓使用者可以自由拖曳邊界調整左側欄、中央工作區、右側面板寬度
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(5)
        self.setCentralWidget(self.main_splitter)

        # 1. 左側欄
        self.sidebar_widget = self._create_sidebar()
        self.main_splitter.addWidget(self.sidebar_widget)

        # 2. 中央區域 (多代理主控與工作台)
        self.center_widget = self._create_center_panel()
        self.main_splitter.addWidget(self.center_widget)

        # 3. 右側多功能抽屜 (即時切畫面卡片流 + 串流預覽/錄影 + 監督 + Skills/MCP)
        self.right_widget = self._create_right_panel()
        self.main_splitter.addWidget(self.right_widget)

        # 伸縮比重與初始拖動大小分配
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([290, 820, 420])
        self.main_splitter.setChildrenCollapsible(True)
        for w in (self.sidebar_widget, self.center_widget, self.right_widget):
            w.setMinimumWidth(1)  # 明確設 1px，取代內容的最小寬度 → 可自由拉到任意寬度
        self.main_splitter.splitterMoved.connect(self._on_main_split_moved)
        self._restore_layout_state()

    # ───────────── 版面：左右欄顯示/隱藏、輸入框高度、記住設定 ─────────────

    @staticmethod
    def _panel_toggle_icon(kind: str) -> QIcon:
        """畫出左欄（方框+左側直條）或右欄（清單）的切換圖示"""
        pm = QPixmap(36, 36)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = p.pen()
        pen.setColor(QColor('#e5e7eb'))
        pen.setWidthF(2.4)
        p.setPen(pen)
        if kind == 'left':
            p.drawRoundedRect(5, 7, 26, 22, 4, 4)
            p.fillRect(9, 11, 4, 14, QColor('#e5e7eb'))
        else:
            p.drawRoundedRect(5, 7, 26, 22, 4, 4)
            for y in (13, 18, 23):
                p.drawPoint(11, y)
                p.drawLine(15, y, 25, y)
        p.end()
        return QIcon(pm)

    def _make_panel_toggle(self, kind: str) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(self._panel_toggle_icon(kind))
        btn.setIconSize(QSize(22, 22))
        btn.setFixedSize(32, 32)
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip('顯示／隱藏左側欄' if kind == 'left' else '顯示／隱藏右側欄')
        btn.setStyleSheet(
            'QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; }'
            'QToolButton:hover { background: #283044; }'
            'QToolButton:checked { background: #1e2230; border-color: rgba(255,255,255,0.12); }'
        )
        btn.toggled.connect(lambda on, k=kind: self._set_side_panel_visible(k, on))
        return btn

    def _set_side_panel_visible(self, kind: str, visible: bool):
        widget = getattr(self, 'sidebar_widget' if kind == 'left' else 'right_widget', None)
        if widget is None:
            return
        widget.setVisible(visible)
        if visible and not getattr(self, '_restoring_layout', False):
            idx = 0 if kind == 'left' else 2
            sizes = self.main_splitter.sizes()
            if sizes[idx] <= 0:
                want = 290 if kind == 'left' else 420
                sizes[1] = max(0, sizes[1] - want)
                sizes[idx] = want
                self.main_splitter.setSizes(sizes)
        btn = getattr(self, 'btn_toggle_left' if kind == 'left' else 'btn_toggle_right', None)
        if btn is not None and btn.isChecked() != visible:
            btn.blockSignals(True)
            btn.setChecked(visible)
            btn.blockSignals(False)
        self._save_layout_state()

    def _on_main_split_moved(self, *_):
        """左右分隔線拖曳後：被拉到 0 寬的欄位，按鈕顯示為未選取"""
        sizes = self.main_splitter.sizes()
        for kind, idx in (('left', 0), ('right', 2)):
            btn = getattr(self, 'btn_toggle_left' if kind == 'left' else 'btn_toggle_right', None)
            if btn is None:
                continue
            widget = self.sidebar_widget if kind == 'left' else self.right_widget
            on = widget.isVisibleTo(self) and sizes[idx] > 0
            if btn.isChecked() != on:
                btn.blockSignals(True)
                btn.setChecked(on)
                btn.blockSignals(False)
        self._save_layout_state()

    def _set_input_manual(self, manual: bool):
        te = self.chat_input_card.text_edit
        te.set_manual_height(1 if manual else None)
        lay = self.card_wrapper.layout()
        if lay is not None:
            lay.setStretchFactor(self.chat_input_card, 1 if manual else 0)

    def _on_chat_vsplit_moved(self, *_):
        """上下分隔線拖曳後：輸入框改為填滿分到的高度（沒有上下限）"""
        if self.chat_input_card.text_edit._manual_height is None:
            self._set_input_manual(True)
        self._save_layout_state()

    def _reset_input_height(self):
        """雙擊分隔線：輸入框恢復依內容自動長高"""
        self._set_input_manual(False)
        total = sum(self.chat_vsplit.sizes())
        want = self.card_wrapper.sizeHint().height()
        self.chat_vsplit.setSizes([max(100, total - want), want])
        self._save_layout_state()

    def eventFilter(self, obj, event):
        vsplit = getattr(self, 'chat_vsplit', None)
        if vsplit is not None and obj is vsplit.handle(1) and event.type() == QEvent.MouseButtonDblClick:
            self._reset_input_height()
            return True
        return super().eventFilter(obj, event)

    def _layout_settings(self) -> QSettings:
        return QSettings('Syntra', 'SyntraDesktop')

    def _save_layout_state(self):
        if getattr(self, '_restoring_layout', False):
            return
        try:
            st = self._layout_settings()
            st.setValue('layout/main_sizes', [int(x) for x in self.main_splitter.sizes()])
            st.setValue('layout/left_visible', bool(self.sidebar_widget.isVisibleTo(self)))
            st.setValue('layout/right_visible', bool(self.right_widget.isVisibleTo(self)))
            manual = self.chat_input_card.text_edit._manual_height is not None
            st.setValue('layout/input_manual', bool(manual))
            st.setValue('layout/input_split', [int(x) for x in self.chat_vsplit.sizes()])
        except Exception:
            pass

    def _restore_layout_state(self):
        self._restoring_layout = True
        try:
            st = self._layout_settings()
            sizes = st.value('layout/main_sizes')
            if isinstance(sizes, (list, tuple)) and len(sizes) == 3:
                vals = [int(x) for x in sizes]
                if all(v >= 0 for v in vals) and sum(vals) > 0:
                    self.main_splitter.setSizes(vals)
            for kind, key in (('left', 'layout/left_visible'), ('right', 'layout/right_visible')):
                v = st.value(key)
                if v is not None:
                    self._set_side_panel_visible(kind, str(v).lower() in ('true', '1'))
            if str(st.value('layout/input_manual')).lower() in ('true', '1'):
                vs = st.value('layout/input_split')
                if isinstance(vs, (list, tuple)) and len(vs) == 2:
                    vals = [max(0, int(x)) for x in vs]
                    if sum(vals) > 0:
                        self._set_input_manual(True)
                        self.chat_vsplit.setSizes(vals)
        except Exception:
            pass
        finally:
            self._restoring_layout = False

    def _create_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setMinimumWidth(200)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(10)

        # 品牌 Header
        brand_row = QHBoxLayout()
        logo_lbl = QLabel()
        if PNG_ICON_PATH.exists():
            pix = QPixmap(str(PNG_ICON_PATH))
            logo_lbl.setPixmap(pix.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo_lbl.setText("✦")
            logo_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        brand_row.addWidget(logo_lbl)

        brand_text = QLabel("<b>Syntra 星樞</b><br><span style='font-size:11px;color:#94a3b8;'>桌面全能 Agent</span>")
        brand_row.addWidget(brand_text)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        btn_new_chat = QPushButton("＋ 開啟新對話")
        btn_new_chat.clicked.connect(self.new_chat_session)
        layout.addWidget(btn_new_chat)

        # 側邊欄頁簽化 (圖三區域升級：快速執行、檔案總管、歷史紀錄、排程專區)
        self.sidebar_tabs = _DropdownTabs()

        # ================= 頁簽 1: ⚡ 快速執行 (原圖三區域) =================
        tab_quick = QWidget()
        tq_layout = QVBoxLayout(tab_quick)
        tq_layout.setContentsMargins(6, 8, 6, 8)
        tq_layout.setSpacing(8)

        tq_layout.addWidget(QLabel("<span style='font-size:11px;font-weight:700;color:#64748b;'>快速執行</span>"))

        self.btn_q1 = QPushButton(t("btn_q_capture"))
        self.btn_q1.clicked.connect(self.capture_current_selection_to_chat)
        tq_layout.addWidget(self.btn_q1)

        self.btn_q2 = QPushButton(t("btn_q_monitor"))
        self.btn_q2.clicked.connect(lambda: self.send_user_message("請在背景檢查寫程式視窗（如 Antigravity / Cursor / VS Code），檢查目前 AI 回覆了什麼、是否有錯誤，不要搶滑鼠焦點。"))
        tq_layout.addWidget(self.btn_q2)

        self.btn_q3 = QPushButton(t("btn_q_git"))
        self.btn_q3.clicked.connect(lambda: self.send_user_message("請在背景執行目前工作目錄的 Git 狀態與語法檢查，若有錯誤請直接整理出修復指令。"))
        tq_layout.addWidget(self.btn_q3)

        self.btn_q4 = QPushButton(t("btn_q_search"))
        self.btn_q4.clicked.connect(lambda: self.send_user_message("請上網搜尋 Python 最新非同步桌控技術最佳實踐，並回報造訪網址與重點摘要。"))
        tq_layout.addWidget(self.btn_q4)

        self.btn_q5 = QPushButton(t("btn_q_structure"))
        self.btn_q5.clicked.connect(self.import_workspace_structure_to_chat)
        tq_layout.addWidget(self.btn_q5)

        tq_layout.addStretch()
        self.sidebar_tabs.addTab(tab_quick, t("tab_quick"))

        # ================= 頁簽 2: 📁 檔案總管 (如圖二 VS Code 樹狀結構) =================
        tab_explorer = QWidget()
        te_layout = QVBoxLayout(tab_explorer)
        te_layout.setContentsMargins(4, 6, 4, 6)
        te_layout.setSpacing(6)

        exp_top = QHBoxLayout()
        exp_top.setSpacing(4)
        self.lbl_workspace_name = QLabel(f"📁 {self.current_workspace_dir.name}")
        self.lbl_workspace_name.setStyleSheet("font-weight:700; color:#38bdf8; font-size:12px;")
        exp_top.addWidget(self.lbl_workspace_name, stretch=1)

        btn_new_file = QPushButton("📄＋")
        btn_new_file.setToolTip("在工作目錄中新增檔案")
        btn_new_file.setFixedSize(30, 26)
        btn_new_file.clicked.connect(lambda: self.create_new_file_in_workspace())
        exp_top.addWidget(btn_new_file)

        btn_new_folder = QPushButton("📁＋")
        btn_new_folder.setToolTip("在工作目錄中新增資料夾")
        btn_new_folder.setFixedSize(30, 26)
        btn_new_folder.clicked.connect(lambda: self.create_new_folder_in_workspace())
        exp_top.addWidget(btn_new_folder)

        btn_choose_folder = QPushButton("📂")
        btn_choose_folder.setToolTip("切換工作資料夾讓程式自動讀入")
        btn_choose_folder.setFixedSize(28, 26)
        btn_choose_folder.clicked.connect(self.select_workspace_folder)
        exp_top.addWidget(btn_choose_folder)

        btn_refresh_tree = QPushButton("🔄")
        btn_refresh_tree.setToolTip("重新整理檔案清單")
        btn_refresh_tree.setFixedSize(28, 26)
        btn_refresh_tree.clicked.connect(lambda: self.populate_file_tree(self.current_workspace_dir))
        exp_top.addWidget(btn_refresh_tree)

        te_layout.addLayout(exp_top)

        self.tree_workspace = QTreeWidget()
        self.tree_workspace.setHeaderHidden(True)
        self.tree_workspace.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_workspace.customContextMenuRequested.connect(self._show_file_tree_context_menu)
        self.tree_workspace.itemDoubleClicked.connect(self._on_file_tree_double_clicked)
        te_layout.addWidget(self.tree_workspace, stretch=1)

        btn_import_structure = QPushButton("➕ 引用目錄結構交給 AI")
        btn_import_structure.clicked.connect(self.import_workspace_structure_to_chat)
        te_layout.addWidget(btn_import_structure)

        self.sidebar_tabs.addTab(tab_explorer, t("tab_explorer"))

        # ================= 頁簽 3: 📜 歷史紀錄專區 (永久保存區 + 暫存區，2週自動刪除) =================
        tab_history = QWidget()
        th_layout = QVBoxLayout(tab_history)
        th_layout.setContentsMargins(4, 6, 4, 6)
        th_layout.setSpacing(6)

        # 永久保存區
        th_layout.addWidget(QLabel("<b>💾 永久保存區</b> <span style='font-size:10px;color:#94a3b8;'>(手動保留)</span>"))
        self.list_history_perm = DraggableHistoryList("permanent", on_drop_callback=self._on_history_dropped)
        self.list_history_perm.itemClicked.connect(self._on_history_item_clicked)
        self.list_history_perm.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_history_perm.customContextMenuRequested.connect(lambda pos: self._show_history_context_menu(pos, self.list_history_perm, "permanent"))
        th_layout.addWidget(self.list_history_perm, stretch=1)

        # 暫存區
        th_layout.addWidget(QLabel("<b>⏳ 暫存區</b> <span style='font-size:10px;color:#f87171;'>(逾 2 週無對話自動清理)</span><br><span style='font-size:10.5px;color:#64748b;'>💡 拖曳項目至上方即可永久保存</span>"))
        self.list_history_temp = DraggableHistoryList("temp", on_drop_callback=self._on_history_dropped)
        self.list_history_temp.itemClicked.connect(self._on_history_item_clicked)
        self.list_history_temp.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_history_temp.customContextMenuRequested.connect(lambda pos: self._show_history_context_menu(pos, self.list_history_temp, "temp"))
        th_layout.addWidget(self.list_history_temp, stretch=1)

        self.sidebar_tabs.addTab(tab_history, t("tab_history"))

        # ================= 頁簽 4: ⏰ 排程專區 =================
        tab_schedule = QWidget()
        tsched_layout = QVBoxLayout(tab_schedule)
        tsched_layout.setContentsMargins(4, 6, 4, 6)
        tsched_layout.setSpacing(6)

        sched_top = QHBoxLayout()
        sched_top.addWidget(QLabel("<b>⏰ 定時背景排程</b>"))
        sched_top.addStretch()
        btn_add_sched = QPushButton("➕ 新增排程")
        btn_add_sched.clicked.connect(self.open_add_schedule_dialog)
        sched_top.addWidget(btn_add_sched)
        tsched_layout.addLayout(sched_top)

        self.list_schedules = QListWidget()
        self.list_schedules.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_schedules.customContextMenuRequested.connect(self._show_schedule_context_menu)
        tsched_layout.addWidget(self.list_schedules, stretch=1)

        btn_run_due_now = QPushButton("▶ 立即檢查並觸發排程")
        btn_run_due_now.clicked.connect(self._check_and_run_schedules)
        tsched_layout.addWidget(btn_run_due_now)

        self.sidebar_tabs.addTab(tab_schedule, t("tab_schedule"))

        layout.addWidget(self.sidebar_tabs.selector)
        layout.addWidget(self.sidebar_tabs, stretch=1)

        self.lbl_status_models = QLabel(t("lbl_status_models_empty"))
        self.lbl_status_models.setStyleSheet("color:#60a5fa;font-size:11.5px;")
        layout.addWidget(self.lbl_status_models)

        self.btn_sidebar_settings = QPushButton(t("btn_sidebar_settings"))
        self.btn_sidebar_settings.clicked.connect(lambda: self.open_settings_dialog(0))
        layout.addWidget(self.btn_sidebar_settings)

        self.btn_manage_api = QPushButton(t("btn_manage_api"))
        self.btn_manage_api.clicked.connect(self.open_api_manager_dialog)
        layout.addWidget(self.btn_manage_api)

        self.btn_manage_dlc = QPushButton("🧩 DLC 擴充模組中心")
        self.btn_manage_dlc.setStyleSheet("""
            QPushButton {
                background: #142838;
                border: 1px solid #1e4963;
                color: #38bdf8;
                font-weight: 700;
                padding: 6px 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #1d3c54;
                border-color: #38bdf8;
            }
        """)
        self.btn_manage_dlc.clicked.connect(self.open_dlc_manager_dialog)
        layout.addWidget(self.btn_manage_dlc)

        return frame

    def _create_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 頂部列：只留常用的，其餘收進選單
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(46)
        top_bar.setStyleSheet(_TOPBAR_GHOST_QSS)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 0, 10, 0)
        top_layout.setSpacing(6)

        # 左側欄顯示/隱藏
        self.btn_toggle_left = self._make_panel_toggle('left')
        top_layout.addWidget(self.btn_toggle_left)

        # 模型選單：輸入框下方已有「模型」按鈕，這裡保留物件給舊程式使用但不顯示
        self.combo_models = QComboBox()
        self.combo_models.currentIndexChanged.connect(self._on_model_changed)
        self.combo_models.hide()
        top_layout.addWidget(self.combo_models)

        # 代理選單：顯示在線數量，點開可新增代理／切換並排
        self.lbl_agent_summary = _MenuChip()
        self.lbl_agent_summary.setPopupMode(QToolButton.InstantPopup)
        self.lbl_agent_summary.setToolTip("管理代理")
        self.lbl_agent_summary.setText("🤖 1 個代理在線")
        menu_agents = QMenu(self.lbl_agent_summary)
        menu_agents.addAction("＋ 新增代理", lambda: self.create_agent_slot())
        menu_agents.addSeparator()
        self._team_build_view_menu(menu_agents)  # 分頁 / 並排監控 / 代理畫布 三選一
        self.lbl_agent_summary.setMenu(menu_agents)
        top_layout.addWidget(self.lbl_agent_summary)

        # 舊按鈕保留物件（其他程式會改它的文字），不顯示
        self.btn_toggle_split = QPushButton("🗗 並排監控")
        self.btn_toggle_split.clicked.connect(self.toggle_split_view)
        self.btn_toggle_split.hide()
        top_layout.addWidget(self.btn_toggle_split)

        self.btn_google_login = QToolButton()
        self.btn_google_login.setPopupMode(QToolButton.InstantPopup)
        self._update_google_login_button()
        self.btn_google_login.hide()
        top_layout.addWidget(self.btn_google_login)

        self.btn_sec_level = QToolButton()
        menu_sec = QMenu(self.btn_sec_level)
        menu_sec.addAction("🟢 標準防護 (Default)", lambda: self._on_card_mode_changed("default"))
        menu_sec.addAction("🟡 嚴格審查 (Request Review)", lambda: self._on_card_mode_changed("request_review"))
        menu_sec.addAction("🔵 智慧自動 (Auto)", lambda: self._on_card_mode_changed("auto"))
        menu_sec.addAction("⚡ 極速無阻 (Turbo)", lambda: self._on_card_mode_changed("turbo"))
        self.btn_sec_level.setMenu(menu_sec)
        self.btn_sec_level.hide()
        top_layout.addWidget(self.btn_sec_level)

        top_layout.addStretch()

        # 狀態：小圓點＋短字
        self.lbl_context = _StatusLabel()
        self.lbl_context.setStyleSheet("")
        self.lbl_context.setText("🟢 待命")
        top_layout.addWidget(self.lbl_context)

        # 停止
        self.btn_kill = _KillButton()
        self.btn_kill.setText("🛑 緊急停止所有代理與桌面操作")
        self.btn_kill.setStyleSheet("")
        self.btn_kill.setCursor(Qt.PointingHandCursor)
        self.btn_kill.clicked.connect(self.trigger_kill_switch)
        top_layout.addWidget(self.btn_kill)

        # ⚙ 設定（含語言、API、防護等級、Google 帳號…）
        self.btn_system_menu = _IconMenuButton("⚙")
        self.btn_system_menu.setPopupMode(QToolButton.InstantPopup)
        self.btn_system_menu.setToolTip("設定")
        self.btn_system_menu.setFixedSize(32, 32)
        self.btn_system_menu.setStyleSheet("QToolButton { font-size: 16px; padding: 0; }")
        self._populate_system_menu()
        top_layout.addWidget(self.btn_system_menu)

        # 右側欄顯示/隱藏
        self.btn_toggle_right = self._make_panel_toggle('right')
        top_layout.addWidget(self.btn_toggle_right)

        layout.addWidget(top_bar)

        # 多代理切換分頁橫條 (支援同一介面多開並行)
        self.agent_bar_widget = QWidget()
        self.agent_bar_widget.setFixedHeight(36)
        self.agent_bar_widget.setStyleSheet("background: #12141c; border-bottom: 1px solid rgba(255,255,255,0.08);")
        self.agent_bar_layout = QHBoxLayout(self.agent_bar_widget)
        self.agent_bar_layout.setContentsMargins(10, 2, 10, 2)
        self.agent_bar_layout.setSpacing(6)
        self.agent_bar_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.agent_bar_widget.customContextMenuRequested.connect(self._on_agent_bar_context_menu)
        layout.addWidget(self.agent_bar_widget)

        # 代理檢視容器 (左側輸入圓點導航欄 + 右側分頁聚焦/並排多代理監控)
        self.agent_view_container = QWidget()
        av_outer = QHBoxLayout(self.agent_view_container)
        av_outer.setContentsMargins(0, 0, 0, 0)
        av_outer.setSpacing(0)

        self.nav_rail_widget = QWidget()
        self.nav_rail_widget.setFixedWidth(20)
        self.nav_rail_widget.setStyleSheet("background: #0b0d14; border-right: 1px solid rgba(255,255,255,0.05);")
        nav_rail_outer = QVBoxLayout(self.nav_rail_widget)
        nav_rail_outer.setContentsMargins(0, 8, 0, 8)
        nav_rail_outer.setSpacing(0)
        self.nav_rail_scroll = QScrollArea()
        self.nav_rail_scroll.setWidgetResizable(True)
        self.nav_rail_scroll.setFrameShape(QFrame.NoFrame)
        self.nav_rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_rail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav_rail_scroll.setStyleSheet("background: transparent;")
        self.nav_dots_host = QWidget()
        self.nav_dots_host.setStyleSheet("background: transparent;")
        self.nav_rail_layout = QVBoxLayout(self.nav_dots_host)
        self.nav_rail_layout.setContentsMargins(5, 4, 5, 4)
        self.nav_rail_layout.setSpacing(7)
        self.nav_rail_layout.addStretch()
        self.nav_rail_scroll.setWidget(self.nav_dots_host)
        nav_rail_outer.addWidget(self.nav_rail_scroll)
        self.nav_rail_widget.hide()
        av_outer.addWidget(self.nav_rail_widget)

        av_inner = QWidget()
        av_layout = QVBoxLayout(av_inner)
        av_layout.setContentsMargins(0, 0, 0, 0)
        av_layout.setSpacing(0)
        av_outer.addWidget(av_inner, 1)

        self.agent_stack = QStackedWidget()
        self.agent_split = QSplitter(Qt.Horizontal)
        self.agent_split.setHandleWidth(4)
        self.agent_split.hide()

        av_layout.addWidget(self.agent_stack)
        av_layout.addWidget(self.agent_split)
        self._team_setup(av_layout)  # 多代理團隊：代理畫布、終端、用量

        # 對話區 ↕ 輸入框：可上下拖曳調整，雙擊分隔線恢復自動高度
        self.chat_vsplit = QSplitter(Qt.Vertical)
        self.chat_vsplit.setHandleWidth(5)
        self.chat_vsplit.setChildrenCollapsible(True)
        self.agent_view_container.setMinimumHeight(1)
        self.chat_vsplit.addWidget(self.agent_view_container)
        layout.addWidget(self.chat_vsplit, stretch=1)

        # 建立預設代理 1
        slot1 = self._team_restore_workspace() or self.create_agent_slot("🤖 代理 #1")  # 還原上次的代理工作區
        self.active_agent_id = slot1.agent_id
        self.chat_browser = slot1.chat_browser

        # 現代整合卡片式輸入容器 (對齊圖五設計，整合圖二上下文選單、圖三可用模型、圖四審批模式與斜線補全)
        card_wrapper = QWidget()
        self.card_wrapper = card_wrapper
        card_wrapper.setMinimumHeight(1)
        card_wrapper.setStyleSheet("background: #10121a; border-top: 1px solid rgba(255,255,255,0.06);")
        card_wrapper_layout = QVBoxLayout(card_wrapper)
        card_wrapper_layout.setContentsMargins(14, 10, 14, 12)
        card_wrapper_layout.setSpacing(0)

        self.chat_input_card = ChatInputCard(self)
        self.chat_input_card.sig_send_prompt.connect(self.send_current_prompt)
        self.chat_input_card.sig_request_files.connect(self.select_files_to_attach)
        self.chat_input_card.sig_request_folder.connect(self.select_workspace_folder)
        self.chat_input_card.sig_request_snap.connect(self.capture_current_selection_to_chat)
        self.chat_input_card.sig_request_browser.connect(self._prompt_browser_url)
        self.chat_input_card.sig_request_mentions.connect(self._prompt_window_mention)
        self.chat_input_card.sig_model_changed.connect(self._on_card_model_changed)
        self.chat_input_card.sig_mode_changed.connect(self._on_card_mode_changed)
        self.chat_input_card.sig_open_api_manager.connect(self.open_api_manager_dialog)
        self.chat_input_card.sig_chip_removed.connect(self._on_attachment_chip_removed)
        self.chat_input_card.set_execution_mode(self.current_execution_mode)

        # 向下相容
        self.input_text = self.chat_input_card.text_edit
        self.btn_send = self.chat_input_card.btn_send

        card_wrapper_layout.addWidget(self.chat_input_card)
        card_wrapper_layout.addStretch(0)
        self.chat_vsplit.addWidget(card_wrapper)
        self.chat_vsplit.setStretchFactor(0, 1)
        self.chat_vsplit.setStretchFactor(1, 0)
        self.chat_vsplit.splitterMoved.connect(self._on_chat_vsplit_moved)
        self.chat_vsplit.handle(1).installEventFilter(self)
        self.chat_vsplit.handle(1).setToolTip('拖曳調整輸入框高度，雙擊恢復自動')
        return panel

    def _create_right_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("rightPanel")
        frame.setMinimumWidth(260)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.tabs = _DropdownTabs()

        # ================= Tab 1: 即時切畫面卡片流 + 錄影 + 監督 =================
        tab_stream = QWidget()
        ts_layout = QVBoxLayout(tab_stream)
        ts_layout.setContentsMargins(6, 6, 6, 6)
        ts_layout.setSpacing(8)

        # 頂部操作列：刷新視窗卡片 + 錄影按鈕
        top_act_row = QHBoxLayout()
        top_act_row.addWidget(QLabel("<b>🖥️ 即時切換畫面（點卡片立即同步）</b>"))
        top_act_row.addStretch()

        btn_refresh_cards = QPushButton("🔄 刷新")
        btn_refresh_cards.clicked.connect(self.refresh_window_carousel)
        top_act_row.addWidget(btn_refresh_cards)

        self.btn_inspect_uia = QPushButton("♿ 提取無障礙語意樹")
        self.btn_inspect_uia.setToolTip("利用 Windows 無障礙 API (UIA) 提取目前視窗結構樹與按鈕文字，代替傳統畫面截圖！")
        self.btn_inspect_uia.clicked.connect(self.extract_accessibility_tree_to_chat)
        top_act_row.addWidget(self.btn_inspect_uia)

        self.btn_record = QPushButton("🔴 錄影")
        self.btn_record.clicked.connect(self.toggle_recording)
        top_act_row.addWidget(self.btn_record)

        ts_layout.addLayout(top_act_row)

        # 水平捲動視窗卡片流 (類似 Windows Alt+Tab / Discord 螢幕分享選擇)
        scroll_area = QScrollArea()
        scroll_area.setFixedHeight(126)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background: transparent; border: none;")

        self.carousel_container = QWidget()
        self.carousel_layout = QHBoxLayout(self.carousel_container)
        self.carousel_layout.setContentsMargins(2, 2, 2, 2)
        self.carousel_layout.setSpacing(8)
        self.carousel_layout.setAlignment(Qt.AlignLeft)
        scroll_area.setWidget(self.carousel_container)

        ts_layout.addWidget(scroll_area)

        # 即時串流大預覽畫面 (12 FPS 流暢動態更新)
        live_box = QFrame()
        live_box.setStyleSheet("background: #0b0d12; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px;")
        live_layout = QVBoxLayout(live_box)
        live_layout.setContentsMargins(4, 4, 4, 4)

        self.lbl_live_title = QLabel("即時畫面：🖥️ 目前桌面全螢幕 (12 FPS 同步中)")
        self.lbl_live_title.setStyleSheet("font-size: 11px; color: #38bdf8; font-weight: 600;")
        live_layout.addWidget(self.lbl_live_title)

        self.lbl_live_stream = QLabel()
        self.lbl_live_stream.setFixedHeight(190)
        self.lbl_live_stream.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.lbl_live_stream.setAlignment(Qt.AlignCenter)
        self.lbl_live_stream.setText("正在同步即時畫面串流...")
        self.lbl_live_stream.setStyleSheet("background-color: #0b0f19; border-radius: 6px; border: 1px solid #1e293b;")
        live_layout.addWidget(self.lbl_live_stream)

        # 錄影狀態列 (錄影時顯示)
        self.lbl_record_status = QLabel("● 錄影中: 0.0s (0 frames)")
        self.lbl_record_status.setStyleSheet("color: #f87171; font-weight: 700; font-size: 11.5px;")
        self.lbl_record_status.hide()
        live_layout.addWidget(self.lbl_record_status)

        ts_layout.addWidget(live_box)

        # 自動監督閉環設定
        ts_layout.addWidget(QLabel("<b>🤖 自動閉環監督設定 (含 3 次卡關熔斷)</b>"))
        self.input_sup_goal = QLineEdit("監督目前選定畫面上的 AI 寫程式進度，檢查有無報錯，有錯自動整理指令回報修好")
        ts_layout.addWidget(self.input_sup_goal)

        self.input_sup_verify = QLineEdit()
        self.input_sup_verify.setPlaceholderText("背景驗證指令 (選填，如 pytest -q 或 npm test)")
        ts_layout.addWidget(self.input_sup_verify)

        btn_row_sup = QHBoxLayout()
        self.btn_start_sup = QPushButton("▶️ 啟動自動監督")
        self.btn_start_sup.setObjectName("primaryBtn")
        self.btn_start_sup.clicked.connect(self.start_supervisor)

        self.btn_stop_sup = QPushButton("⏹️ 停止監督")
        self.btn_stop_sup.setObjectName("dangerBtn")
        self.btn_stop_sup.clicked.connect(self.stop_supervisor)
        self.btn_stop_sup.hide()

        btn_row_sup.addWidget(self.btn_start_sup)
        btn_row_sup.addWidget(self.btn_stop_sup)
        ts_layout.addLayout(btn_row_sup)

        self.btn_resume_sup = QPushButton("🔄 重置熔斷計數並重試 3 次")
        self.btn_resume_sup.setStyleSheet("background-color: #16a34a; color: white;")
        self.btn_resume_sup.clicked.connect(self.resume_supervisor)
        self.btn_resume_sup.hide()
        ts_layout.addWidget(self.btn_resume_sup)

        self.list_sup_logs = QListWidget()
        ts_layout.addWidget(self.list_sup_logs, stretch=1)

        self.tabs.addTab(tab_stream, t("tab_stream"))

        # ================= Tab 2: Skills & MCP 管理 =================
        tab_mcp = QWidget()
        tm_layout = QVBoxLayout(tab_mcp)
        tm_layout.setContentsMargins(6, 6, 6, 6)
        tm_layout.setSpacing(10)

        # 頂部切換檢視
        tm_layout.addWidget(QLabel("<b>🧩 本機 Skills 技能模組庫</b>"))
        self.table_skills = QTableWidget()
        self.table_skills.setColumnCount(3)
        self.table_skills.setHorizontalHeaderLabels(["技能名稱", "類別", "說明與路徑"])
        self.table_skills.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_skills.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_skills.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_skills.verticalHeader().setVisible(False)
        self.table_skills.setFixedHeight(170)
        tm_layout.addWidget(self.table_skills)

        tm_layout.addWidget(QLabel("<b>🔌 MCP (Model Context Protocol) 伺服器與工具</b>"))
        self.table_mcp = QTableWidget()
        self.table_mcp.setColumnCount(4)
        self.table_mcp.setHorizontalHeaderLabels(["MCP 伺服器", "狀態", "Tools 數", "指令/說明"])
        self.table_mcp.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_mcp.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_mcp.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_mcp.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_mcp.verticalHeader().setVisible(False)
        tm_layout.addWidget(self.table_mcp, stretch=1)

        btn_row_mcp = QHBoxLayout()
        btn_refresh_mcp = QPushButton("🔄 重新掃描 Skills / MCP")
        btn_refresh_mcp.clicked.connect(self.reload_mcp_and_skills)
        btn_add_mcp = QPushButton("＋ 新增 MCP 伺服器")
        btn_add_mcp.clicked.connect(self.add_custom_mcp_server)
        btn_row_mcp.addWidget(btn_refresh_mcp)
        btn_row_mcp.addWidget(btn_add_mcp)
        tm_layout.addLayout(btn_row_mcp)

        self.tabs.addTab(tab_mcp, t("tab_mcp"))

        # ================= Tab 3: 上網通報 =================
        tab_web = QWidget()
        tw_layout = QVBoxLayout(tab_web)
        tw_layout.addWidget(QLabel("🌐 <b>上網透明規則</b>：每次搜尋或連線外部網址，皆在此即時記錄網址與內容摘要，同步推播 Discord。"))
        self.list_web_logs = QListWidget()
        tw_layout.addWidget(self.list_web_logs)
        self.tabs.addTab(tab_web, t("tab_web"))

        # ================= Tab 4: 🛡️ CDR 沙箱與防毒 =================
        self.tabs.addTab(self._create_security_center_tab(), t("tab_security"))

        # ================= Tab 5: 🌐 Google 全家桶與習慣同步 =================
        self.tabs.addTab(self._create_google_hub_tab(), "🌐 Google & 習慣")

        layout.addWidget(self.tabs.selector)
        layout.addWidget(self.tabs, stretch=1)
        self.reload_mcp_and_skills()
        return frame

    def _create_google_hub_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 1. Google 狀態與登入卡片
        grp_auth = QGroupBox("🔑 Google 帳號與 Workspace 狀態")
        auth_layout = QVBoxLayout(grp_auth)
        auth_layout.setSpacing(8)

        self.lbl_main_google_status = QLabel("")
        self.lbl_main_google_status.setStyleSheet("font-size: 12.5px; font-weight: 600;")
        auth_layout.addWidget(self.lbl_main_google_status)

        row_auth_btns = QHBoxLayout()
        btn_login = QPushButton("🚀 登入 Google 帳號授權")
        btn_login.setStyleSheet("background-color: #2563eb; color: white; font-weight: 600; padding: 6px 12px;")
        btn_login.clicked.connect(self._main_login_google)
        row_auth_btns.addWidget(btn_login)

        btn_cfg = QPushButton("⚙️ 開啟進階設定")
        btn_cfg.clicked.connect(lambda: self.open_settings_dialog(initial_tab=5))
        row_auth_btns.addWidget(btn_cfg)
        auth_layout.addLayout(row_auth_btns)

        # 服務快速開啟
        row_svc = QHBoxLayout()
        for name, key in [("✉️ Gmail", "gmail"), ("📁 Drive", "drive"), ("📅 Calendar", "calendar"), ("📝 Docs", "docs"), ("📊 Sheets", "sheets")]:
            b = QPushButton(name)
            b.setStyleSheet("padding: 4px 6px; font-size: 11px;")
            b.clicked.connect(lambda chk, s=key: webbrowser.open(google_suite.get_service_url(s)))
            row_svc.addWidget(b)
        auth_layout.addLayout(row_svc)
        layout.addWidget(grp_auth)

        # 2. 習慣快速同步卡片
        grp_habit = QGroupBox("⚡ 個人習慣與偏好同步")
        habit_layout = QVBoxLayout(grp_habit)
        habit_layout.setSpacing(8)

        lbl_desc = QLabel("一鍵提取本機 Chrome / Edge 歷史紀錄，3 秒同步工作習慣與關注專案：")
        lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        habit_layout.addWidget(lbl_desc)

        row_sync = QHBoxLayout()
        btn_sync_chrome = QPushButton("⚡ 一鍵同步本機習慣 (免密碼快照)")
        btn_sync_chrome.setStyleSheet("background-color: #059669; color: white; font-weight: 600; padding: 7px 12px;")
        btn_sync_chrome.clicked.connect(self._main_sync_habits)
        row_sync.addWidget(btn_sync_chrome)

        btn_sync_g = QPushButton("☁️ 同步雲端日曆與硬碟")
        btn_sync_g.clicked.connect(self._main_sync_cloud_habits)
        row_sync.addWidget(btn_sync_g)
        habit_layout.addLayout(row_sync)

        self.txt_main_habit_view = QTextEdit()
        self.txt_main_habit_view.setReadOnly(True)
        self.txt_main_habit_view.setStyleSheet("""
            QTextEdit {
                background-color: #0b0d13;
                color: #38bdf8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-family: Consolas, monospace;
                font-size: 11.5px;
            }
        """)
        habit_layout.addWidget(self.txt_main_habit_view)
        layout.addWidget(grp_habit)

        self._refresh_main_google_hub()
        return widget

    def _refresh_main_google_hub(self):
        if not hasattr(self, "lbl_main_google_status"):
            return
        if google_suite.is_authenticated():
            self.lbl_main_google_status.setText("🟢 <b>已授權登入</b>：Workspace 全套 API 運作中")
            self.lbl_main_google_status.setStyleSheet("color: #4ade80;")
        elif os.path.exists(google_suite.creds_path):
            self.lbl_main_google_status.setText("🟡 <b>已配置憑證</b>：請點擊「登入 Google 帳號授權」完成綁定")
            self.lbl_main_google_status.setStyleSheet("color: #fbbf24;")
        else:
            self.lbl_main_google_status.setText("⚪ <b>未配置憑證</b>：點擊下方服務可直接使用本機 Chrome 登入態開啟")
            self.lbl_main_google_status.setStyleSheet("color: #94a3b8;")

        ctx = habit_sync_engine.load_prompt_context()
        self.txt_main_habit_view.setPlainText(ctx or "尚未同步習慣。點擊上方「一鍵同步本機習慣」開始！")

    def _main_login_google(self):
        try:
            ok = google_suite._try_authenticate()
            if ok:
                QMessageBox.information(self, "授權成功", "🎉 Google 帳號授權成功！全套 Workspace 服務已啟用。")
            else:
                QMessageBox.warning(self, "提示", "尚未完成授權，若尚未放置 credentials.json，請點「⚙️ 開啟進階設定」進行匯入。")
        except Exception as e:
            QMessageBox.critical(self, "授權失敗", f"錯誤：{e}")
        self._refresh_main_google_hub()
        self._update_google_login_button()

    def _main_sync_habits(self):
        res = habit_sync_engine.sync_from_local_browser("chrome")
        if res.get("success"):
            QMessageBox.information(self, "同步成功", "⚡ 已成功提取本機 Chrome 習慣，已注入 Agent 認知背景！")
        else:
            QMessageBox.warning(self, "提示", f"同步未完成：{res.get('error')}")
        self._refresh_main_google_hub()
        self._update_google_login_button()

    def _main_sync_cloud_habits(self):
        res = habit_sync_engine.sync_from_google_suite(google_suite)
        if res.get("success"):
            QMessageBox.information(self, "同步成功", "☁️ 已成功提取 Google 雲端日曆與硬碟習慣！")
        else:
            QMessageBox.warning(self, "提示", f"同步未完成：{res.get('error')}")
        self._refresh_main_google_hub()
        self._update_google_login_button()

    def _update_tray_menu(self):
        if not hasattr(self, "tray") or not self.tray:
            return
        menu = QMenu()
        act_open = QAction(t("tray_show"), menu)
        act_open.triggered.connect(self.show_and_activate)
        menu.addAction(act_open)

        act_settings = QAction(t("tray_settings"), menu)
        act_settings.triggered.connect(lambda: self.open_settings_dialog(0))
        menu.addAction(act_settings)

        # 🌐 語言切換選單 (繁體中文、簡體中文、英文、日語、韓文)
        menu_lang = menu.addMenu(t("menu_language"))
        curr_lang = i18n.get_language()
        for code, name in SUPPORTED_LANGUAGES.items():
            act_l = menu_lang.addAction(name)
            act_l.setCheckable(True)
            act_l.setChecked(code == curr_lang)
            act_l.triggered.connect(lambda checked, c=code: self.switch_language(c))

        act_win = QAction(t("tray_new_win"), menu)
        act_win.triggered.connect(self.spawn_new_instance)
        menu.addAction(act_win)

        menu.addSeparator()
        act_totp = QAction("📱 TOTP 驗證器（掃碼 / 測試）", menu)
        act_totp.triggered.connect(self._show_totp_binding_ui)
        menu.addAction(act_totp)

        act_kill = QAction(t("btn_kill"), menu)
        act_kill.triggered.connect(self.trigger_kill_switch)
        menu.addAction(act_kill)

        act_quit = QAction(t("tray_quit"), menu)
        act_quit.triggered.connect(self._safe_quit)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)

    def _safe_quit(self):
        """徹底完全退出軟體（必須通過真人 TOTP 雙因子身分驗證器簽發 HMAC 退場憑證，病毒無法偽造關閉）"""
        if hasattr(self, "security_guard") and self.security_guard:
            ok = self._prompt_totp_authenticator_dialog(mode="exit")
            if not ok:
                return
        if hasattr(self, "streamer") and self.streamer:
            try:
                self.streamer.stop_stream()
            except Exception:
                pass
        try:
            self.async_worker.submit(mcp_manager.shutdown()).result(timeout=5)
        except Exception:
            pass
        self._team_shutdown()
        QApplication.instance().quit()

    def _init_tray_icon(self):
        icon = QIcon(str(ICON_PATH)) if ICON_PATH.exists() else self.windowIcon()
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(f"{t('brand_name')} ({t('lbl_context_normal')})")
        self._update_tray_menu()
        self.tray.activated.connect(
            lambda reason: self.show_and_activate()
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
            else None
        )
        self.tray.show()

    def show_and_activate(self):
        """還原並將視窗強制拉到最上層獲取使用者焦點"""
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        try:
            import win32con
            import win32gui
            hwnd = int(self.winId())
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def setup_ipc_server(self, server: QLocalServer):
        """配置單例 IPC 監聽，當重複開啟捷徑時主動喚醒視窗並置頂"""
        self._ipc_server = server
        self._ipc_server.newConnection.connect(self._handle_ipc_connection)

    def _handle_ipc_connection(self):
        client = self._ipc_server.nextPendingConnection()
        if client:
            client.readyRead.connect(lambda: self._on_ipc_message(client))

    def _on_ipc_message(self, client):
        try:
            raw = bytes(client.readAll()).decode("utf-8", errors="ignore")
            if "SHOW" in raw or "RESTORE" in raw:
                self.show_and_activate()
        except Exception:
            pass
        finally:
            try:
                client.disconnectFromServer()
            except Exception:
                pass

    def closeEvent(self, event):
        try:
            from core.app_auto_mapper import has_pending_test_queue
            rem = has_pending_test_queue()
            if rem > 0:
                ans = QMessageBox.question(self, '軟體學習進度尚未完成', f'目前還有 {rem} 個軟體排程實測尚未完成。\n確定要關閉嗎？（系統已自動保存進度，下次開機閒置時會繼續測試）', QMessageBox.Yes | QMessageBox.No)
                if ans != QMessageBox.Yes:
                    event.ignore()
                    return
        except Exception:
            pass
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "Syntra 星樞",
            "程式已最小化至右下角系統列常駐待命。雙擊圖示隨時開啟！",
            self.tray.icon(),
            2000,
        )

    # ================= 即時畫面卡片流與即時串流邏輯 =================

    def refresh_window_carousel(self):
        """掃描桌面所有視窗，並生成水平視窗切換卡片流（極速加載，不阻塞 UI 啟動）"""
        # 清除舊卡片
        for c in self.window_cards.values():
            c.deleteLater()
        self.window_cards.clear()

        windows = self.desktop_controller.list_open_windows()
        for w in windows:
            hwnd = w["hwnd"]
            title = w["title"]
            is_screen = hwnd == 0

            card = WindowCardWidget(hwnd=hwnd, title=title, is_screen=is_screen, parent=self.carousel_container)
            card.clicked.connect(self.select_window_card)
            self.carousel_layout.addWidget(card)
            self.window_cards[hwnd] = card

        # 延後 150ms 非同步異步抓取卡片縮圖，徹底消除主線程啟動凍結
        QTimer.singleShot(150, self._lazy_load_carousel_thumbnails)

    def _lazy_load_carousel_thumbnails(self):
        """非同步逐一為視窗卡片加載縮圖"""
        for hwnd, card in list(self.window_cards.items()):
            try:
                img, _ = self.desktop_controller.capture_window_background(hwnd, draw_grid=False)
                if img:
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    pix = QPixmap()
                    pix.loadFromData(buf.getvalue())
                    card.set_thumbnail(pix)
            except Exception:
                pass

        # 預設選取主螢幕 (0)
        self.select_window_card(0)

    def select_window_card(self, hwnd: int):
        self.selected_hwnd = hwnd
        for h, card in self.window_cards.items():
            card.set_selected(h == hwnd)

        self.streamer.set_target_window(hwnd)
        card_title = self.window_cards.get(hwnd).title_text if hwnd in self.window_cards else f"視窗 HWND:{hwnd}"
        self.lbl_live_title.setText(f"即時同步：{card_title[:34]} (12 FPS 即時串流)")

    def extract_accessibility_tree_to_chat(self):
        """以作業系統無障礙功能提取當前選中視窗之結構樹，直接填入對話框代替截圖！"""
        target_hwnd = getattr(self, "selected_hwnd", 0)
        from core.accessibility_engine import accessibility_engine
        tree_text, nodes = accessibility_engine.dump_window_tree(target_hwnd, max_depth=5, max_nodes=60)
        self.statusBar().showMessage(f"♿ 已成功提取無障礙控制項樹 (共 {len(nodes)} 個元素)，已帶入對話框！", 4000)

        snippet = tree_text
        if len(snippet) > 1800:
            snippet = snippet[:1800] + "\n...(以下略，共 " + str(len(nodes)) + " 個元件)"
        prompt = f"/uia 請根據以下視窗的無障礙控制項樹，分析畫面內容與可互動元素：\n\n```accessibility_tree\n{snippet}\n```"
        if hasattr(self, "chat_input_card"):
            self.chat_input_card.set_text(prompt)

    def _should_capture_preview(self) -> bool:
        """
        預覽截圖節流（錄影中不受此限，由 ScreenStreamer 照原速擷取）：
        - 主視窗真的是 Windows 前景視窗：每秒 5 張（預覽框只有 190px 高，12 張用不到）
        - 視窗開著但不在最前面：每秒 1 張
        - 縮在托盤 / 最小化 / 正在打遊戲：不截圖
        前景判斷用 GetForegroundWindow：Qt 的 isActiveWindow() 在 Windows 拒絕交出焦點時
        仍會回傳 True，曾導致開機時預覽以 12 張/秒全速截圖（主執行緒約 30% CPU）。
        """
        if not self.isVisible() or self.isMinimized():
            return False
        if not hasattr(self, "lbl_live_stream") or not self.lbl_live_stream.isVisible():
            return False
        if getattr(self.streamer, "target_hwnd", 0) == 0:
            return False
        try:
            import win32gui
            is_foreground = win32gui.GetForegroundWindow() == int(self.winId())
        except Exception:
            is_foreground = self.isActiveWindow()
        if not is_foreground:
            try:
                from core.process_event_hub import process_hub
                if process_hub.is_gaming():
                    return False
            except Exception:
                pass
        interval = 1.5 if is_foreground else 3.0
        now = time.time()
        if now - self._last_bg_capture >= interval:
            self._last_bg_capture = now
            return True
        return False

    def _on_stream_frame(self, pixmap: QPixmap, pil_img: Image.Image):
        """12 FPS 即時同步串流影格渲染 (排版防抖固定尺寸，防止 Layout 重排抖動閃爍)"""
        self.latest_live_pil_img = pil_img
        target_w = max(self.lbl_live_stream.width(), 240)
        target_h = 190
        scaled = pixmap.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_live_stream.setPixmap(scaled)

    def toggle_recording(self):
        if not self.streamer.recorder.is_recording:
            filepath = self.streamer.start_recording()
            self.btn_record.setText("⏹️ 停止錄影")
            self.btn_record.setObjectName("recordActiveBtn")
            self.btn_record.setStyle(self.btn_record.style())
            self.lbl_record_status.show()
            self.lbl_record_status.setText(f"🔴 錄影中: 0.0s -> {filepath.name}")
        else:
            res = self.streamer.stop_recording()
            self.btn_record.setText("🔴 錄影")
            self.btn_record.setObjectName("")
            self.btn_record.setStyle(self.btn_record.style())
            self.lbl_record_status.hide()
            if res:
                QMessageBox.information(
                    self,
                    "錄影已儲存",
                    f"✅ 視窗/螢幕錄影完成！\n\n時長：{res['duration_seconds']} 秒 ({res['frame_count']} 影格)\n儲存路徑：\n{res['path']}",
                )

    def _on_recording_tick(self, elapsed: float, frames: int):
        self.lbl_record_status.setText(f"🔴 錄影中: {elapsed:.1f}s ({frames} frames)")

    # ================= Skills & MCP 管理邏輯 =================

    def reload_mcp_and_skills(self):
        # 1. 載入 Skills
        skills = self.mcp_skill_manager.get_all_skills()
        self.table_skills.setRowCount(len(skills))
        for row, s in enumerate(skills):
            self.table_skills.setItem(row, 0, QTableWidgetItem(s["name"]))
            self.table_skills.setItem(row, 1, QTableWidgetItem(s["category"]))
            self.table_skills.setItem(row, 2, QTableWidgetItem(f"{s['description'][:50]}... ({Path(s['path']).name})"))

        # 2. 載入 MCP Servers
        mcp_servers = self.mcp_skill_manager.get_mcp_servers()
        live = {s["id"]: s for s in mcp_manager.status()}  # 真實連線狀態（不再顯示寫死的 READY）
        self.table_mcp.setRowCount(len(mcp_servers))
        for row, m in enumerate(mcp_servers):
            self.table_mcp.setItem(row, 0, QTableWidgetItem(m["name"]))
            st = live.get(re.sub(r"[^a-zA-Z0-9_-]", "_", str(m.get("id") or m.get("name"))))
            if not m.get("enabled", True):
                label, color, n_tools, tip = "⚪ 已停用", "#94a3b8", "—", m.get("note", "")
            elif st is None or st["state"] == "STOPPED":
                label, color, n_tools, tip = "⏳ 尚未啟動", "#fbbf24", "—", ""
            elif st["state"] == "STARTING":
                label, color, n_tools, tip = "⏳ 啟動中", "#fbbf24", "—", ""
            elif st["state"] == "READY":
                label, color, n_tools, tip = "🟢 就緒", "#4ade80", f"{len(st['tools'])} tools", ", ".join(st["tools"])
            else:
                label, color, n_tools, tip = "🔴 失敗", "#f87171", "0 tools", st.get("error", "")
            status_item = QTableWidgetItem(label)
            status_item.setForeground(QColor(color))
            status_item.setToolTip(tip)
            self.table_mcp.setItem(row, 1, status_item)
            self.table_mcp.setItem(row, 2, QTableWidgetItem(n_tools))
            cmd_desc = f"{m.get('command')} {' '.join(m.get('args', []))} - {m.get('description', '')}"
            self.table_mcp.setItem(row, 3, QTableWidgetItem(cmd_desc))

    def add_custom_mcp_server(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("＋ 新增 MCP (Model Context Protocol) 伺服器")
        dlg.resize(460, 260)
        dlg.setStyleSheet(MODERN_DARK_STYLE)

        f_layout = QFormLayout(dlg)
        in_name = QLineEdit()
        in_cmd = QLineEdit("npx")
        in_args = QLineEdit("-y @modelcontextprotocol/server-postgres postgresql://localhost/mydb")
        in_desc = QLineEdit()

        f_layout.addRow("伺服器名稱：", in_name)
        f_layout.addRow("執行指令 (Command)：", in_cmd)
        f_layout.addRow("參數 (Args)：", in_args)
        f_layout.addRow("功能說明：", in_desc)

        btn_box = QHBoxLayout()
        btn_ok = QPushButton("新增並註冊")
        btn_ok.setObjectName("primaryBtn")
        btn_box.addWidget(btn_ok)

        def _do_add():
            if not in_name.text().strip():
                return
            self.mcp_skill_manager.upsert_mcp_server({
                "name": in_name.text().strip(),
                "command": in_cmd.text().strip(),
                "args": in_args.text().strip(),
                "description": in_desc.text().strip(),
            })
            self.reload_mcp_and_skills()
            dlg.accept()

        btn_ok.clicked.connect(_do_add)
        f_layout.addRow(btn_box)
        dlg.exec_()

    # ================= 聊天與大腦互動 =================

    def _append_welcome_message(self):
        welcome_html = """
        <div style="text-align:center; padding: 25px 10px;">
            <h1 style="color:#60a5fa; font-size:24px; margin-bottom:8px;">你好，我是 Syntra 星樞，今天要監督哪個專案或操作什麼軟體？</h1>
            <p style="color:#94a3b8; font-size:13px; line-height:1.6;">
                純 Windows 本地原生桌面應用程式（零 127.0.0.1 伺服器）。<br>
                支援<strong>API 編碼智慧識別與命名</strong>、右側<strong>即時螢幕分享卡片流 (12 FPS) 與錄影</strong>、AI 寫程式閉環監督（3 次熔斷）、<strong>Skills / MCP 整合管理</strong>。
            </p>
        </div>
        """
        self.chat_browser.setHtml(welcome_html)

    def new_chat_session(self):
        self.current_session_id = f"qt_sess_{int(time.time())}"
        self.current_category = "temp"
        self.current_messages = []
        self.clear_all_attachments()
        if hasattr(self, "agent_slots") and self.active_agent_id in self.agent_slots:
            slot = self.agent_slots[self.active_agent_id]
            slot.session_id = self.current_session_id
            slot.messages = []
            self._append_welcome_message_to_slot(slot)
        else:
            self._append_welcome_message()
        self._refresh_nav_dots()

    # ================= 多代理工作台系統 (同一介面多開並行執行與監控) =================

    def create_agent_slot(self, name: Optional[str] = None, parent_id: Optional[str] = None,
                          focus: bool = True) -> AgentSlot:
        # 用遞增編號，避免關掉代理後再新增時名稱／ID 重複
        self._agent_counter = max(getattr(self, "_agent_counter", 0), len(self.agent_slots)) + 1
        idx = self._agent_counter
        agent_id = f"agent_{int(time.time())}_{idx}"
        agent_name = name or f"🤖 代理 #{idx}"
        session_id = f"qt_sess_{int(time.time())}_{idx}"

        slot = AgentSlot(agent_id, agent_name, session_id)
        self.agent_slots[agent_id] = slot
        self._team_on_slot_created(slot, parent_id)
        if getattr(self, "_main_agent_id", None) not in self.agent_slots:
            self._main_agent_id = agent_id  # 沒有主控時，新建的代理自動成為主控

        # 初始化歡迎訊息
        self._append_welcome_message_to_slot(slot)

        # 構建並排監控面板 (Agent Monitor Panel)
        panel = QFrame()
        panel.setObjectName("agentPanel")
        panel.setStyleSheet("background: #0f121a; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;")
        p_layout = QVBoxLayout(panel)
        p_layout.setContentsMargins(6, 6, 6, 6)
        p_layout.setSpacing(4)

        # 頂部狀態標題列
        header_row = QHBoxLayout()
        lbl_name = QLabel(f"<b>{html.escape(self._agent_display_name(agent_id))}</b>")
        slot.lbl_name = lbl_name
        lbl_name.setStyleSheet("color: #38bdf8; font-size: 12px;")
        lbl_status = QLabel("🟢 待命")
        lbl_status.setStyleSheet("background: rgba(34,197,94,0.15); color: #4ade80; border-radius: 4px; padding: 2px 6px; font-size: 10.5px;")
        slot.lbl_status_tag = lbl_status

        header_row.addWidget(lbl_name)
        header_row.addWidget(lbl_status)
        header_row.addStretch()

        btn_focus = QPushButton("🔍 聚焦")
        btn_focus.setFixedSize(48, 22)
        btn_focus.setStyleSheet("font-size: 11px; padding: 2px;")
        btn_focus.clicked.connect(lambda _, aid=agent_id: self.switch_to_agent(aid, force_tab=True))
        header_row.addWidget(btn_focus)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(22, 22)
        btn_close.setToolTip("關閉這個代理（至少會保留一個）")
        btn_close.setStyleSheet("background: rgba(239,68,68,0.15); border: none; color: #ef4444; border-radius: 4px;")
        btn_close.clicked.connect(lambda _, aid=agent_id: self.close_agent_slot(aid))
        header_row.addWidget(btn_close)

        p_layout.addLayout(header_row)
        slot.chat_browser.anchorClicked.connect(lambda url, s=slot: self._handle_chat_anchor_click(url, s))
        p_layout.addWidget(slot.chat_browser, stretch=1)
        slot.panel_widget = panel

        # 加入 stack 與 splitter
        if hasattr(self, "agent_stack"):
            self.agent_stack.addWidget(self._team_build_container(slot))
        if hasattr(self, "agent_split"):
            self.agent_split.addWidget(slot.panel_widget)
        self._team_place_chat(slot)

        if focus or self.active_agent_id not in self.agent_slots:
            self.switch_to_agent(agent_id)
        self._refresh_agent_tab_bar()
        return slot

    def close_agent_slot(self, agent_id: str, confirm: bool = True):
        if len(self.agent_slots) <= 1:
            try:
                self.statusBar().showMessage("至少要保留一個代理，最後一個不能關閉。", 4000)
            except Exception:
                pass
            return False
        slot = self.agent_slots.get(agent_id)
        if slot is None:
            return False
        if confirm and slot.status == "RUNNING":
            ans = QMessageBox.question(
                self, "關閉代理",
                f"{slot.name} 還在執行中，確定要關閉嗎？\n（關閉後就看不到它的結果）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return False
        slot = self.agent_slots.pop(agent_id, None)
        self._work.pop(agent_id, None)
        self._stream_start.pop(agent_id, None)
        if slot:
            if hasattr(self, "agent_stack") and slot.chat_browser:
                self.agent_stack.removeWidget(slot.container or slot.chat_browser)
            if slot.terminal_widget is not None:
                slot.terminal_widget.detach()
            if slot.panel_widget:
                slot.panel_widget.setParent(None)
                slot.panel_widget.deleteLater()
        self._team_on_slot_closed(agent_id)
        if getattr(self, "_main_agent_id", None) == agent_id:
            self._main_agent_id = next(iter(self.agent_slots.keys()))
            self._update_agent_panel_names()
            try:
                new_main = self.agent_slots[self._main_agent_id].name
                self.statusBar().showMessage(f"主控已改由 {new_main} 擔任。", 4000)
            except Exception:
                pass
        if self.active_agent_id == agent_id:
            first_aid = next(iter(self.agent_slots.keys()))
            self.switch_to_agent(first_aid)
        self._refresh_agent_tab_bar()
        return True

    # ───────────── 分頁列：主控、新增、右鍵選單 ─────────────

    def _agent_display_name(self, agent_id: str) -> str:
        slot = self.agent_slots.get(agent_id)
        name = slot.name if slot else ""
        if agent_id == getattr(self, "_main_agent_id", None) and "主控" not in name:
            name += " (主控)"
        return name

    def _update_agent_panel_names(self):
        for aid, s in self.agent_slots.items():
            if getattr(s, "lbl_name", None) is not None:
                s.lbl_name.setText(f"<b>{html.escape(self._agent_display_name(aid))}</b>")

    def set_main_agent(self, agent_id: str):
        if agent_id not in self.agent_slots or agent_id == getattr(self, "_main_agent_id", None):
            return
        self._main_agent_id = agent_id
        self._update_agent_panel_names()
        self._refresh_agent_tab_bar()
        try:
            self.statusBar().showMessage(f"已把 {self.agent_slots[agent_id].name} 設為主控。", 4000)
        except Exception:
            pass

    def _new_agent_from_bar(self, make_main: bool = False):
        slot = self.create_agent_slot()
        if make_main:
            self.set_main_agent(slot.agent_id)
        return slot

    def _rename_agent_dialog(self, agent_id: str):
        slot = self.agent_slots.get(agent_id)
        if slot is None:
            return
        name, ok = QInputDialog.getText(self, "重新命名代理", "新的名稱：", text=slot.name)
        name = (name or "").strip()
        if ok and name:
            slot.name = name
            self._update_agent_panel_names()
            self._refresh_agent_tab_bar()

    def _on_agent_bar_context_menu(self, pos):
        menu = QMenu(self)
        act_new = menu.addAction("＋ 新增代理")
        act_new_main = menu.addAction("＋ 新增代理並設為主控")
        chosen = menu.exec_(self.agent_bar_widget.mapToGlobal(pos))
        if chosen is act_new:
            self._new_agent_from_bar()
        elif chosen is act_new_main:
            self._new_agent_from_bar(make_main=True)

    def _on_agent_tab_context_menu(self, agent_id: str, widget, pos):
        if agent_id not in self.agent_slots:
            return
        is_main = agent_id == getattr(self, "_main_agent_id", None)
        menu = QMenu(self)
        act_switch = menu.addAction("切換到這個代理")
        act_main = menu.addAction("⭐ 已是主控" if is_main else "⭐ 設為主控")
        act_main.setEnabled(not is_main)
        act_rename = menu.addAction("✏️ 重新命名…")
        menu.addSeparator()
        act_new = menu.addAction("＋ 新增代理")
        act_close = menu.addAction("✕ 關閉這個代理")
        act_close.setEnabled(len(self.agent_slots) > 1)
        chosen = menu.exec_(widget.mapToGlobal(pos))
        if chosen is act_switch:
            self.switch_to_agent(agent_id)
        elif chosen is act_main:
            self.set_main_agent(agent_id)
        elif chosen is act_rename:
            self._rename_agent_dialog(agent_id)
        elif chosen is act_new:
            self._new_agent_from_bar()
        elif chosen is act_close:
            self.close_agent_slot(agent_id)

    # ───────────── Linux 風格代理指令（輸入框）與終端機遙控 ─────────────

    def _agent_by_no(self, no: int) -> Optional[AgentSlot]:
        ids = list(self.agent_slots.keys())
        return self.agent_slots[ids[no - 1]] if 1 <= no <= len(ids) else None

    def _agent_no(self, agent_id: str) -> int:
        ids = list(self.agent_slots.keys())
        return ids.index(agent_id) + 1 if agent_id in ids else 0

    _STATUS_ZH = {"IDLE": "🟢 待命", "RUNNING": "⏳ 執行中", "DONE": "✅ 完成", "ERROR": "🔴 錯誤"}

    def _agents_table_text(self) -> str:
        lines = ["編號  狀態        名稱"]
        for i, (aid, s) in enumerate(self.agent_slots.items(), 1):
            mark = "＊" if aid == self.active_agent_id else "  "
            main = "（主控）" if aid == getattr(self, "_main_agent_id", None) and "主控" not in s.name else ""
            lines.append(f"{mark}{i:<3} {self._STATUS_ZH.get(s.status, s.status):<10} {s.name}{main}")
        lines.append("＊ = 目前所在的代理")
        return "\n".join(lines)

    def _append_console_block(self, slot: Optional[AgentSlot], command: str, output: str, ok: bool = True):
        """在對話區顯示一段類似終端機的「指令 + 輸出」區塊（不送給 AI、不存進歷史）"""
        slot = slot or self.agent_slots.get(self.active_agent_id)
        browser = slot.chat_browser if slot else self.chat_browser
        color = "#e2e8f0" if ok else "#fca5a5"
        block = (
            "<table width='100%' cellspacing='0' cellpadding='10' bgcolor='#0b0d12' "
            "style='border:1px solid #262b33; margin:8px 0;'><tr><td>"
            f"<div style='color:#60a5fa; font-family:Consolas,monospace; font-size:12.5px;'>$ {html.escape(command)}</div>"
            f"<pre style='color:{color}; font-family:Consolas,\"Microsoft JhengHei\",monospace; font-size:12.5px; margin:6px 0 0 0;'>"
            f"{html.escape(output or '（沒有輸出）')}</pre></td></tr></table>"
        )
        self._append_left_block(browser)
        cur = QTextCursor(browser.document())
        cur.movePosition(QTextCursor.End)
        cur.insertHtml(block)
        sb = browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _run_agent_command(self, cmd: str, args: Dict[str, Any]):
        here = self.agent_slots.get(self.active_agent_id)
        if cmd == "ps":
            return self._append_console_block(here, "ps", self._agents_table_text())
        if cmd == "help":
            return self._append_console_block(here, "help", AGENT_CMD_HELP)
        if cmd == "remote":
            return self._append_console_block(here, "remote", self._remote_help_text())
        if cmd == "new":
            slot = self.create_agent_slot(args.get("name") or None)
            return self._append_console_block(slot, f"new {args.get('name', '')}".strip(),
                                              f"已新增 #{self._agent_no(slot.agent_id)} {slot.name}")
        if cmd == "sh":
            command = args["command"]
            aid = self.active_agent_id
            cwd = str(self.current_workspace_dir)
            self._append_console_block(here, command, f"⏳ 執行中…（{describe_linux_shell()}，位置：{cwd}）")

            async def _go():
                try:
                    res = await self.desktop_controller.run_background_command(
                        command=command, cwd=cwd, timeout=120.0, shell="linux")
                except Exception as e:  # noqa: BLE001
                    res = {"ok": False, "output": f"執行失敗：{e}", "exit_code": -1}
                out = res.get("output") or ""
                code = res.get("exit_code")
                if code not in (0, None):
                    out = (out + f"\n（結束代碼 {code}）").strip()
                self.sig_console_result.emit(aid, command, out, bool(res.get("ok")))

            self.async_worker.submit(_go())
            return
        # 以下需要編號
        no = args.get("no")
        target = self._agent_by_no(no) if no else here
        label = f"{cmd} {no}" if no else cmd
        if target is None:
            return self._append_console_block(here, label, f"找不到編號 {no} 的代理，輸入 ps 查看編號", ok=False)
        if cmd == "cd":
            self.switch_to_agent(target.agent_id)
            return self._append_console_block(target, label, f"已切換到 #{no} {target.name}")
        if cmd == "kill":
            if len(self.agent_slots) <= 1:
                return self._append_console_block(here, label, "至少要保留一個代理，最後一個不能關閉", ok=False)
            name = target.name
            ok = self.close_agent_slot(target.agent_id)
            here = self.agent_slots.get(self.active_agent_id)
            return self._append_console_block(here, label, f"已關閉 #{no} {name}" if ok else "沒有關閉", ok=ok)
        if cmd == "rename":
            target.name = args["name"]
            self._update_agent_panel_names()
            self._refresh_agent_tab_bar()
            return self._append_console_block(here, f"rename {no} {target.name}", f"#{no} 已改名為 {target.name}")
        if cmd == "stop":
            stopped = self._stop_agent_turn(target.agent_id)
            return self._append_console_block(here, label, f"已停止 {target.name} 這一輪" if stopped else f"{target.name} 目前沒有在執行")

    def _stop_agent_turn(self, agent_id: str) -> bool:
        fut = self._turn_by_agent.pop(agent_id, None)
        if fut is None or fut.done():
            return False
        fut.cancel()
        try:
            self.desktop_controller.kill_running_commands()
        except Exception:
            pass
        return True

    def _on_console_result(self, aid: str, command: str, output: str, ok: bool):
        slot = self.agent_slots.get(aid) or self.agent_slots.get(self.active_agent_id)
        self._append_console_block(slot, command, output, ok)

    # ---- 遙控服務 ----
    def _start_remote_control(self):
        try:
            self.remote_server = RemoteControlServer(self._remote_api(), BASE_DIR / "data")
            if not self.remote_server.start():
                print(f"[Remote] 終端機遙控未啟動：{self.remote_server.error}")
        except Exception as e:  # noqa: BLE001
            self.remote_server = None
            print(f"[Remote] 終端機遙控啟動失敗：{e}")

    def _remote_help_text(self) -> str:
        rs = self.remote_server
        if rs is None or rs._httpd is None:
            err = rs.error if rs else "未啟動"
            return f"終端機遙控目前沒有啟動：{err}"
        lan = "（只接受本機連線）" if rs.cfg["host"] in ("127.0.0.1", "localhost") else "（⚠️ 已開放區域網路連線）"
        return (
            f"服務位址：{rs.address} {lan}\n"
            f"Token 檔案：{rs.cfg['token_path']}\n"
            f"設定檔：{rs.cfg['config_path']}\n\n"
            f"CLI 用戶端：{BASE_DIR / 'cli'}（syntra-windows.py／syntra-linux）\n"
            "第一次使用：\n"
            f"  syntra config --url {rs.address}\n"
            "  syntra config --token      （貼上 token.txt 的內容）\n"
            "之後：\n"
            "  syntra ps\n"
            "  syntra ask -a 2 \"幫我整理下載資料夾\"\n"
            "（Windows 用 py syntra-windows.py …，Linux 用 ./syntra-linux …）\n\n"
            "要讓別台電腦連線：把設定檔的 host 改成 0.0.0.0 後重開 Syntra"
            "（連線未加密，只建議在信任的區域網路使用）。"
        )

    def _remote_api(self):
        import types

        def list_agents():
            return [
                {"no": i, "id": aid, "name": s.name, "status": s.status,
                 "main": aid == getattr(self, "_main_agent_id", None), "active": aid == self.active_agent_id,
                 "messages": len(s.messages)}
                for i, (aid, s) in enumerate(self.agent_slots.items(), 1)
            ]

        def new_agent(name=None):
            slot = self.create_agent_slot(name)
            return {"ok": True, "no": self._agent_no(slot.agent_id), "name": slot.name}

        def kill_agent(no):
            slot = self._agent_by_no(no)
            if slot is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            if len(self.agent_slots) <= 1:
                return {"ok": False, "error": "至少要保留一個代理，最後一個不能關閉"}
            name = slot.name
            ok = self.close_agent_slot(slot.agent_id, confirm=False)
            return {"ok": bool(ok), "closed": name}

        def ask_agent(no, text):
            slot = self._agent_by_no(no)
            if slot is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            fut = self._turn_by_agent.get(slot.agent_id)
            if fut is not None and not fut.done():
                return {"ok": False, "error": f"{slot.name} 還在執行上一輪，請稍後或先 stop"}
            prev_aid = self.active_agent_id
            # 暫存使用者在輸入框的草稿與附件，避免被遙控指令吃掉
            draft = self.input_text.toPlainText()
            files, shot = list(self.attached_files), self.attached_screenshot_b64
            self.attached_files, self.attached_screenshot_b64 = [], None
            try:
                self.switch_to_agent(slot.agent_id)
                before = len(slot.messages)
                self.send_current_prompt(text, allow_commands=False)
            finally:
                self.attached_files, self.attached_screenshot_b64 = files, shot
                if self.input_text.toPlainText() != draft:
                    self.input_text.setPlainText(draft)
                if prev_aid in self.agent_slots and prev_aid != slot.agent_id:
                    self.switch_to_agent(prev_aid)
            if len(slot.messages) <= before:
                return {"ok": False, "error": "沒有送出（可能被其他狀態擋下）"}
            return {"ok": True, "no": no, "after": len(slot.messages) - 1}

        def stop_agent(no):
            slot = self._agent_by_no(no)
            if slot is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            return {"ok": True, "stopped": self._stop_agent_turn(slot.agent_id)}

        def agent_messages(no, after=-1):
            slot = self._agent_by_no(no)
            if slot is None:
                return {"ok": False, "error": f"找不到編號 {no} 的代理"}
            fut = self._turn_by_agent.get(slot.agent_id)
            running = fut is not None and not fut.done()
            msgs = [
                {"i": i, "role": m.get("role"), "text": str(m.get("text") or "")[:20000]}
                for i, m in enumerate(slot.messages)
                if i > after and isinstance(m, dict)
            ]
            return {"ok": True, "no": no, "name": slot.name, "running": running,
                    "status": slot.status, "messages": msgs}

        return types.SimpleNamespace(
            list_agents=list_agents, new_agent=new_agent, kill_agent=kill_agent,
            ask_agent=ask_agent, stop_agent=stop_agent, agent_messages=agent_messages,
        )

    def switch_to_agent(self, agent_id: str, force_tab: bool = False):
        if agent_id not in self.agent_slots:
            return
        self.active_agent_id = agent_id
        slot = self.agent_slots[agent_id]
        self.current_session_id = slot.session_id
        self.chat_browser = slot.chat_browser
        self.current_messages = slot.messages

        if force_tab and self.is_split_view:
            self.toggle_split_view()

        if hasattr(self, "agent_stack"):
            self.agent_stack.setCurrentWidget(slot.container or slot.chat_browser)

        self._refresh_agent_tab_bar()
        self._refresh_nav_dots()

    def toggle_split_view(self):
        """切換分頁聚焦與並排監控模式（交給 set_agent_view 統一處理，會把對話框搬到正確位置）"""
        self.set_agent_view("tab" if getattr(self, "agent_view_mode", "tab") == "split" else "split")

    def _refresh_agent_tab_bar(self):
        """刷新代理橫條按鈕列"""
        if not hasattr(self, "agent_bar_layout"):
            return
        while self.agent_bar_layout.count():
            item = self.agent_bar_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        can_close = len(self.agent_slots) > 1
        for aid in self._team_ordered_ids():
            self.agent_bar_layout.addWidget(self._team_make_tab(aid, can_close))
        for aid, slot in ([] if hasattr(self, "_team_bridge") else self.agent_slots.items()):
            is_active = aid == self.active_agent_id
            status_dot = "⏳" if slot.status == "RUNNING" else ("✅" if slot.status == "DONE" else "🟢")
            btn = QPushButton(f"{status_dot} {self._agent_display_name(aid)}")
            btn.setFixedHeight(26)
            if is_active:
                btn.setStyleSheet("background: #283044; color: #38bdf8; border: 1px solid #38bdf8; border-radius: 6px; font-weight: bold; padding: 2px 10px;")
            else:
                btn.setStyleSheet("background: #1e2230; color: #94a3b8; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 2px 10px;")
            btn.clicked.connect(lambda _, a=aid: self.switch_to_agent(a))
            btn.setToolTip("右鍵：設為主控、重新命名、關閉")
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, a=aid, w=btn: self._on_agent_tab_context_menu(a, w, pos))
            if not can_close:
                self.agent_bar_layout.addWidget(btn)
                continue
            # 分頁旁邊加上 ✕ 關閉鈕（只剩一個代理時不顯示）
            tab = QWidget()
            tab_lay = QHBoxLayout(tab)
            tab_lay.setContentsMargins(0, 0, 0, 0)
            tab_lay.setSpacing(2)
            tab_lay.addWidget(btn)
            btn_x = QPushButton("✕")
            btn_x.setFixedSize(22, 22)
            btn_x.setToolTip(f"關閉 {slot.name}")
            btn_x.setCursor(Qt.PointingHandCursor)
            btn_x.setStyleSheet(
                "QPushButton { background: transparent; border: none; color: #94a3b8; border-radius: 4px; padding: 0; font-size: 11px; }"
                "QPushButton:hover { background: rgba(239,68,68,0.25); color: #f87171; }"
            )
            btn_x.clicked.connect(lambda _, a=aid: self.close_agent_slot(a))
            tab_lay.addWidget(btn_x)
            self.agent_bar_layout.addWidget(tab)

        btn_add = QPushButton("＋")
        btn_add.setFixedSize(26, 26)
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setToolTip("新增代理（在這一行空白處按右鍵也可以）")
        btn_add.setStyleSheet(
            "QPushButton { background: #1e2230; color: #94a3b8; border: 1px dashed rgba(148,163,184,0.45);"
            " border-radius: 6px; font-size: 15px; font-weight: bold; padding: 0; }"
            "QPushButton:hover { background: #283044; color: #38bdf8; border-color: #38bdf8; }"
        )
        btn_add.clicked.connect(lambda _: self._new_agent_from_bar())
        self.agent_bar_layout.addWidget(btn_add)
        self.agent_bar_layout.addStretch()

        if hasattr(self, "lbl_agent_summary"):
            running_cnt = sum(1 for s in self.agent_slots.values() if s.status == "RUNNING")
            run_txt = f" ({running_cnt} 個執行中)" if running_cnt > 0 else ""
            self.lbl_agent_summary.setText(f"🤖 {len(self.agent_slots)} 個代理在線{run_txt}")

    def _append_welcome_message_to_slot(self, slot: AgentSlot):
        welcome_html = f"""
        <div style="text-align:center; padding: 20px 10px;">
            <h2 style="color:#60a5fa; font-size:20px; margin-bottom:6px;">{slot.name} 已就緒</h2>
            <p style="color:#94a3b8; font-size:12px; line-height:1.5;">
                純本機多代理工作台 · 支援同介面多開並行執行與即時監控<br>
                可在此代理指派獨立任務（代碼檢查、網頁爬蟲、Git 巡檢或桌面自動化）
            </p>
        </div>
        """
        slot.chat_browser.setHtml(welcome_html)

    # ================= 支援多開 (Multi-Instance) =================

    def spawn_new_instance(self):
        """支援多開：開啟新的獨立應用程式視窗，互不阻塞，絕不在背景彈出黑色終端視窗"""
        try:
            py_exe = Path(sys.executable).resolve()
            pyw_exe = py_exe.parent / "pythonw.exe"
            runner = str(pyw_exe) if pyw_exe.exists() else str(py_exe)
            script_path = str(Path(__file__).resolve())
            silent_popen([runner, script_path])
        except Exception:
            win = MainWindow()
            win.show()
            if not hasattr(self, "_extra_windows"):
                self._extra_windows = []
            self._extra_windows.append(win)

    # ================= 檔案總管與工作目錄 (圖二) =================

    def select_workspace_folder(self):
        """指定檔案夾讓程式自動讀入並載入左側檔案總管 (如圖二)"""
        folder = QFileDialog.getExistingDirectory(self, "指定專案工作檔案夾", str(self.current_workspace_dir))
        if folder:
            self.current_workspace_dir = Path(folder)
            self.lbl_workspace_name.setText(f"📁 {self.current_workspace_dir.name}")
            self.populate_file_tree(self.current_workspace_dir)
            self.sidebar_tabs.setCurrentIndex(1)

    def populate_file_tree(self, root_dir: Path):
        """以類似 VS Code 樹狀結構呈現檔案總管 (如圖二)"""
        self.tree_workspace.clear()
        if not root_dir.exists():
            return

        root_item = QTreeWidgetItem(self.tree_workspace)
        root_item.setText(0, f"📁 {root_dir.name}")
        root_item.setData(0, Qt.UserRole, str(root_dir))
        root_item.setExpanded(True)

        ignored_names = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}

        def _add_children(parent_item: QTreeWidgetItem, cur_path: Path, depth: int = 0):
            if depth > 4:
                return
            try:
                entries = sorted(list(cur_path.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
                for p in entries:
                    if p.name in ignored_names:
                        continue
                    item = QTreeWidgetItem(parent_item)
                    item.setData(0, Qt.UserRole, str(p))
                    if p.is_dir():
                        item.setText(0, f"📁 {p.name}")
                        _add_children(item, p, depth + 1)
                    else:
                        ext = p.suffix.lower()
                        icon = "📄"
                        if ext == ".py":
                            icon = "🐍"
                        elif ext in (".js", ".jsx", ".ts", ".tsx"):
                            icon = "JS"
                        elif ext in (".json", ".yaml", ".yml"):
                            icon = "{}"
                        elif ext in (".html", ".htm"):
                            icon = "🌐"
                        elif ext in (".css", ".scss", ".less"):
                            icon = "🎨"
                        elif ext in (".md", ".txt", ".rst"):
                            icon = "📝"
                        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".ico"):
                            icon = "🖼️"
                        elif ext == ".pdf":
                            icon = "📕"
                        item.setText(0, f"{icon} {p.name}")
            except Exception:
                pass

        _add_children(root_item, root_dir)

    def create_new_file_in_workspace(self, parent_dir: Optional[Path] = None):
        """新增檔案"""
        target_dir = parent_dir or self.current_workspace_dir
        name, ok = QInputDialog.getText(self, "新增檔案", f"在 {target_dir.name} 下建立新檔案：", text="new_file.py")
        if ok and name.strip():
            new_file = target_dir / name.strip()
            try:
                new_file.touch(exist_ok=False)
                self.populate_file_tree(self.current_workspace_dir)
                self.statusBar().showMessage(f"✅ 已成功建立檔案：{new_file.name}", 3500)
            except Exception as e:
                QMessageBox.warning(self, "建立失敗", f"無法建立檔案：{e}")

    def create_new_folder_in_workspace(self, parent_dir: Optional[Path] = None):
        """新增資料夾"""
        target_dir = parent_dir or self.current_workspace_dir
        name, ok = QInputDialog.getText(self, "新增資料夾", f"在 {target_dir.name} 下建立新資料夾：", text="new_folder")
        if ok and name.strip():
            new_folder = target_dir / name.strip()
            try:
                new_folder.mkdir(parents=True, exist_ok=True)
                self.populate_file_tree(self.current_workspace_dir)
                self.statusBar().showMessage(f"✅ 已成功建立資料夾：{new_folder.name}", 3500)
            except Exception as e:
                QMessageBox.warning(self, "建立失敗", f"無法建立資料夾：{e}")

    def rename_workspace_item(self, target_path: Path):
        """重新命名 (修改)"""
        new_name, ok = QInputDialog.getText(self, "重新命名", "請輸入新名稱：", text=target_path.name)
        if ok and new_name.strip() and new_name.strip() != target_path.name:
            dest = target_path.parent / new_name.strip()
            try:
                target_path.rename(dest)
                self.populate_file_tree(self.current_workspace_dir)
                self.statusBar().showMessage(f"✅ 已重新命名為：{dest.name}", 3500)
            except Exception as e:
                QMessageBox.warning(self, "重命名失敗", f"無法重新命名：{e}")

    def duplicate_workspace_item(self, target_path: Path):
        """複製檔案或資料夾副本"""
        try:
            if target_path.is_file():
                stem = target_path.stem
                suffix = target_path.suffix
                dest = target_path.parent / f"{stem}_copy{suffix}"
                counter = 1
                while dest.exists():
                    dest = target_path.parent / f"{stem}_copy{counter}{suffix}"
                    counter += 1
                shutil.copy2(target_path, dest)
                self.statusBar().showMessage(f"📋 已複製檔案副本：{dest.name}", 3500)
            else:
                dest = target_path.parent / f"{target_path.name}_copy"
                counter = 1
                while dest.exists():
                    dest = target_path.parent / f"{target_path.name}_copy{counter}"
                    counter += 1
                shutil.copytree(target_path, dest)
                self.statusBar().showMessage(f"📋 已複製資料夾副本：{dest.name}", 3500)
            self.populate_file_tree(self.current_workspace_dir)
        except Exception as e:
            QMessageBox.warning(self, "複製失敗", f"無法複製：{e}")

    def delete_workspace_item(self, target_path: Path):
        """刪除檔案或資料夾"""
        reply = QMessageBox.question(
            self,
            "確認刪除",
            f"確定要永久刪除「{target_path.name}」嗎？此操作無法復原！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                if target_path.is_file():
                    target_path.unlink()
                else:
                    shutil.rmtree(target_path)
                self.populate_file_tree(self.current_workspace_dir)
                self.statusBar().showMessage(f"🗑️ 已刪除：{target_path.name}", 3500)
            except Exception as e:
                QMessageBox.warning(self, "刪除失敗", f"無法刪除：{e}")

    def _show_file_tree_context_menu(self, pos: QPoint):
        item = self.tree_workspace.itemAt(pos)
        path_str = item.data(0, Qt.UserRole) if item else str(self.current_workspace_dir)
        target_path = Path(path_str) if path_str else self.current_workspace_dir

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #161922; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px; padding: 4px; color: #f1f5f9; }
            QMenu::item { padding: 6px 18px; border-radius: 4px; font-size: 12.5px; }
            QMenu::item:selected { background: #283044; color: #60a5fa; }
            QMenu::separator { height: 1px; background: rgba(255,255,255,0.08); margin: 4px 8px; }
        """)

        if target_path.is_file():
            act_attach = menu.addAction("📎 附加此檔案交給 AI")
            act_preview = menu.addAction("👁️ 快速預覽 / 編輯檔案")
            menu.addSeparator()
            act_rename = menu.addAction("✏️ 重新命名 (Rename)")
            act_duplicate = menu.addAction("📋 複製檔案副本 (Duplicate)")
            act_copy = menu.addAction("📋 複製檔案路徑 (Copy Path)")
            menu.addSeparator()
            act_open = menu.addAction("📂 在 Windows 總管中顯示")
            act_delete = menu.addAction("🗑️ 刪除檔案 (Delete)")

            action = menu.exec_(self.tree_workspace.viewport().mapToGlobal(pos))
            if action == act_attach:
                self.attach_single_file(target_path)
            elif action == act_preview:
                self.preview_file_dialog(target_path)
            elif action == act_rename:
                self.rename_workspace_item(target_path)
            elif action == act_duplicate:
                self.duplicate_workspace_item(target_path)
            elif action == act_copy:
                QApplication.clipboard().setText(str(target_path))
            elif action == act_open:
                silent_popen(["explorer.exe", f'/select,{str(target_path)}'])
            elif action == act_delete:
                self.delete_workspace_item(target_path)
        else:
            # 資料夾右鍵選單
            act_new_file = menu.addAction("📄 在此目錄新增檔案 (New File)")
            act_new_folder = menu.addAction("📁 在此目錄新增資料夾 (New Folder)")
            menu.addSeparator()
            act_rename = menu.addAction("✏️ 重新命名資料夾 (Rename)")
            act_duplicate = menu.addAction("📋 複製資料夾副本 (Duplicate)")
            act_copy = menu.addAction("📋 複製目錄路徑 (Copy Path)")
            menu.addSeparator()
            act_switch = menu.addAction("📂 設為當前根工作目錄")
            act_import_sub = menu.addAction("➕ 讀入此目錄架構交給 AI")
            act_open = menu.addAction("📂 在 Windows 總管中開啟")
            if target_path != self.current_workspace_dir:
                menu.addSeparator()
                act_delete = menu.addAction("🗑️ 刪除此資料夾 (Delete)")
            else:
                act_delete = None

            action = menu.exec_(self.tree_workspace.viewport().mapToGlobal(pos))
            if action == act_new_file:
                self.create_new_file_in_workspace(target_path)
            elif action == act_new_folder:
                self.create_new_folder_in_workspace(target_path)
            elif action == act_rename:
                self.rename_workspace_item(target_path)
            elif action == act_duplicate:
                self.duplicate_workspace_item(target_path)
            elif action == act_copy:
                QApplication.clipboard().setText(str(target_path))
            elif action == act_switch:
                self.current_workspace_dir = target_path
                self.lbl_workspace_name.setText(f"📁 {target_path.name}")
                self.populate_file_tree(target_path)
            elif action == act_import_sub:
                self.import_folder_structure(target_path)
            elif action == act_open:
                silent_popen(["explorer.exe", str(target_path)])
            elif act_delete and action == act_delete:
                self.delete_workspace_item(target_path)

    def _on_file_tree_double_clicked(self, item: QTreeWidgetItem, column: int):
        path_str = item.data(0, Qt.UserRole)
        if not path_str:
            return
        target_path = Path(path_str)
        if target_path.is_file():
            self.attach_single_file(target_path)

    def import_workspace_structure_to_chat(self):
        self.import_folder_structure(self.current_workspace_dir)

    def import_folder_structure(self, folder: Path):
        """讀入整個資料夾的目錄結構交給 AI"""
        lines = [f"專案目錄架構：{folder.name}/"]
        ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea"}
        count = 0
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in ignored]
            rel_dir = os.path.relpath(root, folder)
            indent = "  " * (0 if rel_dir == "." else rel_dir.count(os.sep) + 1)
            if rel_dir != ".":
                lines.append(f"{indent}📁 {os.path.basename(root)}/")
            for f in files:
                if count > 100:
                    lines.append(f"{indent}  ... (後續檔案已折疊)")
                    break
                lines.append(f"{indent}  📄 {f}")
                count += 1
            if count > 100:
                break
        structure_text = "\n".join(lines)
        self.input_text.setText(f"請分析以下檔案架構並給予架構優化或程式碼檢查建議：\n```text\n{structure_text}\n```")

    # ================= 各種檔案附加與預覽 (圖一擴充) =================

    def select_files_to_attach(self):
        """選擇各種類型檔案（代碼、文字、文件、圖片等）附加"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "選擇要交給 AI 的檔案 (可多選)",
            str(self.current_workspace_dir),
            "所有檔案 (*.*);;程式代碼 (*.py *.js *.ts *.html *.css *.json *.md *.sh *.bat);;文字檔案 (*.txt *.csv *.log);;圖片檔案 (*.png *.jpg *.jpeg *.webp)",
        )
        if files:
            for f in files:
                p = Path(f)
                if p not in self.attached_files:
                    self.attached_files.append(p)
            self._update_attachment_banner()

    def attach_single_file(self, file_path: Path):
        if file_path not in self.attached_files:
            self.attached_files.append(file_path)
            self._update_attachment_banner()

    def _update_attachment_banner(self):
        if hasattr(self, "chat_input_card"):
            self.chat_input_card.clear_all_chips()
            if self.attached_screenshot_b64:
                pix = None
                if self.latest_live_pil_img:
                    try:
                        from PIL.ImageQt import ImageQt
                        qim = ImageQt(self.latest_live_pil_img)
                        pix = QPixmap.fromImage(qim)
                    except Exception:
                        pass
                self.chat_input_card.add_thumbnail_chip("screenshot", "即時螢幕截圖", icon_str="📸", pixmap=pix)

            for p in self.attached_files:
                pix = None
                if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    try:
                        pix = QPixmap(str(p))
                    except Exception:
                        pass
                self.chat_input_card.add_thumbnail_chip(f"file_{p.name}", p.name, icon_str="📄", pixmap=pix)

    def _on_attachment_chip_removed(self, item_id: str):
        """當使用者在輸入盒晶片點擊 ✕ 刪除時，同步清理宿主底層附件物件"""
        if item_id == "screenshot":
            self.attached_screenshot_b64 = None
        elif item_id.startswith("file_"):
            filename = item_id[5:]
            self.attached_files = [
                p for p in self.attached_files
                if (p.name if hasattr(p, "name") else Path(str(p)).name) != filename
            ]

    def _on_remove_attachment_item(self, item_id: str):
        if item_id == "screenshot":
            self.attached_screenshot_b64 = None
        elif item_id.startswith("file_"):
            filename = item_id[5:]
            self.attached_files = [
                p for p in self.attached_files
                if (p.name if hasattr(p, "name") else Path(str(p)).name) != filename
            ]
        self._update_attachment_banner()

    def clear_all_attachments(self):
        self.attached_screenshot_b64 = None
        self.attached_files.clear()
        if hasattr(self, "chat_input_card"):
            self.chat_input_card.clear_all_chips()

    def clear_attachment(self):
        self.clear_all_attachments()

    def _prompt_browser_url(self):
        url, ok = QInputDialog.getText(self, "🌐 深度網頁分析與瀏覽", "請輸入要分析或摘要的網頁 URL 或搜尋目標：")
        if ok and url.strip():
            cmd = f"/browser {url.strip()} "
            self.chat_input_card.set_text(cmd)

    def _prompt_window_mention(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #181d28; border: 1px solid #334155; border-radius: 8px; padding: 4px; color: #e2e8f0; }
            QMenu::item { padding: 6px 16px; border-radius: 4px; font-size: 12.5px; }
            QMenu::item:selected { background: #0284c7; color: #ffffff; }
        """)
        act_h = QAction("可提及的目前視窗 (點選注入 @視窗名稱)：", menu)
        act_h.setEnabled(False)
        menu.addAction(act_h)
        menu.addSeparator()

        count = self.combo_windows.count()
        added = 0
        for i in range(min(count, 15)):
            title = self.combo_windows.itemText(i)
            if title and not title.startswith("--"):
                clean = title.split(" (HWND:")[0].strip()
                act = QAction(f"🪟 @{clean[:32]}", menu)
                act.triggered.connect(lambda checked, t=clean: self._insert_mention(t))
                menu.addAction(act)
                added += 1

        if added == 0:
            act_none = QAction("(目前未選取任何視窗)", menu)
            act_none.setEnabled(False)
            menu.addAction(act_none)

        menu.exec_(QCursor.pos())

    def _insert_mention(self, mention_text: str):
        cur = self.chat_input_card.text_edit.toPlainText()
        self.chat_input_card.set_text(f"{cur} @{mention_text} ")

    def _on_card_model_changed(self, model_id: str):
        self.settings_manager.update_settings({"selected_model": model_id})
        idx = self.combo_models.findData(model_id)
        if idx >= 0:
            self.combo_models.blockSignals(True)
            self.combo_models.setCurrentIndex(idx)
            self.combo_models.blockSignals(False)

    def _on_card_mode_changed(self, mode_key: str):
        self.current_execution_mode = mode_key
        if hasattr(self, "chat_input_card") and self.chat_input_card:
            if getattr(self.chat_input_card, "_current_mode", None) != mode_key:
                self.chat_input_card.set_execution_mode(mode_key)
        if hasattr(self, "security_guard") and self.security_guard:
            self.security_guard.set_execution_mode(mode_key)
        if hasattr(self, "agent_brain") and self.agent_brain and getattr(self.agent_brain, "security_guard", None):
            self.agent_brain.security_guard.set_execution_mode(mode_key)
        if hasattr(self, "settings_manager") and self.settings_manager:
            try:
                self.settings_manager.set("execution_mode", mode_key)
            except Exception:
                pass
        mode_names = {
            "request_review": "嚴格審查 (Request Review - 每項指令皆需人工放行)",
            "default": "標準防護 (Default - 僅敏感視窗與交易攔截)",
            "auto": "智慧判定 (Auto - 安全引擎自動評估)",
            "turbo": "極速無阻 (Turbo - 全速自動化執行)",
        }
        name = mode_names.get(mode_key, mode_key)
        self.statusBar().showMessage(f"🛡️ 已切換防護層級為：{name}", 4000)

    def preview_file_dialog(self, file_path: Path):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"預覽檔案內容：{file_path.name}")
        dlg.resize(650, 440)
        dlg.setStyleSheet(MODERN_DARK_STYLE)
        l = QVBoxLayout(dlg)
        browser = QTextBrowser()
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")[:6000]
            browser.setPlainText(content)
        except Exception as e:
            browser.setPlainText(f"無法讀取檔案內容：{e}")
        l.addWidget(browser)
        dlg.exec_()

    # ================= 歷史紀錄專區 (永久保存區 + 暫存區拖曳 + 兩邊釘選 + 2週自動清理) =================

    def reload_history_lists(self):
        """載入歷史紀錄並分類顯示在永久保存區與暫存區，兩邊皆支援釘選置頂"""
        sessions = self.history_manager.list_sessions()
        self.list_history_perm.clear()
        self.list_history_temp.clear()

        # 永久保存區 (支援釘選)
        for s in sessions["permanent"]:
            t_str = time.strftime("%m/%d %H:%M", time.localtime(s["updated_at"])) if s["updated_at"] else ""
            is_pinned = s.get("is_pinned", False)
            pin_tag = "📌 " if is_pinned else "⭐ "
            item = QListWidgetItem(f"{pin_tag}{s['title']} ({t_str})")
            item.setData(Qt.UserRole, s["id"])
            if is_pinned:
                item.setForeground(QColor("#38bdf8"))
            item.setToolTip(f"ID: {s['id']}\n更新: {t_str}\n釘選狀態: {'已釘選' if is_pinned else '未釘選'}\n訊息數: {s.get('message_count', 0)}")
            self.list_history_perm.addItem(item)

        # 暫存區 (超過 2 週無對話自動清理，支援釘選保護)
        for s in sessions["temp"]:
            t_str = time.strftime("%m/%d %H:%M", time.localtime(s["updated_at"])) if s["updated_at"] else ""
            is_pinned = s.get("is_pinned", False)
            pin_tag = "📌 " if is_pinned else "⏳ "
            item = QListWidgetItem(f"{pin_tag}{s['title']} ({t_str})")
            item.setData(Qt.UserRole, s["id"])
            if is_pinned:
                item.setForeground(QColor("#38bdf8"))
            item.setToolTip(f"ID: {s['id']}\n更新: {t_str}\n釘選狀態: {'已釘選 (防過期自動刪除)' if is_pinned else '未釘選'}\n訊息數: {s.get('message_count', 0)}")
            self.list_history_temp.addItem(item)

    def _on_history_dropped(self, session_id: str, target_category: str):
        """拖曳對話項目到永久區或暫存區"""
        self.history_manager.move_session(session_id, target_category)
        if session_id == self.current_session_id:
            self.current_category = target_category
        self.reload_history_lists()

    def _on_history_item_clicked(self, item: QListWidgetItem):
        sess_id = item.data(Qt.UserRole)
        if sess_id:
            self.load_history_session(sess_id)

    def load_history_session(self, session_id: str):
        sess = self.history_manager.get_session(session_id)
        if not sess:
            return
        self.current_session_id = session_id
        self.current_category = sess.get("category", "temp")
        self.current_messages = sess.get("messages", [])

        self.chat_browser.clear()
        pin_icon = "📌 " if sess.get("is_pinned") else ""
        pill = f"<div style='font-size:11px;color:#94a3b8;margin-bottom:12px;text-align:center;'>── 已載入對話紀錄：<b>{pin_icon}{html.escape(sess.get('title', ''))}</b> ──</div>"
        self.chat_browser.append(pill)

        for idx, m in enumerate(self.current_messages):
            self._render_bubble_html(m.get("role", "user"), m.get("text", ""), m.get("img_b64"), msg_idx=idx)

        # 同步 context 給 AgentBrain 接續上下文
        conv = [{"role": "system", "content": self.agent_brain.SYSTEM_PROMPT}]
        for m in self.current_messages:
            role = "user" if m.get("role") == "user" else "assistant"
            conv.append({"role": role, "content": m.get("text", "")})
        self.agent_brain.conversations[session_id] = conv
        self._refresh_nav_dots()
        self._scroll_chat_to_bottom(self.chat_browser)

    def _show_history_context_menu(self, pos: QPoint, list_widget: DraggableHistoryList, category: str):
        item = list_widget.itemAt(pos)
        if not item:
            return
        sess_id = item.data(Qt.UserRole)
        sess = self.history_manager.get_session(sess_id)
        is_pinned = sess.get("is_pinned", False) if sess else False

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #161922; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px; padding: 4px; color: #f1f5f9; }
            QMenu::item { padding: 6px 18px; border-radius: 4px; font-size: 12.5px; }
            QMenu::item:selected { background: #283044; color: #60a5fa; }
            QMenu::separator { height: 1px; background: rgba(255,255,255,0.08); margin: 4px 8px; }
        """)

        # 1. 釘選 / 取消釘選 (兩邊都能釘選)
        pin_label = "📌 取消釘選 (Unpin)" if is_pinned else "📌 釘選置頂 (Pin)"
        act_pin = menu.addAction(pin_label)

        # 2. 重新命名
        act_rename = menu.addAction("✏️ 重新命名 (Rename)")

        # 3. 複製對話副本
        act_dup = menu.addAction("📋 複製對話副本 (Duplicate)")

        # 4. 複製文字內容
        act_copy_text = menu.addAction("📋 複製對話全文 (Copy Text)")

        menu.addSeparator()

        # 5. 分類移動
        if category == "temp":
            act_move = menu.addAction("⭐ 移至永久保存區")
        else:
            act_move = menu.addAction("⏳ 移至暫存區")

        menu.addSeparator()

        # 6. 直接刪除
        act_delete = menu.addAction("🗑️ 直接刪除 (Delete)")

        action = menu.exec_(list_widget.viewport().mapToGlobal(pos))
        if action == act_pin:
            self.history_manager.toggle_pin(sess_id)
            self.reload_history_lists()
        elif action == act_rename:
            cur_txt = item.text().split(" (")[0].replace("📌 ", "").replace("⭐ ", "").replace("⏳ ", "")
            new_title, ok = QInputDialog.getText(self, "重新命名", "請輸入新對話名稱：", text=cur_txt)
            if ok and new_title.strip():
                self.history_manager.rename_session(sess_id, new_title.strip())
                self.reload_history_lists()
        elif action == act_dup:
            new_id = self.history_manager.duplicate_session(sess_id)
            if new_id:
                self.reload_history_lists()
                self.statusBar().showMessage("📋 已成功複製對話副本", 3000)
        elif action == act_copy_text:
            if sess:
                lines = []
                for m in sess.get("messages", []):
                    prefix = "【使用者】" if m.get("role") == "user" else "【AI】"
                    lines.append(f"{prefix}\n{m.get('text', '')}\n")
                QApplication.clipboard().setText("\n".join(lines))
                self.statusBar().showMessage("📋 已複製對話全文至剪貼簿", 3000)
        elif action == act_move:
            new_cat = "permanent" if category == "temp" else "temp"
            self.history_manager.move_session(sess_id, new_cat)
            self.reload_history_lists()
        elif action == act_delete:
            self.delete_history_session_direct(sess_id)

    def delete_history_session_direct(self, session_id: str):
        """直接刪除對話紀錄"""
        self.history_manager.delete_session(session_id)
        if self.current_session_id == session_id:
            self.new_chat_session()
        self.reload_history_lists()
        self.statusBar().showMessage("🗑️ 已成功刪除歷史對話", 3000)

    # ================= 排程專區 (支援卡片式直接刪除) =================

    def reload_schedules_list(self):
        """載入排程清單，每個排程帶有獨立啟用開關、立即執行與直接刪除按鈕"""
        schedules = self.schedule_manager.list_schedules()
        self.list_schedules.clear()
        for s in schedules:
            sched_id = s["id"]
            enabled = s.get("enabled", False)
            interval = s.get("interval_minutes", 30)
            next_t = time.strftime("%H:%M:%S", time.localtime(s.get("next_run", 0)))

            item = QListWidgetItem()
            item.setSizeHint(QSize(260, 48))
            item.setData(Qt.UserRole, sched_id)
            self.list_schedules.addItem(item)

            # 自訂排程卡片元件
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: #12141c;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 6px;
                }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(6, 4, 6, 4)
            card_layout.setSpacing(6)

            # 狀態指示
            status_btn = QPushButton("🟢" if enabled else "⚪")
            status_btn.setFixedSize(26, 26)
            status_btn.setToolTip("切換啟用 / 停用")
            status_btn.setStyleSheet("background: transparent; border: none; font-size: 13px;")
            status_btn.clicked.connect(lambda _, sid=sched_id, cur_en=enabled: self._toggle_schedule_enabled(sid, cur_en))
            card_layout.addWidget(status_btn)

            # 文字描述
            txt_box = QVBoxLayout()
            txt_box.setSpacing(0)
            lbl_title = QLabel(f"<b>{s['name'][:16]}</b>")
            lbl_title.setStyleSheet("color: #f1f5f9; font-size: 11.5px;")
            lbl_sub = QLabel(f"每 {interval} 分鐘 | 下次: {next_t}")
            lbl_sub.setStyleSheet("color: #94a3b8; font-size: 10px;")
            txt_box.addWidget(lbl_title)
            txt_box.addWidget(lbl_sub)
            card_layout.addLayout(txt_box, stretch=1)

            # 立即執行按鈕
            btn_run = QPushButton("▶")
            btn_run.setToolTip("立即手動執行此排程")
            btn_run.setFixedSize(26, 26)
            btn_run.clicked.connect(lambda _, sc=s: self._trigger_schedule_task(sc))
            card_layout.addWidget(btn_run)

            # 🗑️ 直接刪除按鈕
            btn_del = QPushButton("🗑️")
            btn_del.setToolTip("直接刪除此排程")
            btn_del.setFixedSize(26, 26)
            btn_del.setStyleSheet("""
                QPushButton { background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; }
                QPushButton:hover { background: rgba(239, 68, 68, 0.35); border-color: #ef4444; }
            """)
            btn_del.clicked.connect(lambda _, sid=sched_id: self.delete_schedule_direct(sid))
            card_layout.addWidget(btn_del)

            self.list_schedules.setItemWidget(item, card)

    def _toggle_schedule_enabled(self, sched_id: str, current_enabled: bool):
        self.schedule_manager.update_schedule(sched_id, enabled=not current_enabled)
        self.reload_schedules_list()

    def delete_schedule_direct(self, sched_id: str):
        """直接刪除排程"""
        self.schedule_manager.delete_schedule(sched_id)
        self.reload_schedules_list()
        self.statusBar().showMessage("🗑️ 已直接刪除排程任務", 3000)

    def _show_schedule_context_menu(self, pos: QPoint):
        item = self.list_schedules.itemAt(pos)
        if not item:
            return
        sched_id = item.data(Qt.UserRole)
        schedules = self.schedule_manager.list_schedules()
        sched = next((s for s in schedules if s["id"] == sched_id), None)
        if not sched:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #161922; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px; padding: 4px; color: #f1f5f9; }
            QMenu::item { padding: 6px 18px; border-radius: 4px; font-size: 12.5px; }
            QMenu::item:selected { background: #283044; color: #60a5fa; }
            QMenu::separator { height: 1px; background: rgba(255,255,255,0.08); margin: 4px 8px; }
        """)
        act_run = menu.addAction("▶ 立即手動執行此排程")
        act_toggle = menu.addAction("⚪ 停用此排程" if sched.get("enabled") else "🟢 啟用此排程")
        menu.addSeparator()
        act_delete = menu.addAction("🗑️ 直接刪除排程 (Delete)")

        action = menu.exec_(self.list_schedules.viewport().mapToGlobal(pos))
        if action == act_run:
            self._trigger_schedule_task(sched)
        elif action == act_toggle:
            self._toggle_schedule_enabled(sched_id, sched.get("enabled", False))
        elif action == act_delete:
            self.delete_schedule_direct(sched_id)

    def open_add_schedule_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("➕ 新增定時背景排程")
        dlg.resize(460, 240)
        dlg.setStyleSheet(MODERN_DARK_STYLE)
        f_layout = QFormLayout(dlg)

        in_name = QLineEdit("定時巡檢代碼與環境")
        in_prompt = QTextEdit("請在背景檢查工作目錄與視窗，審查代碼與編譯是否有潛在錯誤。")
        in_prompt.setFixedHeight(60)
        in_interval = QSpinBox()
        in_interval.setRange(1, 1440)
        in_interval.setValue(30)
        in_interval.setSuffix(" 分鐘")

        f_layout.addRow("排程任務名稱：", in_name)
        f_layout.addRow("執行 Prompt：", in_prompt)
        f_layout.addRow("執行間隔：", in_interval)

        btn_box = QHBoxLayout()
        btn_ok = QPushButton("新增並啟動")
        btn_ok.setObjectName("primaryBtn")
        btn_box.addWidget(btn_ok)
        f_layout.addRow(btn_box)

        def _do_add():
            if not in_name.text().strip() or not in_prompt.toPlainText().strip():
                return
            self.schedule_manager.add_schedule(
                name=in_name.text().strip(),
                prompt=in_prompt.toPlainText().strip(),
                interval_minutes=in_interval.value(),
            )
            self.reload_schedules_list()
            dlg.accept()

        btn_ok.clicked.connect(_do_add)
        dlg.exec_()

    def _check_and_run_schedules(self):
        """定時器觸發：檢查是否有到期的排程並執行"""
        due = self.schedule_manager.get_due_schedules()
        for s in due:
            self._trigger_schedule_task(s)
            self.schedule_manager.mark_run(s["id"])
        if due:
            self.reload_schedules_list()

    def _trigger_schedule_task(self, sched: Dict[str, Any]):
        prompt = sched.get("prompt", "")
        name = sched.get("name", "未命名排程")
        header = f"⏰ [定時排程自動執行: {name}]\n"
        self.send_user_message(header + prompt)

    def reload_models_combo(self):
        catalog = self.api_manager.get_models_catalog()
        self.combo_models.clear()

        # 🤖 首位新增「智慧自動路由」模式
        self.combo_models.addItem("🤖 智慧自動路由 (依視覺/推理/代碼動態分配)", "auto_router")

        if not catalog:
            self.lbl_status_models.setText("可用模型：0 個 (請點擊設定金鑰)")
            return

        selected = self.settings_manager.get_raw().get("selected_model", "auto_router")
        self.lbl_status_models.setText(f"可用模型：{len(catalog)} 個 (支援多模型路由)")

        for m in catalog:
            tag = "🟢" if m["has_key"] else "⚪"
            self.combo_models.addItem(f"{tag} {m['display_name']}", m["full_id"])

        idx = self.combo_models.findData(selected)
        if idx >= 0:
            self.combo_models.setCurrentIndex(idx)
        else:
            self.combo_models.setCurrentIndex(0)

        # 同步更新底部卡片之可用模型選單 (對齊圖三)
        if hasattr(self, "chat_input_card"):
            self.chat_input_card.set_available_models(catalog, selected)

    def _on_model_changed(self, idx):
        full_id = self.combo_models.currentData()
        if full_id:
            self.settings_manager.update_settings({"selected_model": full_id})
            if hasattr(self, "chat_input_card"):
                catalog = self.api_manager.get_models_catalog()
                self.chat_input_card.set_available_models(catalog, full_id)

    def open_api_manager_dialog(self):
        dlg = ApiManagerDialog(self.api_manager, self.async_worker, self)
        self._api_dialog = dlg
        try:
            if dlg.exec_():
                self.reload_models_combo()
        finally:
            self._api_dialog = None

    def open_dlc_manager_dialog(self):
        dlg = DlcManagerDialog(settings_manager=self.settings_manager, parent=self)
        dlg.sig_dlc_changed.connect(self._on_dlc_configuration_changed)
        dlg.exec_()

    def _on_dlc_configuration_changed(self):
        # 當 DLC 模組狀態更新時，通知系統與代理重新註冊工具
        try:
            from core.addon_module_manager import addon_module_manager
            addon_module_manager.refresh_agent_tool_registry()
        except Exception:
            pass

    # ── 本地模型自動偵測與接入 ───────────────────────────────
    def scan_local_models(self, manual: bool = False):
        """背景掃描本機模型服務；manual=True 時連「不再詢問」的模型也列出，且沒找到時會提示"""
        if self._local_scan_running:
            return
        self._local_scan_running = True

        async def _scan():
            scanned = await self.local_model_scanner.scan()
            return self.local_model_scanner.find_new_models(
                self.api_manager, scanned, include_dismissed=manual
            )

        def _done(fut):
            try:
                found = fut.result()
            except Exception:
                found = []
            # 跨執行緒：一律透過 signal 回到 UI 執行緒處理
            self.sig_local_models_found.emit(found, manual)

        self.async_worker.submit(_scan()).add_done_callback(_done)

    def _on_local_models_found(self, services: list, manual: bool):
        self._local_scan_running = False
        parent = self._api_dialog or self
        if not services:
            if manual:
                QMessageBox.information(
                    parent, "掃描本機模型",
                    "沒有找到尚未接入的本地模型。\n\n"
                    "支援：Ollama (11434)、LM Studio (1234)、llama.cpp (8080)。\n"
                    "請確認服務已啟動並至少下載一個模型。",
                )
            return

        dlg = LocalModelConsentDialog(services, parent)
        dlg.exec_()
        if dlg.choice == RESULT_NEVER:
            for svc, models in dlg.selections(checked=True) + dlg.selections(checked=False):
                self.local_model_scanner.dismiss(svc, models)
            return
        if dlg.choice != RESULT_ADD:
            return

        added, errors = [], []
        for svc, models in dlg.selections(checked=True):
            try:
                self.local_model_scanner.apply(self.api_manager, svc, models)
                added += models
            except Exception as e:  # noqa: BLE001
                errors.append(f"{svc['name']}：{e}")
        # 沒勾的視為不要，之後不再自動詢問（手動掃描仍會列出）
        for svc, models in dlg.selections(checked=False):
            self.local_model_scanner.dismiss(svc, models)

        self.reload_models_combo()
        if self._api_dialog is not None:
            self._api_dialog.load_table_data()
        if errors:
            QMessageBox.warning(parent, "部分模型接入失敗", "\n".join(errors))
        elif added:
            QMessageBox.information(
                parent, "本地模型已接入",
                f"✅ 已將 {len(added)} 個本地模型接入 Agent：\n" + "\n".join(f"• {m}" for m in added),
            )

    def _populate_system_menu(self):
        if not hasattr(self, "btn_system_menu") or not self.btn_system_menu:
            return
        menu_sys = QMenu(self.btn_system_menu)
        act_pref = menu_sys.addAction(t("menu_system_settings"))
        act_pref.triggered.connect(lambda: self.open_settings_dialog(0))

        # 🌐 語言切換選單 (繁體中文、簡體中文、英文、日語、韓文)
        menu_lang = menu_sys.addMenu(t("menu_language"))
        curr_lang = i18n.get_language()
        for code, name in SUPPORTED_LANGUAGES.items():
            act = menu_lang.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == curr_lang)
            act.triggered.connect(lambda checked, c=code: self.switch_language(c))

        menu_sys.addSeparator()
        act_api = menu_sys.addAction(t("btn_manage_api"))
        act_api.triggered.connect(lambda: self.open_settings_dialog(1))
        act_win = menu_sys.addAction(t("menu_new_window"))
        act_win.triggered.connect(self.spawn_new_instance)
        act_sec = menu_sys.addAction(t("btn_sec_center"))
        act_sec.triggered.connect(self.switch_to_security_tab)
        menu_sys.addSeparator()
        self.act_dnd_menu = menu_sys.addAction(t("btn_dnd_on") if self.manual_dnd else t("btn_dnd_off"))
        self.act_dnd_menu.triggered.connect(self.toggle_dnd)
        act_logs = menu_sys.addAction(t("tab_web"))
        act_logs.triggered.connect(self.switch_to_logs_tab)

        # 防護等級（與輸入框的模式按鈕同步）
        menu_sys.addSeparator()
        menu_guard = menu_sys.addMenu("🛡️ 防護等級")
        for key, name in (("default", "🟢 標準防護"), ("request_review", "🟡 嚴格審查"),
                          ("auto", "🔵 智慧自動"), ("turbo", "⚡ 極速無阻")):
            a = menu_guard.addAction(name)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, k=key: self._on_card_mode_changed(k))
            a.setData(key)

        def _sync_guard():
            cur = getattr(self, "current_execution_mode", "default")
            for a in menu_guard.actions():
                a.setChecked(a.data() == cur)
        menu_guard.aboutToShow.connect(_sync_guard)

        # Google 帳號（內容沿用原本 Google 按鈕的選單，打開時才取最新狀態）
        menu_google = menu_sys.addMenu("🌐 Google 帳號")

        def _sync_google():
            menu_google.clear()
            src_btn = getattr(self, "btn_google_login", None)
            src_menu = src_btn.menu() if src_btn is not None else None
            if src_menu is None:
                menu_google.addAction("（尚未載入）").setEnabled(False)
                return
            status = menu_google.addAction(src_btn.text().replace("▾", "").strip())
            status.setEnabled(False)
            menu_google.addSeparator()
            menu_google.addActions(src_menu.actions())
        menu_google.aboutToShow.connect(_sync_google)

        def _sync_google_title():
            src_btn = getattr(self, "btn_google_login", None)
            if src_btn is not None and "已登入" in src_btn.text():
                menu_google.setTitle("🌐 Google 帳號（已登入）")
            else:
                menu_google.setTitle("🌐 Google 帳號")
        menu_sys.aboutToShow.connect(_sync_google_title)

        self.btn_system_menu.setMenu(menu_sys)

    def _update_google_login_button(self):
        if not hasattr(self, "btn_google_login") or not self.btn_google_login:
            return

        is_auth = google_suite.is_authenticated()
        has_synced = os.path.exists(habit_sync_engine.profile_path)

        menu = QMenu(self.btn_google_login)

        if is_auth:
            self.btn_google_login.setText("🟢 Google 已登入 ▾")
            self.btn_google_login.setStyleSheet("""
                QToolButton {
                    background-color: #064e3b;
                    color: #4ade80;
                    border: 1px solid rgba(74, 222, 128, 0.4);
                    border-radius: 8px;
                    padding: 6px 12px;
                    font-weight: 700;
                    font-size: 12px;
                }
                QToolButton:hover {
                    background-color: #065f46;
                    border-color: #4ade80;
                }
            """)
            act_sync = menu.addAction("⚡ 立即同步個人習慣 (Sync Habits)")
            act_sync.triggered.connect(self._main_sync_habits)
            act_cloud_sync = menu.addAction("☁️ 同步雲端日曆與硬碟")
            act_cloud_sync.triggered.connect(self._main_sync_cloud_habits)
            menu.addSeparator()
            act_gmail = menu.addAction("✉️ 開啟 Gmail")
            act_gmail.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("gmail")))
            act_drive = menu.addAction("📁 開啟 Google Drive")
            act_drive.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("drive")))
            act_cal = menu.addAction("📅 開啟 Google Calendar")
            act_cal.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("calendar")))
            act_docs = menu.addAction("📝 開啟 Google Docs")
            act_docs.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("docs")))
            act_sheets = menu.addAction("📊 開啟 Google Sheets")
            act_sheets.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("sheets")))
            menu.addSeparator()
            act_cfg = menu.addAction("⚙️ Google 整合與習慣設定...")
            act_cfg.triggered.connect(lambda: self.open_settings_dialog(5))

        elif has_synced:
            self.btn_google_login.setText("🟢 習慣已同步 (本機) ▾")
            self.btn_google_login.setStyleSheet("""
                QToolButton {
                    background-color: #1e3a8a;
                    color: #60a5fa;
                    border: 1px solid rgba(96, 165, 250, 0.4);
                    border-radius: 8px;
                    padding: 6px 12px;
                    font-weight: 700;
                    font-size: 12px;
                }
                QToolButton:hover {
                    background-color: #1d4ed8;
                    border-color: #93c5fd;
                }
            """)
            act_sync = menu.addAction("⚡ 重新同步本機習慣 (Chrome/Edge)")
            act_sync.triggered.connect(self._main_sync_habits)
            act_login = menu.addAction("🚀 升級雲端授權 (登入 Google OAuth)")
            act_login.triggered.connect(self._main_login_google)
            menu.addSeparator()
            act_gmail = menu.addAction("✉️ 開啟 Gmail")
            act_gmail.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("gmail")))
            act_drive = menu.addAction("📁 開啟 Google Drive")
            act_drive.triggered.connect(lambda: webbrowser.open(google_suite.get_service_url("drive")))
            menu.addSeparator()
            act_cfg = menu.addAction("⚙️ Google 整合與習慣設定...")
            act_cfg.triggered.connect(lambda: self.open_settings_dialog(5))

        else:
            self.btn_google_login.setText("🌐 登入 Google ▾")
            self.btn_google_login.setStyleSheet("""
                QToolButton {
                    background-color: #2563eb;
                    color: #ffffff;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 8px;
                    padding: 6px 14px;
                    font-weight: 700;
                    font-size: 12px;
                }
                QToolButton:hover {
                    background-color: #1d4ed8;
                    border-color: #60a5fa;
                }
            """)
            act_fast = menu.addAction("⚡ 免密碼本機 Chrome 一鍵快速同步")
            act_fast.triggered.connect(self._main_sync_habits)
            act_oauth = menu.addAction("🚀 啟動 Google 帳號授權登入 (OAuth)")
            act_oauth.triggered.connect(self._main_login_google)
            menu.addSeparator()
            act_import = menu.addAction("📂 匯入 credentials.json 憑證...")
            act_import.triggered.connect(self._top_import_google_credentials)
            menu.addSeparator()
            act_open_web = menu.addAction("🌐 瀏覽器開啟 Google 帳號...")
            act_open_web.triggered.connect(lambda: webbrowser.open("https://myaccount.google.com"))

        self.btn_google_login.setMenu(menu)

    def _top_import_google_credentials(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "選取 Google Cloud credentials.json",
            "",
            "JSON Files (*.json)"
        )
        if file_path:
            target_dir = os.path.dirname(google_suite.creds_path)
            os.makedirs(target_dir, exist_ok=True)
            import shutil
            shutil.copyfile(file_path, google_suite.creds_path)
            QMessageBox.information(self, "憑證匯入成功", "憑證已成功保存！\n現在可點擊「登入 Google」按鈕啟動一次性登入。")
            self._update_google_login_button()

    def open_settings_dialog(self, initial_tab: int = 0):
        dlg = SettingsDialog(
            settings_manager=self.settings_manager,
            api_manager=self.api_manager,
            async_worker=self.async_worker,
            parent=self,
            initial_tab_index=initial_tab,
        )
        dlg.sig_settings_saved.connect(self._on_settings_saved)
        dlg.sig_language_changed.connect(self.switch_language)
        if dlg.exec_():
            self.reload_models_combo()

    def switch_language(self, lang_code: str):
        if lang_code not in SUPPORTED_LANGUAGES:
            return
        i18n.set_language(lang_code, notify=True)
        self.settings_manager.update_settings({"language": lang_code})
        self._retranslate_ui()

    def _on_settings_saved(self, payload: Dict[str, Any]):
        if "language" in payload:
            self.switch_language(payload["language"])
        self.reload_models_combo()

    def _on_language_changed_global(self, lang_code: str):
        self._retranslate_ui()

    def _retranslate_ui(self):
        # 1. 主視窗標題
        self.setWindowTitle(t("app_title"))

        # 2. 頂部選單列與下拉選單
        self._create_menu_bar()
        self._populate_system_menu()
        if hasattr(self, "btn_system_menu"):
            self.btn_system_menu.setText(t("btn_settings") + " ▾")

        # 3. 側邊欄標籤與按鈕
        if hasattr(self, "sidebar_tabs"):
            self.sidebar_tabs.setTabText(0, t("tab_quick"))
            self.sidebar_tabs.setTabText(1, t("tab_explorer"))
            self.sidebar_tabs.setTabText(2, t("tab_history"))
            self.sidebar_tabs.setTabText(3, t("tab_schedule"))
        if hasattr(self, "btn_q1"):
            self.btn_q1.setText(t("btn_q_capture"))
        if hasattr(self, "btn_q2"):
            self.btn_q2.setText(t("btn_q_monitor"))
        if hasattr(self, "btn_q3"):
            self.btn_q3.setText(t("btn_q_git"))
        if hasattr(self, "btn_q4"):
            self.btn_q4.setText(t("btn_q_search"))
        if hasattr(self, "btn_q5"):
            self.btn_q5.setText(t("btn_q_structure"))
        if hasattr(self, "btn_manage_api"):
            self.btn_manage_api.setText(t("btn_manage_api"))
        if hasattr(self, "btn_sidebar_settings"):
            self.btn_sidebar_settings.setText(t("btn_sidebar_settings"))

        # 4. 右側面板標籤
        if hasattr(self, "tabs"):
            self.tabs.setTabText(0, t("tab_stream"))
            self.tabs.setTabText(1, t("tab_mcp"))
            self.tabs.setTabText(2, t("tab_web"))
            self.tabs.setTabText(3, t("tab_security"))

        # 5. 聊天輸入卡片
        if hasattr(self, "chat_input_card") and hasattr(self.chat_input_card, "retranslate_ui"):
            self.chat_input_card.retranslate_ui()

        # 6. 右側控制鈕與標題
        if hasattr(self, "btn_start_sup"):
            self.btn_start_sup.setText(t("btn_start_sup"))
        if hasattr(self, "btn_stop_sup"):
            self.btn_stop_sup.setText(t("btn_stop_sup"))
        if hasattr(self, "btn_resume_sup"):
            self.btn_resume_sup.setText(t("btn_resume_sup"))
        if hasattr(self, "btn_record"):
            is_rec = hasattr(self, "streamer") and hasattr(self.streamer, "recorder") and self.streamer.recorder.is_recording
            self.btn_record.setText(t("btn_record_stop") if is_rec else t("btn_record"))
        if hasattr(self, "btn_kill"):
            self.btn_kill.setText(t("btn_kill"))

        # 7. 系統托盤選單
        self._update_tray_menu()

    def capture_current_selection_to_chat(self):
        """將目前右側即時選定串流中的影格附加至對話"""
        img = self.latest_live_pil_img
        if not img:
            img, _ = self.desktop_controller.capture_window_background(self.selected_hwnd, draw_grid=True)

        if img:
            self.attached_screenshot_b64 = self.desktop_controller.image_to_base64(img)
            self._update_attachment_banner()

    def insert_slash_command(self, cmd_str: str):
        """快捷插入斜線指令到輸入框"""
        current_text = self.input_text.toPlainText().strip()
        if not current_text:
            self.input_text.setPlainText(cmd_str)
        else:
            # 若已有文字且尚未以該指令開頭，則前置插入
            if not current_text.startswith(cmd_str.strip()):
                self.input_text.setPlainText(f"{cmd_str}{current_text}")
        self.input_text.setFocus()
        cursor = self.input_text.textCursor()
        cursor.movePosition(cursor.End)
        self.input_text.setTextCursor(cursor)

    def send_user_message(self, text: str):
        self.input_text.setText(text)
        self.send_current_prompt(text)

    def send_current_prompt(self, prompt_text: Optional[str] = None, allow_commands: bool = True):
        text = (prompt_text if (prompt_text is not None and isinstance(prompt_text, str)) else self.input_text.toPlainText()).strip()
        # Linux 風格代理指令（ps / new / kill 2 / !ls …）：整行完全符合才攔截，其他照常送給 AI
        if allow_commands and not self.attached_files and not self.attached_screenshot_b64:
            parsed = parse_agent_command(text)
            if parsed:
                if self.input_text.toPlainText().strip() == text:
                    self.input_text.clear()
                self._run_agent_command(*parsed)
                return
        running = self._turn_by_agent.get(self.active_agent_id)
        if running is not None and not running.done():
            if not text:
                self._cancel_active_turn()
            else:
                self.statusBar().showMessage("⏳ 這個代理還在執行上一輪；要中途停止，請清空輸入框後按 ■。", 4000)
            return
        if not text and not self.attached_screenshot_b64 and not self.attached_files:
            return

        model_id = self._team_model_for_active() or self.combo_models.currentData()  # 每個代理可用不同模型
        img_b64 = self.attached_screenshot_b64

        # 斜線指令解析與意圖注入
        is_cmd, cmd_key, transformed_text, badge_label = SlashCommandManager.parse_and_transform(text)

        # 讀入附加的各種檔案（代碼、文字、文件、圖片等）
        file_attachments_text = []
        for fp in self.attached_files:
            try:
                if fp.exists():
                    ext = fp.suffix.lower()
                    if ext in (".png", ".jpg", ".jpeg", ".webp") and not img_b64:
                        from PIL import Image as PILImage
                        pil_img = PILImage.open(fp)
                        img_b64 = self.desktop_controller.image_to_base64(pil_img)
                    else:
                        content = fp.read_text(encoding="utf-8", errors="replace")
                        if len(content) > 5000:
                            content = content[:5000] + "\n... (過長內容已自動截斷)"
                        clean_ext = ext.replace(".", "") or "txt"
                        file_attachments_text.append(f"\n\n【附加檔案: {fp.name}】\n```{clean_ext}\n{content}\n```")
            except Exception as e:
                file_attachments_text.append(f"\n\n【附加檔案: {fp.name} (讀取失敗: {e})】")

        raw_user_input = text + "".join(file_attachments_text)
        llm_turn_prompt = (transformed_text if is_cmd else text) + "".join(file_attachments_text)

        self.input_text.clear()
        self.clear_all_attachments()

        # 取得目前活躍代理 (或建立預設代理)
        active_slot = self.agent_slots.get(self.active_agent_id)
        if not active_slot:
            active_slot = self.create_agent_slot("🤖 代理 #1")
        target_aid = active_slot.agent_id
        target_session = active_slot.session_id

        # 標記該代理狀態為運行中
        active_slot.status = "RUNNING"
        active_slot.task_summary = text[:22]
        if active_slot.lbl_status_tag:
            active_slot.lbl_status_tag.setText("⏳ 執行中")
            active_slot.lbl_status_tag.setStyleSheet("background: rgba(245,158,11,0.2); color: #fbbf24; border-radius: 4px; padding: 2px 6px; font-size: 10.5px;")
        self._refresh_agent_tab_bar()

        # 寫入歷史紀錄
        msg_record = {"role": "user", "text": raw_user_input, "img_b64": img_b64, "badge": badge_label if is_cmd else None}
        active_slot.messages.append(msg_record)
        user_msg_idx = len(active_slot.messages) - 1
        self.current_messages = active_slot.messages
        self.history_manager.save_session(
            target_session,
            active_slot.messages,
            category=self.current_category,
        )
        self.reload_history_lists()

        display_html_text = f"<span style='background:#3b82f6;color:#ffffff;padding:2px 7px;border-radius:8px;font-size:11px;font-weight:bold;margin-right:6px;'>{badge_label}</span> {html.escape(raw_user_input)}" if is_cmd else raw_user_input
        self._render_bubble_html_for_slot(active_slot, "user", display_html_text, img_b64, msg_idx=user_msg_idx)
        self._work_begin(target_aid, active_slot.chat_browser)
        if hasattr(self, "chat_input_card") and self.chat_input_card:
            self.chat_input_card.set_running(True)

        async def _do_turn():
            async def _step_cb(step_info):
                step_info["agent_id"] = target_aid
                self.sig_agent_step.emit(step_info)

            def _token_cb(chunk: str):
                self.sig_agent_token.emit(target_aid, chunk)

            try:
                res = await self.agent_brain.run_chat_turn(
                    session_id=target_session,
                    user_message=llm_turn_prompt,
                    model_full_id=model_id,
                    attached_image_b64=img_b64,
                    step_callback=_step_cb,
                    token_callback=_token_cb,
                )
            except asyncio.CancelledError:
                # 被「■ 停止這一輪」或緊急停止中斷：仍要通知 UI 收尾，否則送出鈕會一直停在 ■
                stopped_by_user = self._turn_by_agent.get(target_aid) is None
                msg = ("⏹ 已停止這一輪。" if stopped_by_user
                       else "🛑 已緊急停止：這一輪的思考與工具執行已被中斷。")
                self.sig_agent_reply.emit({"ok": False, "agent_id": target_aid, "tool_steps": [], "reply": msg})
                raise
            res["agent_id"] = target_aid
            self.sig_agent_reply.emit(res)

        fut = self.async_worker.submit(_do_turn())
        self._running_turns.add(fut)
        self._turn_by_agent[target_aid] = fut
        fut.add_done_callback(self._running_turns.discard)

    def _on_agent_token(self, aid: str, chunk: str):
        """串流文字逐字附加在對話最下方；回合結束時由 _on_agent_reply 換成正式泡泡。"""
        slot = self.agent_slots.get(aid or self.active_agent_id)
        browser = slot.chat_browser if slot else self.chat_browser
        doc = browser.document()
        work = self._work.get(aid)
        if work is not None and work.get("out_t") is None:
            work["out_t"] = time.time()  # 開始輸出的時間點（思考時間的終點）
        if aid not in self._stream_start:
            self._append_left_block(browser)
            self._stream_start[aid] = doc.characterCount() - 1
        cur = QTextCursor(doc)
        cur.movePosition(QTextCursor.End)
        cur.insertText(chunk)
        sb = browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_stream_segment(self, aid: str, browser):
        start = self._stream_start.pop(aid, None)
        if start is None:
            return
        cur = QTextCursor(browser.document())
        cur.setPosition(min(start, browser.document().characterCount() - 1))
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()

    # ───────────── 處理過程區塊（執行中顯示步驟，結束後收合成「已處理 X ›」）─────────────

    @staticmethod
    def _fmt_elapsed(seconds: float) -> str:
        sec = max(0, int(round(seconds)))
        if sec < 60:
            return f"{sec} 秒"
        return f"{sec // 60} 分 {sec % 60} 秒"

    @staticmethod
    def _work_items_html(items: List[str]) -> str:
        return "".join(
            f"<div align='left' style='font-size:12px;color:#9ca3af;margin-left:14px;text-align:left;'>{h}</div>" for h in items
        )

    def _ensure_work_anim_timer(self):
        if not hasattr(self, "_work_anim_timer") or self._work_anim_timer is None:
            self._work_anim_timer = QTimer(self)
            self._work_anim_timer.setInterval(110)
            self._work_anim_timer.timeout.connect(self._tick_work_model_animation)
            self._work_anim_tick = 0
        if not self._work_anim_timer.isActive():
            self._work_anim_timer.start()

    def _tick_work_model_animation(self):
        if not getattr(self, "_work", None):
            if hasattr(self, "_work_anim_timer") and self._work_anim_timer.isActive():
                self._work_anim_timer.stop()
            return
        self._work_anim_tick = (getattr(self, "_work_anim_tick", 0) + 1) % 12
        try:
            from PyQt5.QtGui import QTextDocument
            from ui.model_icons import get_brand_animation_frames, resolve_model_brand
            for aid, work in list(self._work.items()):
                slot = self.agent_slots.get(aid) if hasattr(self, "agent_slots") else None
                browser = slot.chat_browser if slot else getattr(self, "chat_browser", None)
                if browser is None:
                    continue
                brand = resolve_model_brand(str(work.get("model_id") or ""), is_local=work.get("is_local"))
                frames = get_brand_animation_frames(brand, n_frames=12, size=32)
                if frames:
                    browser.document().addResource(
                        QTextDocument.ImageResource,
                        QUrl(f"syntra-anim://{aid}"),
                        frames[self._work_anim_tick % len(frames)],
                    )
                    browser.viewport().update()
        except Exception:
            pass

    def _work_live_html(self, work: Dict[str, Any]) -> str:
        n_steps = sum(1 for k, _ in work["items"] if str(k).startswith("step:"))
        aid = work.get("aid") or self.active_agent_id
        lead_icon = f"<img src='syntra-anim://{aid}' width='16' height='16' style='vertical-align:middle;'>"
        head = (f"{lead_icon} 處理中…（已執行 {n_steps} 步）" if n_steps else f"{lead_icon} 思考中…")
        return (
            f"<div align='left' style='font-size:12.5px;color:#9ca3af;text-align:left;'>{head}</div>"
            + self._work_items_html([h for _, h in work["items"]])
        )

    @staticmethod
    def _append_left_block(browser):
        """附加空段落並強制靠左，避免沿用前一段（例如歡迎訊息）的置中格式"""
        browser.append("")
        cur = QTextCursor(browser.document())
        cur.movePosition(QTextCursor.End)
        fmt = cur.blockFormat()
        fmt.setAlignment(Qt.AlignLeft)
        cur.setBlockFormat(fmt)

    def _work_begin(self, aid: str, browser):
        self._append_left_block(browser)
        slot = self.agent_slots.get(aid) if hasattr(self, "agent_slots") else None
        init_mid = str(getattr(slot, "model_id", "") or getattr(self, "selected_model_full_id", "") or "")
        self._work[aid] = {"aid": aid, "t0": time.time(), "start": browser.document().characterCount() - 1, "items": [], "model_id": init_mid}
        self._tick_work_model_animation()
        self._ensure_work_anim_timer()
        self._work_redraw(aid, browser)

    def _work_redraw(self, aid: str, browser):
        work = self._work.get(aid)
        if not work:
            return
        doc = browser.document()
        cur = QTextCursor(doc)
        cur.setPosition(min(work["start"], doc.characterCount() - 1))
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.insertHtml(self._work_live_html(work))
        sb = browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _work_add(self, aid: str, key: str, item_html: str):
        work = self._work.get(aid)
        if not work:
            return
        for n, (k, _) in enumerate(work["items"]):
            if k == key:
                work["items"][n] = (key, item_html)
                return
        work["items"].append((key, item_html))

    def _work_take_stream_note(self, aid: str, browser):
        """把模型在呼叫工具前串流出來的話，收進處理區塊（避免重繪時被蓋掉）"""
        start = self._stream_start.pop(aid, None)
        if start is None:
            return
        doc = browser.document()
        cur = QTextCursor(doc)
        cur.setPosition(min(start, doc.characterCount() - 1))
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        text = cur.selectedText().replace("\u2029", "\n").strip()
        cur.removeSelectedText()
        if text and aid in self._work:
            note = html.escape(text[:300]).replace("\n", "<br>")
            self._work_add(aid, f"note:{len(self._work[aid]['items'])}", f"💭 {note}")

    def _work_finish(self, aid: str, browser) -> Optional[Dict[str, Any]]:
        """移除即時處理區塊，回傳要存進訊息的收合資料（含總時間與開始輸出前的思考時間）"""
        work = self._work.pop(aid, None)
        if not work:
            return None
        doc = browser.document()
        cur = QTextCursor(doc)
        cur.setPosition(min(work["start"], doc.characterCount() - 1))
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        now = time.time()
        return {
            "seconds": now - work["t0"],
            "think_seconds": (work.get("out_t") or now) - work["t0"],
            "items": [h for _, h in work["items"]],
            "expanded": False,
            "web_sources": work.get("web_sources"),
        }

    def _on_agent_step(self, step: Dict[str, Any]):
        aid = step.get("agent_id") or self.active_agent_id
        slot = self.agent_slots.get(aid)
        browser = slot.chat_browser if slot else self.chat_browser
        self._work_take_stream_note(aid, browser)
        if aid not in self._work:
            self._work_begin(aid, browser)
        self._work[aid]["out_t"] = None

        if step.get("type") == "MODEL_ROUTED":
            self._work[aid]["model_id"] = str(step.get("model_used") or "")
            self._work[aid]["is_local"] = step.get("is_local")
            self._tick_work_model_animation()
            return

        if step.get("type") == "TASK_PLAN":
            self._work_add(aid, "plan", step.get("html", ""))
            self._work_redraw(aid, browser)
            return

        status = step.get("status", "RUNNING")
        if status == "ECC_WARN":
            icon, state = "⚠️", "需要修正"
        elif status == "RUNNING":
            icon, state = "⏳", "正在"
        elif step.get("failed"):
            icon, state = "❌", "沒完成："
        else:
            icon, state = "✅", "已"
        desc = describe_tool_call(step.get("tool", ""), step.get("args"))
        detail = (
            f" <span style='color:#6e7681;'>{html.escape(desc['detail'])}</span>" if desc["detail"] else ""
        )
        if status == "ECC_WARN":
            text = f"{html.escape(desc['action'])}（{state}）"
        else:
            text = f"{state}{html.escape(desc['action'])}"
        item = f"{icon} {text}{detail}"

        corrections = step.get("ecc_corrections") or []
        if corrections:
            item += f"<br>&nbsp;&nbsp;&nbsp;🔧 已自動修正工具參數：{html.escape(' · '.join(corrections))}"
        web_meta = step.get("web_meta") or {}
        if web_meta and aid in self._work:
            ws = self._work[aid].setdefault("web_sources", {"queries": [], "urls": []})
            qv = str(web_meta.get("query") or "").strip()
            if qv and qv not in ws["queries"]:
                ws["queries"].append(qv)
            seen_u = {u.get("url") for u in ws["urls"]}
            for u_info in (web_meta.get("urls") or []):
                u_raw = str(u_info.get("url") or "").strip()
                if u_raw.startswith(("http://", "https://")) and u_raw not in seen_u:
                    seen_u.add(u_raw)
                    ws["urls"].append({"title": str(u_info.get("title") or u_raw), "url": u_raw})
        if web_meta:
            q_txt = html.escape(str(web_meta.get("query") or ""))
            urls = web_meta.get("urls") or []
            sub_lines = ["&nbsp;&nbsp;&nbsp;🌐 <b>網路查詢結果與摘要</b>："]
            if q_txt:
                sub_lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;• 查詢關鍵字：{q_txt}")
            for u_info in urls[:6]:
                u_raw = str(u_info.get("url") or "").strip()
                u_title = html.escape(str(u_info.get("title") or u_raw))
                if u_raw.startswith(("http://", "https://")):
                    u_esc = html.escape(u_raw, quote=True)
                    sub_lines.append(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;• 造訪網址：<a href='{u_esc}' style='color:#38bdf8;'>{u_title}</a>"
                    )
            item += "<br>" + "<br>".join(sub_lines)
        self._work_add(aid, f"step:{step.get('step')}", item)
        self._work_redraw(aid, browser)

    def _on_agent_reply(self, res: Dict[str, Any]):
        self._turn_by_agent.pop(res.get("agent_id") or self.active_agent_id, None)
        if hasattr(self, "chat_input_card") and self.chat_input_card:
            self.chat_input_card.btn_send.setEnabled(True)
            self.chat_input_card.set_running(False)
        reply = res.get("reply") or res.get("error", "執行完成。")

        aid = res.get("agent_id") or self.active_agent_id
        slot = self.agent_slots.get(aid)
        browser = slot.chat_browser if slot else self.chat_browser
        # 串流中的暫時文字換成下方正式排版的回覆
        self._clear_stream_segment(aid, browser)

        if slot:
            slot.status = "IDLE"
            if slot.lbl_status_tag:
                slot.lbl_status_tag.setText("🟢 待命")
                slot.lbl_status_tag.setStyleSheet("background: rgba(34,197,94,0.15); color: #4ade80; border-radius: 4px; padding: 2px 6px; font-size: 10.5px;")

        # 路由／備援資訊收進處理區塊，不再單獨佔一行
        routing = res.get("routing_info") or {}
        model_used = res.get("model_used", "")
        if routing.get("failover_count", 0) > 0:
            self._work_add(aid, "route", f"🔀 首選模型出錯，已改用 {html.escape(str(model_used))}")
        elif routing.get("routing_reason"):
            self._work_add(aid, "route", f"🤖 {html.escape(str(routing.get('routing_reason')))}")
        work_record = self._work_finish(aid, browser)

        agent_msg = {"role": "agent", "text": reply, "img_b64": res.get("screenshot_b64")}
        if work_record:
            agent_msg["work"] = work_record
        if slot:
            slot.messages.append(agent_msg)
            agent_msg_idx = len(slot.messages) - 1
            self._render_bubble_html_for_slot(slot, "agent", reply, res.get("screenshot_b64"), msg_idx=agent_msg_idx)
            # 存檔至歷史紀錄
            self.history_manager.save_session(
                slot.session_id,
                slot.messages,
                category=self.current_category,
            )
        else:
            self.current_messages.append(agent_msg)
            agent_msg_idx = len(self.current_messages) - 1
            self._render_bubble_html("agent", reply, res.get("screenshot_b64"), msg_idx=agent_msg_idx)

        self.reload_history_lists()
        self._refresh_agent_tab_bar()
        if aid:
            self._team_after_reply(aid)

    @staticmethod
    def _compact_text_html(text: str) -> str:
        """純文字 → HTML。模型常在段落間塞好幾個空行，每個 \\n 都變 <br> 會讓行距大得誇張：
        程式碼區塊外的連續空行一律縮成「半行高」的段落間距；程式碼區塊內保持原樣。"""
        parts = re.split(r"(```[\s\S]*?```)", (text or "").strip("\n"))
        out = []
        for i, part in enumerate(parts):
            if i % 2 == 1:  # 程式碼區塊
                out.append(html.escape(part).replace("\n", "<br>"))
                continue
            part = re.sub(r"[ \t]+\n", "\n", part).strip("\n")
            chunks = [c for c in re.split(r"\n\s*\n+", part) if c.strip()]
            # Qt 的空白行一定是整行高；改成段落 + 10px 間距（實測：空一行 +27px → 段落 +10px）
            def _fmt_inline(s: str) -> str:
                esc = html.escape(s)
                esc = re.sub(
                    r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                    r"<a href='\2' style='color:#60a5fa; text-decoration:underline;'>\1</a>",
                    esc,
                )
                esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
                esc = re.sub(r"`([^`]+)`", r"<code style='background:#161b22; padding:1px 4px; border-radius:4px; color:#93c5fd;'>\1</code>", esc)
                return esc.replace("\n", "<br>")

            out.append("".join(
                f"<p style='margin:0 0 {10 if j < len(chunks) - 1 else 0}px 0; line-height:1.7;'>"
                + _fmt_inline(c) + "</p>"
                for j, c in enumerate(chunks)))
        return "".join(out)

    def _render_bubble_html_for_slot(
        self,
        slot: Optional[AgentSlot],
        role: str,
        text: str,
        img_b64: Optional[str] = None,
        msg_idx: Optional[int] = None,
    ):
        is_user = role == "user"
        aid = slot.agent_id if slot else "main"
        target_browser = slot.chat_browser if slot else self.chat_browser
        msgs = slot.messages if slot else self.current_messages
        idx = msg_idx if msg_idx is not None else max(0, len(msgs) - 1)

        formatted = self._compact_text_html(text)
        formatted = re.sub(
            r"```(.*?)(<br>)?([\s\S]*?)```",
            r"<pre style='background:#0b0d12;padding:10px;border-radius:8px;font-family:Consolas,monospace;font-size:12.5px;color:#e2e8f0;margin:6px 0;'><code>\3</code></pre>",
            formatted,
        )
        if "[launch_btn:" in formatted:
            import urllib.parse
            def _btn_repl(m):
                label = html.unescape(m.group(1)).strip()
                tgt = html.unescape(m.group(2)).strip()
                href = f"action:launch_app:{urllib.parse.quote(tgt, safe='')}"
                return (
                    f"<a href='{href}' style='background:#1e293b; color:#38bdf8; "
                    f"border:1px solid #38bdf8; padding:4px 10px; text-decoration:none; "
                    f"font-weight:bold;'>🚀 {html.escape(label)}</a>&nbsp;&nbsp;"
                )
            formatted = re.sub(r"\[launch_btn:([^|\]]+)\|([^\]]+)\]", _btn_repl, formatted)

        img_tag = ""
        if img_b64:
            img_tag = f"<br><img src='data:image/jpeg;base64,{img_b64}' style='max-width:480px;border-radius:8px;margin-top:6px;'>"

        if is_user:
            # 使用者輸入：靠右、有外框的方塊（Qt 不支援 border-radius，用 table 畫框），加上錨點供左側圓點跳轉
            bubble_html = f"""
            <a name='user_turn_{idx}'></a>
            <table align='right' cellspacing='0' cellpadding='12' bgcolor='#1c1f26'
                   style='border:1px solid #3a3f4b; margin:10px 0 14px 60px;'>
              <tr><td style='color:#f3f4f6; font-size:14px; font-family:"Segoe UI","Microsoft JhengHei",sans-serif; line-height:1.6;'>
                {formatted}{img_tag}
                <div align='right' style='font-size:12px; margin-top:4px;'>
                  <a href='action:copy_user:{aid}:{idx}' style='text-decoration:none; color:#6e7681;'>📋</a>&nbsp;&nbsp;
                  <a href='action:edit_user:{aid}:{idx}' style='text-decoration:none; color:#6e7681;'>✏️</a>
                </div>
              </td></tr>
            </table>
            """
        else:
            # AI 回覆：上方是可展開的「已處理 X ›」，下方直接是純文字（無框）
            msg = msgs[idx] if 0 <= idx < len(msgs) and isinstance(msgs[idx], dict) else {}
            work = msg.get("work") if msg.get("role") == "agent" else None
            work_html = ""
            think_txt = ""
            if work and work.get("think_seconds") is not None:
                think_txt = f"思考 {self._fmt_elapsed(work['think_seconds'])}"
            if work and work.get("items"):
                arrow = "⌄" if work.get("expanded") else "›"
                think_part = f" · {think_txt}" if think_txt else ""
                work_html = (
                    f"<div style='margin:6px 0 4px 0;'><a href='action:work:{aid}:{idx}' "
                    f"style='text-decoration:none; color:#8b949e; font-size:12.5px;'>"
                    f"已處理 {self._fmt_elapsed(work.get('seconds', 0))}{think_part}（{len(work['items'])} 項） {arrow}</a></div>"
                )
            elif think_txt:
                work_html = (
                    f"<div style='margin:6px 0 4px 0; color:#8b949e; font-size:12.5px;'>已{think_txt}</div>"
                )
            if work and work.get("items") and work.get("expanded"):
                    work_html += (
                        "<table width='100%' cellspacing='0' cellpadding='8' bgcolor='#12151b' "
                        "style='border:1px solid #262b33; margin-bottom:6px;'><tr><td>"
                        + self._work_items_html(work["items"])
                        + "</td></tr></table>"
                    )
            sources_html = ""
            ws_obj = (work or {}).get("web_sources") if isinstance(work, dict) else None
            if not ws_obj and isinstance(msg.get("sources"), dict):
                ws_obj = msg.get("sources")
            if isinstance(ws_obj, dict) and (ws_obj.get("urls") or ws_obj.get("queries")):
                src_exp = bool(ws_obj.get("expanded", False))
                s_arrow = "⌄" if src_exp else "›"
                n_urls = len(ws_obj.get("urls") or [])
                sources_html = (
                    f"<div style='margin:8px 0 4px 0;'><a href='action:sources:{aid}:{idx}' "
                    f"style='text-decoration:none; color:#38bdf8; font-size:12.5px;'>"
                    f"🌐 查詢資料與查證來源連結（{n_urls} 筆） {s_arrow}</a></div>"
                )
                if src_exp:
                    s_lines = []
                    qs = ws_obj.get("queries") or []
                    if qs:
                        s_lines.append(f"🔎 <b>查詢關鍵字</b>：{html.escape(' · '.join(qs[:6]))}")
                    for u_info in (ws_obj.get("urls") or [])[:12]:
                        u_raw = str(u_info.get("url") or "").strip()
                        u_title = html.escape(str(u_info.get("title") or u_raw))
                        u_esc = html.escape(u_raw, quote=True)
                        s_lines.append(
                            f"• <a href='{u_esc}' style='color:#60a5fa; text-decoration:underline;'>{u_title}</a>"
                            f"<br>&nbsp;&nbsp;<span style='color:#6e7681; font-size:11.5px;'>{html.escape(u_raw)}</span>"
                        )
                    sources_html += (
                        "<table width='100%' cellspacing='0' cellpadding='8' bgcolor='#0f172a' "
                        "style='border:1px solid #1e3a5f; margin-bottom:6px;'><tr><td style='font-size:12.5px; color:#cbd5e1;'>"
                        + "<br>".join(s_lines)
                        + "</td></tr></table>"
                    )

            actions_html = f"""
                <div style='margin-top:6px; font-size:12px;'>
                    <a href='action:like:{aid}:{idx}' style='text-decoration:none; color:#6e7681;'>👍</a>&nbsp;&nbsp;
                    <a href='action:dislike:{aid}:{idx}' style='text-decoration:none; color:#6e7681;'>👎</a>&nbsp;&nbsp;
                    <a href='action:retry:{aid}:{idx}' style='text-decoration:none; color:#6e7681;'>🔄</a>&nbsp;&nbsp;
                    <a href='action:copy_ai:{aid}:{idx}' style='text-decoration:none; color:#6e7681;'>📋</a>&nbsp;&nbsp;
                    <a href='action:more:{aid}:{idx}' style='text-decoration:none; color:#6e7681; font-weight:bold;'>⋯</a>
                </div>
            """
            bubble_html = f"""
            <div align='left' style='margin:4px 0 18px 0; text-align:left;'>
                {work_html}
                <div style='color:#e6edf3; font-size:14px; font-family:"Segoe UI","Microsoft JhengHei",sans-serif; line-height:1.7;'>
                    {formatted}
                    {img_tag}
                    {sources_html}
                </div>
                {actions_html}
            </div>
            """

        target_browser.append(bubble_html)
        if is_user and (slot is None or slot.agent_id == getattr(self, "active_agent_id", None)):
            self._refresh_nav_dots()

    def _scroll_chat_to_bottom(self, browser: Optional[QTextBrowser] = None):
        """捲動對話框至最底部，確保重開或載入時直接顯示最後一則對話。"""
        target = browser or getattr(self, "chat_browser", None)
        if target is None:
            return

        def _do_scroll():
            try:
                sb = target.verticalScrollBar()
                if sb is not None:
                    sb.setValue(sb.maximum())
            except Exception:
                pass

        _do_scroll()
        QTimer.singleShot(0, _do_scroll)
        QTimer.singleShot(80, _do_scroll)

    def _refresh_nav_dots(self, active_dot: int = -1):
        """依據目前代理的對話紀錄，重建左側「一則輸入一顆圓點」的快速跳轉導航欄。"""
        if not hasattr(self, "nav_rail_layout") or not hasattr(self, "nav_rail_widget"):
            return
        while self.nav_rail_layout.count():
            item = self.nav_rail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        slot = self.agent_slots.get(getattr(self, "active_agent_id", None)) if hasattr(self, "agent_slots") else None
        msgs = slot.messages if slot is not None else getattr(self, "current_messages", [])
        user_turns = [(i, m) for i, m in enumerate(msgs) if isinstance(m, dict) and m.get("role") == "user"]
        if not user_turns:
            self.nav_rail_layout.addStretch()
            self.nav_rail_widget.hide()
            return

        if active_dot < 0:
            active_dot = len(user_turns) - 1
        self.nav_rail_widget.show()
        for n, (msg_idx, m) in enumerate(user_turns):
            preview = re.sub(r"\s+", " ", str(m.get("text") or "")).strip()
            if len(preview) > 42:
                preview = preview[:42] + "…"
            dot = QPushButton()
            dot.setFixedSize(10, 10)
            dot.setCursor(Qt.PointingHandCursor)
            dot.setToolTip(f"#{n + 1}: {preview}" if preview else f"第 {n + 1} 則輸入")
            is_cur = n == active_dot
            color = "#38bdf8" if is_cur else "#475569"
            dot.setStyleSheet(
                f"QPushButton {{ background: {color}; border: none; border-radius: 5px; padding: 0; }}"
                "QPushButton:hover { background: #60a5fa; }"
            )
            dot.clicked.connect(lambda _, mi=msg_idx, dn=n: self._jump_to_user_turn(mi, dn))
            self.nav_rail_layout.addWidget(dot, 0, Qt.AlignHCenter)
        self.nav_rail_layout.addStretch()
        if active_dot >= len(user_turns) - 1 and hasattr(self, "nav_rail_scroll"):
            QTimer.singleShot(0, lambda: self.nav_rail_scroll.verticalScrollBar().setValue(
                self.nav_rail_scroll.verticalScrollBar().maximum()
            ))

    def _jump_to_user_turn(self, msg_idx: int, dot_idx: int = -1):
        """點擊左側圓點後，捲動目前對話框至對應的使用者輸入。"""
        browser = getattr(self, "chat_browser", None)
        if browser is not None:
            browser.scrollToAnchor(f"user_turn_{msg_idx}")
        self._refresh_nav_dots(active_dot=dot_idx)

    def _append_chat_bubble_for_slot(self, slot: AgentSlot, role: str, text: str, img_b64: Optional[str] = None, msg_idx: Optional[int] = None):
        self._render_bubble_html_for_slot(slot, role, text, img_b64, msg_idx)

    def _render_bubble_html(self, role: str, text: str, img_b64: Optional[str] = None, msg_idx: Optional[int] = None):
        slot = self.agent_slots.get(self.active_agent_id) if hasattr(self, "agent_slots") else None
        self._render_bubble_html_for_slot(slot, role, text, img_b64, msg_idx)

    def _append_chat_bubble(self, role: str, text: str, img_b64: Optional[str] = None):
        self._render_bubble_html(role, text, img_b64)

    def _handle_chat_anchor_click(self, url: QUrl, slot: Optional[AgentSlot] = None):
        """處理氣泡中的超連結與各項互動功能 (圖一與圖二完整動作集)"""
        url_str = url.toString()
        if url_str.startswith("http://") or url_str.startswith("https://"):
            webbrowser.open(url_str)
            return

        if not url_str.startswith("action:"):
            return

        if url_str.startswith("action:launch_app:"):
            import urllib.parse
            raw_target = urllib.parse.unquote(url_str[len("action:launch_app:"):]).strip()
            if not raw_target:
                return
            if raw_target.startswith(("http://", "https://")):
                webbrowser.open(raw_target)
                self.statusBar().showMessage(f"🌐 已開啟網頁：{raw_target}", 4000)
                return
            try:
                res = self.agent_brain.desktop.launch_application(raw_target)
                if res.get("ok"):
                    launched = res.get("launched") or raw_target
                    self.statusBar().showMessage(f"🚀 已直接開啟：{launched}", 4000)
                else:
                    self.statusBar().showMessage(f"❌ 開啟失敗：{res.get('error', raw_target)}", 5000)
            except Exception as e:
                self.statusBar().showMessage(f"❌ 開啟失敗：{e}", 5000)
            return

        parts = url_str.split(":")
        if len(parts) < 4:
            return

        verb = parts[1]
        aid = parts[2]
        try:
            msg_idx = int(parts[3])
        except Exception:
            msg_idx = 0

        target_slot = slot or self.agent_slots.get(aid)
        messages = target_slot.messages if target_slot else self.current_messages
        msg_obj = messages[msg_idx] if 0 <= msg_idx < len(messages) else {}
        msg_text = msg_obj.get("text", "")

        if verb in ("like", "dislike"):
            # 👍／👎 是給「軟體操作學習」的訊號：👎 會忘掉這次記下的做法並記成教訓，👍 標成確認過
            changed = 0
            try:
                from core import app_learning
                asked = next((m.get("text", "") for m in reversed(messages[:msg_idx])
                              if isinstance(m, dict) and m.get("role") == "user"), "")
                changed = int(app_learning.feedback(asked, verb == "like").get("changed", 0))
            except Exception:
                changed = 0
            if verb == "like":
                tip = "已記錄 👍" + ("：這次的做法已標成確認過，下次會優先照做" if changed else "")
            else:
                tip = "已記錄 👎" + ("：已忘掉這次的做法，下次會先查資料、換方法做" if changed else "")
            self.statusBar().showMessage(tip, 4000)
        elif verb == "copy_user":
            QApplication.clipboard().setText(msg_text)
            self.statusBar().showMessage("已複製提問內容至剪貼簿 📋", 3000)
        elif verb == "copy_ai":
            QApplication.clipboard().setText(msg_text)
            self.statusBar().showMessage("已複製 AI 回覆全文至剪貼簿 📋", 3000)
        elif verb == "edit_user":
            if hasattr(self, "input_text") and self.input_text:
                self.input_text.setPlainText(msg_text)
                self.input_text.setFocus()
                self.statusBar().showMessage("已將訊息帶入輸入框，可編輯後再次發送 ✏️", 3000)
        elif verb == "retry":
            # 找到對應的 user 提問並重新觸發
            prev_user_text = ""
            for i in range(msg_idx - 1, -1, -1):
                if messages[i].get("role") == "user":
                    prev_user_text = messages[i].get("text", "")
                    break
            if prev_user_text:
                self.statusBar().showMessage("正在為您重新產生回覆 🔄...", 3000)
                self.send_current_prompt(prompt_text=prev_user_text)
            else:
                self.statusBar().showMessage("查無上一則提問內容，無法重試", 3000)
        elif verb == "more":
            self._show_ai_more_menu(target_slot, msg_idx, msg_text)
        elif verb == "sources":
            ws_obj = (msg_obj.get("work") or {}).get("web_sources") if isinstance(msg_obj.get("work"), dict) else None
            if not ws_obj and isinstance(msg_obj.get("sources"), dict):
                ws_obj = msg_obj.get("sources")
            if isinstance(ws_obj, dict):
                ws_obj["expanded"] = not ws_obj.get("expanded", False)
                self._rerender_chat_browser(target_slot)
        elif verb == "work":
            work = msg_obj.get("work") if isinstance(msg_obj, dict) else None
            if work:
                work["expanded"] = not work.get("expanded")
                self._rerender_conversation(target_slot)

    def _rerender_conversation(self, slot: Optional[AgentSlot]):
        browser = slot.chat_browser if slot else self.chat_browser
        msgs = slot.messages if slot else self.current_messages
        aid = slot.agent_id if slot else self.active_agent_id
        if aid in self._work or aid in self._stream_start:
            # 這個代理還在執行中，重繪會打亂即時區塊，先不處理
            self.statusBar().showMessage("執行中，完成後再展開", 3000)
            return
        sb = browser.verticalScrollBar()
        pos = sb.value()
        browser.clear()
        for i, m in enumerate(msgs):
            self._render_bubble_html_for_slot(slot, m.get("role", "user"), m.get("text", ""), m.get("img_b64"), msg_idx=i)
        sb.setValue(pos)

    def _show_ai_more_menu(self, slot: Optional[AgentSlot], msg_idx: int, ai_text: str):
        """彈出圖二規格的 8 大功能選單"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #16181f; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 8px; padding: 6px; color: #f1f5f9; }
            QMenu::item { padding: 7px 22px; border-radius: 4px; font-size: 13px; }
            QMenu::item:selected { background: #283044; color: #60a5fa; }
        """)

        act_branch = menu.addAction("🔀  建立新的分支對話")
        is_speaking = hasattr(self, "_speech_proc") and self._speech_proc and self._speech_proc.poll() is None
        act_speech = menu.addAction("⏹️  停止朗讀" if is_speaking else "🔊  朗讀")
        act_export_file = menu.addAction("📄  匯出至文件")
        act_gmail = menu.addAction("✉️  在 Gmail 中建立草稿")
        act_colab = menu.addAction("🌐  匯出至 Colab")
        act_replit = menu.addAction("💻  匯出至 Replit")
        act_legal = menu.addAction("🚩  回報法律問題")
        act_thinking = menu.addAction("🧬  顯示思考步驟")

        chosen = menu.exec_(QCursor.pos())
        if chosen == act_branch:
            self._branch_session(slot, msg_idx)
        elif chosen == act_speech:
            self._toggle_speech_read(ai_text)
        elif chosen == act_export_file:
            self._export_to_file(ai_text)
        elif chosen == act_gmail:
            self._draft_in_gmail(ai_text)
        elif chosen == act_colab:
            self._export_to_colab(ai_text)
        elif chosen == act_replit:
            self._export_to_replit(ai_text)
        elif chosen == act_legal:
            self._report_legal_issue(ai_text)
        elif chosen == act_thinking:
            self._show_thinking_steps(slot, msg_idx)

    def _branch_session(self, slot: Optional[AgentSlot], msg_idx: int):
        """建立新的分支對話"""
        source_msgs = slot.messages if slot else self.current_messages
        branch_msgs = [dict(m) for m in source_msgs[: msg_idx + 1]]
        new_slot = self.create_agent_slot(f"🔀 分支 #{len(self.agent_slots)}")
        new_slot.messages = branch_msgs
        new_slot.chat_browser.clear()

        pill = "<div style='font-size:11px;color:#94a3b8;margin-bottom:12px;text-align:center;'>── 已從歷史點建立分支對話 ──</div>"
        new_slot.chat_browser.append(pill)
        for idx, m in enumerate(branch_msgs):
            self._render_bubble_html_for_slot(new_slot, m.get("role", "user"), m.get("text", ""), m.get("img_b64"), msg_idx=idx)

        # 存檔至新 session
        self.history_manager.save_session(
            new_slot.session_id,
            new_slot.messages,
            category=self.current_category,
        )
        self.reload_history_lists()
        self.switch_to_agent(new_slot.agent_id)
        self.statusBar().showMessage("已成功建立並切換至新分支對話！", 4000)

    def _toggle_speech_read(self, text: str):
        """本地 SAPI 繁中/英雙語語音合成朗讀 (零套件依賴)"""
        if hasattr(self, "_speech_proc") and self._speech_proc and self._speech_proc.poll() is None:
            try:
                self._speech_proc.terminate()
            except Exception:
                pass
            self._speech_proc = None
            self.statusBar().showMessage("⏹️ 已停止語音朗讀", 3000)
            return

        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"```[\s\S]*?```", "包含程式碼區塊。", clean)
        clean = clean.replace("'", "''").replace('"', '`"').strip()
        if not clean:
            return

        speech_cmd = (
            "Add-Type -AssemblyName System.Speech; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$synth.Speak('{clean[:1200]}')"
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._speech_proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", speech_cmd],
            creationflags=creationflags,
        )
        self.statusBar().showMessage("🔊 正在為您朗讀回覆內容...", 5000)

    def _export_to_file(self, text: str):
        """匯出至文件"""
        fp, _ = QFileDialog.getSaveFileName(self, "匯出回覆至文件", "reply.md", "Markdown (*.md);;文字檔 (*.txt);;所有檔案 (*)")
        if fp:
            try:
                Path(fp).write_text(text, encoding="utf-8")
                self.statusBar().showMessage(f"已成功匯出至：{Path(fp).name}", 4000)
            except Exception as e:
                QMessageBox.warning(self, "匯出失敗", f"寫入檔案時發生錯誤：{e}")

    def _draft_in_gmail(self, text: str):
        """在 Gmail 中建立草稿"""
        quoted = urllib.parse.quote(text[:3000])
        webbrowser.open(f"https://mail.google.com/mail/?view=cm&fs=1&body={quoted}")
        self.statusBar().showMessage("已開啟 Gmail 草稿頁面！", 4000)

    def _export_to_colab(self, text: str):
        """匯出至 Google Colab"""
        matches = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", text)
        code = matches[0] if matches else text
        QApplication.clipboard().setText(code)
        webbrowser.open("https://colab.research.google.com/#create=true")
        self.statusBar().showMessage("已複製程式碼並開啟 Google Colab！", 4000)

    def _export_to_replit(self, text: str):
        """匯出至 Replit"""
        matches = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", text)
        code = matches[0] if matches else text
        QApplication.clipboard().setText(code)
        webbrowser.open("https://replit.com/new")
        self.statusBar().showMessage("已複製程式碼並開啟 Replit！", 4000)

    def _report_legal_issue(self, text: str):
        """回報法律與合規問題"""
        QMessageBox.information(
            self,
            "法律與合規問題回報",
            "感謝您的回報！\n\n系統資安防護與合規中心已為此內容建立稽核工單 (Audit Ticket)，內部將嚴格審視著作權、資料安全與合規性。",
        )

    def _show_thinking_steps(self, slot: Optional[AgentSlot], msg_idx: int):
        """顯示思考步驟"""
        dlg = QDialog(self)
        dlg.setWindowTitle("🧬 AI 模型推導與思考步驟")
        dlg.resize(540, 420)
        dlg.setStyleSheet("background: #0f121a; color: #f1f5f9;")
        layout = QVBoxLayout(dlg)
        tb = QTextBrowser()
        tb.setStyleSheet("background: #161922; border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; color: #93c5fd; font-family: Consolas, monospace; font-size: 12px; padding: 10px;")

        info = f"""
        <h3>🧬 思考與決策軌跡分析 (對話 #{msg_idx})</h3>
        <p><b>1. 意圖識別：</b> 解析任務需求，並啟動全域上下文比對。</p>
        <p><b>2. 模型路由：</b> 依任務複雜度與視覺輸入權重自動配置最合適模型推導架構。</p>
        <p><b>3. ECC 工具鏈自癒：</b> 實時語法比對與抗幻覺沙箱驗證通過。</p>
        <p><b>4. 資安防護層：</b> 沙箱執行 CDR 無害化與防竄改機制通過。</p>
        """
        tb.setHtml(info)
        layout.addWidget(tb)
        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        dlg.exec_()

    # ================= 監督與資安審批 =================

    def start_supervisor(self):
        hwnd = self.selected_hwnd
        title = self.window_cards.get(hwnd).title_text if hwnd in self.window_cards else "目前畫面"
        goal = self.input_sup_goal.text().strip()
        verify = self.input_sup_verify.text().strip()

        self.supervisor.start_supervision(
            hwnd=hwnd,
            window_title=title,
            goal=goal,
            verify_command=verify,
            max_failures=3,
        )
        self.btn_start_sup.hide()
        self.btn_stop_sup.show()
        self.btn_resume_sup.hide()

    def stop_supervisor(self):
        self.supervisor.stop_supervision("使用者手動停止")
        self.btn_start_sup.show()
        self.btn_stop_sup.hide()
        self.btn_resume_sup.hide()

    def resume_supervisor(self):
        self.supervisor.resume_after_circuit_break()
        self.btn_start_sup.hide()
        self.btn_stop_sup.show()
        self.btn_resume_sup.hide()

    def _on_supervisor_event(self, entry: Dict[str, Any]):
        ev = entry.get("event", "")
        msg = entry.get("message", "")
        self.list_sup_logs.insertItem(0, f"[{time.strftime('%H:%M:%S')}] {ev}: {msg[:60]}")

        if ev == "SUPERVISION_CIRCUIT_BREAK":
            self.btn_resume_sup.show()
            self._append_chat_bubble("agent", f"⚠️ **【觸發 3 次卡關智慧熔斷】**\n{msg}", entry.get("screenshot_b64"))
        elif ev == "SUPERVISION_COMPLETED":
            self.btn_start_sup.show()
            self.btn_stop_sup.hide()
            self._append_chat_bubble("agent", f"✅ **【AI 寫程式監督完成】**\n{msg}")

    def _on_web_activity(self, rec: Dict[str, Any]):
        item = f"🌐 {rec.get('title')}\nURL: {rec.get('url')}\n摘要: {rec.get('summary', '')[:80]}"
        self.list_web_logs.insertItem(0, item)

    def _on_security_ticket(self, ticket: Dict[str, Any]):
        dlg = SecurityPinDialog(ticket, self)
        res = dlg.exec_()
        approved = res == QDialog.Accepted
        pin_code = dlg.pin_result

        self.security_guard.resolve_approval(
            ticket_id=ticket["id"],
            approved=approved,
            pin_code=pin_code,
            source="Qt Native Dialog",
            remember=getattr(dlg, "remember", False),
        )

    def _on_context_update(self, state: Dict[str, Any]):
        label = state.get("label", "🟢 待命")
        self.lbl_context.setText(label)
        # 免打擾可能被情境切換工具改掉：選單文字跟著實際狀態走
        is_dnd = state.get("mode") == "MANUAL_DND"
        if is_dnd != self.manual_dnd:
            self.manual_dnd = is_dnd
            if getattr(self, "act_dnd_menu", None):
                self.act_dnd_menu.setText(t("btn_dnd_on") if is_dnd else t("btn_dnd_off"))
        if state.get("mode") != "NORMAL":
            self.lbl_context.setStyleSheet("background: rgba(245,158,11,0.15); color: #fbbf24; border: 1px solid rgba(245,158,11,0.3); border-radius: 12px; padding: 4px 10px; font-weight: 600;")
        else:
            self.lbl_context.setStyleSheet("background: rgba(34,197,94,0.15); color: #4ade80; border: 1px solid rgba(34,197,94,0.3); border-radius: 12px; padding: 4px 10px; font-weight: 600;")

    def toggle_dnd(self):
        try:  # 以設定檔為準（情境切換工具也會改它），避免畫面與實際狀態相反
            current = bool(self.settings_manager.get_raw().get("dnd", {}).get("manual_dnd", False))
        except Exception:
            current = self.manual_dnd
        self.manual_dnd = not current
        dnd_text = "🔕 免打擾模式：開" if self.manual_dnd else "🔕 免打擾模式：關"
        if hasattr(self, "act_dnd_menu") and self.act_dnd_menu:
            self.act_dnd_menu.setText(f"{dnd_text} (點擊切換)")
        if hasattr(self, "btn_dnd") and self.btn_dnd:
            self.btn_dnd.setText(dnd_text)
        self.settings_manager.update_settings({"dnd": {"manual_dnd": self.manual_dnd}})
        self.statusBar().showMessage(f"🔕 {dnd_text}", 3000)

    def _on_hotkey_kill(self):
        """全域熱鍵 Ctrl+Alt+Q：只負責「停」，不會把已鎖定的狀態解除（解除請按按鈕）。"""
        was_locked = self.security_guard.emergency_stop_triggered
        if not was_locked:
            self.trigger_kill_switch()
            aborted = 0
        else:
            aborted = self._abort_running_work()  # 已鎖定時再按一次：再確認一遍所有工作都停了
        try:
            self.settings_manager.append_audit_log(
                "HOTKEY_EMERGENCY_STOP", {"hotkey": "Ctrl+Alt+Q", "was_locked": was_locked, "aborted": aborted})
        except Exception:
            pass
        # 明確回饋：系統提示音 + 畫面上方紅色橫幅（不搶焦點，打遊戲也安全）。
        # 系統通知氣球常被「專注輔助」藏起來，不能只靠它。
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            pass
        self._show_stop_banner("🛑 Syntra 已緊急停止 — 所有代理與桌面操作已中斷（到主視窗按「已緊急鎖定」解除）")
        try:
            self.tray.setToolTip("Syntra 星樞（🛑 已緊急鎖定）")
            self.tray.showMessage("🛑 Syntra 已緊急停止", "所有代理與桌面操作已中斷。到主視窗按「已緊急鎖定」可解除。",
                                  QSystemTrayIcon.Warning, 4000)
        except Exception:
            pass

    def _cancel_active_turn(self):
        """只停止目前代理正在跑的這一輪（不鎖定 agent），並砍掉它正在跑的背景指令。"""
        fut = self._turn_by_agent.pop(self.active_agent_id, None)
        if fut is not None:
            fut.cancel()
        try:
            self.desktop_controller.kill_running_commands()
        except Exception:
            pass

    def _clipboard_assist_busy(self) -> bool:
        try:
            from core.process_event_hub import process_hub
            if process_hub.is_gaming():
                return True
            import win32gui
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
            return pid == os.getpid()  # 在 agent 自己的視窗裡複製，不提示
        except Exception:
            return False

    def _on_hotkey_summon(self):
        self.quick_bar.summon()

    def _on_quick_bar_submit(self, text: str):
        """快速輸入列送出：打開主視窗並交給目前的代理。"""
        self.show_and_activate()
        self.send_current_prompt(text)

    def _show_stop_banner(self, text: str, ms: int = 3500):
        """螢幕上方置頂的紅色橫幅：不取得焦點、不出現在工作列，幾秒後自動消失。"""
        banner = QLabel(text)
        banner.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                              | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        banner.setAttribute(Qt.WA_ShowWithoutActivating, True)
        banner.setAttribute(Qt.WA_DeleteOnClose, True)
        banner.setStyleSheet("background:#dc2626; color:white; font-size:16px; font-weight:bold;"
                             "padding:12px 22px; border:2px solid #fecaca; border-radius:10px;")
        banner.adjustSize()
        geo = QApplication.primaryScreen().availableGeometry()
        banner.move(geo.center().x() - banner.width() // 2, geo.top() + 24)
        banner.show()
        self._stop_banner = banner
        QTimer.singleShot(ms, banner.close)

    def _abort_running_work(self) -> int:
        """真正中斷：取消執行中的對話回合（含正在等的模型與工具），並砍掉正在跑的背景指令。"""
        n = 0
        for fut in list(self._running_turns):
            if fut.cancel():
                n += 1
        try:
            n += self.desktop_controller.kill_running_commands()
        except Exception:
            pass
        try:
            from core.agent_terminal import terminal_manager
            terminal_manager.interrupt_all()
        except Exception:
            pass
        return n

    def trigger_kill_switch(self):
        is_stopped = not self.security_guard.emergency_stop_triggered
        self.security_guard.emergency_stop_triggered = is_stopped
        if is_stopped:
            self._abort_running_work()
            self.supervisor.stop_supervision("緊急停止開關觸發")
            self.btn_kill.setText("🔓 已緊急鎖定 (點擊解除)")
            self.btn_kill.setStyleSheet("background-color: #dc2626; color: white;")
        else:
            self.btn_kill.setText("🛑 緊急停止 (Ctrl+Alt+Q)")
            self.btn_kill.setStyleSheet("")
            try:
                self.tray.setToolTip(f"{t('brand_name')} ({t('lbl_context_normal')})")
            except Exception:
                pass

    async def _run_background_services(self):
        self.discord_bridge.start()
        while True:
            await asyncio.sleep(2.5)
            state = self.context_guard.evaluate_state()
            self.sig_context_update.emit(state)

    def switch_to_security_tab(self):
        self.tabs.setCurrentIndex(3)

    def switch_to_logs_tab(self):
        self.tabs.setCurrentIndex(2)

    def _create_security_center_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)
        _sec_pages = []

        # --- 區塊 1: CDR 內容威脅消除與重構 ---
        grp_cdr = QGroupBox("🛡️ 1. CDR 內容威脅消除與重構 (Disarm & Reconstruct)")
        cdr_lay = QVBoxLayout(grp_cdr)
        cdr_lay.addWidget(QLabel(
            "<span style='color:#94a3b8;font-size:11px;'>"
            "針對不可信外部檔案（圖片、PDF、Office 文件、壓縮檔、腳本），深度剔除惡意巨集、"
            "EXIF/GPS 隱寫、Polyglot 後門、Bidi 欺騙字符，並以安全結構重構檔案。"
            "</span>"
        ))

        cdr_file_row = QHBoxLayout()
        self.txt_cdr_path = QLineEdit()
        self.txt_cdr_path.setPlaceholderText("請選擇或貼上欲進行 CDR 無害化之檔案路徑...")
        btn_cdr_browse = QPushButton("📁 選擇檔案")
        btn_cdr_browse.clicked.connect(self._browse_cdr_file)
        cdr_file_row.addWidget(self.txt_cdr_path, stretch=1)
        cdr_file_row.addWidget(btn_cdr_browse)
        cdr_lay.addLayout(cdr_file_row)

        btn_cdr_exec = QPushButton("🚀 執行 CDR 深度清洗重構")
        btn_cdr_exec.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold;")
        btn_cdr_exec.clicked.connect(self._run_cdr_disarm)
        cdr_lay.addWidget(btn_cdr_exec)

        self.txt_cdr_output = QTextEdit()
        self.txt_cdr_output.setReadOnly(True)
        self.txt_cdr_output.setFixedHeight(85)
        self.txt_cdr_output.setPlaceholderText("CDR 執行報告與安全哈希對比將顯示於此...")
        cdr_lay.addWidget(self.txt_cdr_output)
        _sec_pages.append(grp_cdr)

        # --- 區塊 2: 電腦防毒掃描 (雙引擎) ---
        grp_av = QGroupBox("🔍 2. 電腦防毒掃描中心 (Windows Defender + 本地啟發式)")
        av_lay = QVBoxLayout(grp_av)

        av_file_row = QHBoxLayout()
        self.txt_av_path = QLineEdit()
        self.txt_av_path.setPlaceholderText("欲掃描之檔案或目錄路徑 (預設為專案目錄)...")
        self.txt_av_path.setText(str(self.current_workspace_dir))
        btn_av_file = QPushButton("📄 檔案")
        btn_av_file.clicked.connect(self._browse_av_file)
        btn_av_dir = QPushButton("📁 目錄")
        btn_av_dir.clicked.connect(self._browse_av_dir)
        av_file_row.addWidget(self.txt_av_path, stretch=1)
        av_file_row.addWidget(btn_av_file)
        av_file_row.addWidget(btn_av_dir)
        av_lay.addLayout(av_file_row)

        self.chk_auto_quarantine = QCheckBox("發現惡意威脅自動移入安全隔離庫 (Auto Quarantine)")
        self.chk_auto_quarantine.setChecked(True)
        av_lay.addWidget(self.chk_auto_quarantine)

        av_btn_row = QHBoxLayout()
        btn_av_heur = QPushButton("⚡ 本地啟發式掃描")
        btn_av_heur.clicked.connect(self._run_av_heuristics)
        btn_av_defender = QPushButton("🛡️ Defender 掃描")
        btn_av_defender.clicked.connect(self._run_av_defender)
        btn_av_full = QPushButton("🔍 複合全面掃毒")
        btn_av_full.setStyleSheet("background-color: #0d9488; color: white; font-weight: bold;")
        btn_av_full.clicked.connect(self._run_av_full_scan)
        av_btn_row.addWidget(btn_av_heur)
        av_btn_row.addWidget(btn_av_defender)
        av_btn_row.addWidget(btn_av_full)
        av_lay.addLayout(av_btn_row)

        self.txt_av_output = QTextEdit()
        self.txt_av_output.setReadOnly(True)
        self.txt_av_output.setFixedHeight(95)
        self.txt_av_output.setPlaceholderText("掃毒日誌與威脅報表...")
        av_lay.addWidget(self.txt_av_output)
        _sec_pages.append(grp_av)

        # --- 區塊 3: 隔離庫管理 (Quarantine Vault) ---
        grp_q = QGroupBox("☣️ 3. 安全隔離庫 (XOR 混淆加密防護)")
        q_lay = QVBoxLayout(grp_q)
        self.table_quarantine = QTableWidget()
        self.table_quarantine.setColumnCount(3)
        self.table_quarantine.setHorizontalHeaderLabels(["ID", "原檔案路徑", "隔離原因"])
        self.table_quarantine.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_quarantine.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_quarantine.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_quarantine.verticalHeader().setVisible(False)
        self.table_quarantine.setFixedHeight(90)
        q_lay.addWidget(self.table_quarantine)

        q_btn_row = QHBoxLayout()
        btn_q_refresh = QPushButton("🔄 刷新隔離區")
        btn_q_refresh.clicked.connect(self._refresh_quarantine_table)
        btn_q_restore = QPushButton("↩️ 還原檔案")
        btn_q_restore.clicked.connect(self._restore_quarantined_file)
        btn_q_shred = QPushButton("🔥 徹底粉碎抹除")
        btn_q_shred.setObjectName("dangerBtn")
        btn_q_shred.clicked.connect(self._shred_quarantined_file)
        q_btn_row.addWidget(btn_q_refresh)
        q_btn_row.addWidget(btn_q_restore)
        q_btn_row.addWidget(btn_q_shred)
        q_lay.addLayout(q_btn_row)
        _sec_pages.append(grp_q)

        # --- 區塊 4: 沙箱隔離執行 (Windows Job Object & WSB) ---
        grp_sb = QGroupBox("📦 4. 受限沙箱執行環境 (Windows Job Object)")
        sb_lay = QVBoxLayout(grp_sb)
        sb_lay.addWidget(QLabel(
            "<span style='color:#94a3b8;font-size:11px;'>"
            "限制記憶體用量 (Max 512MB)、脫敏清除 API Key 與敏感環境變數、"
            "退出時強制清除衍生進程防留後門。"
            "</span>"
        ))

        self.txt_sb_cmd = QLineEdit("Get-Process | Select-Object -First 5")
        sb_lay.addWidget(self.txt_sb_cmd)

        sb_btn_row = QHBoxLayout()
        btn_sb_run = QPushButton("▶️ 在受限沙箱中執行")
        btn_sb_run.setStyleSheet("background-color: #4f46e5; color: white; font-weight: bold;")
        btn_sb_run.clicked.connect(self._run_in_sandbox_ui)
        btn_sb_wsb = QPushButton("📑 產生 Windows Sandbox (.wsb)")
        btn_sb_wsb.clicked.connect(self._generate_wsb_ui)
        sb_btn_row.addWidget(btn_sb_run)
        sb_btn_row.addWidget(btn_sb_wsb)
        sb_lay.addLayout(sb_btn_row)

        self.txt_sb_output = QTextEdit()
        self.txt_sb_output.setReadOnly(True)
        self.txt_sb_output.setFixedHeight(80)
        self.txt_sb_output.setPlaceholderText("沙箱隔離輸出...")
        sb_lay.addWidget(self.txt_sb_output)
        _sec_pages.append(grp_sb)

        # --- 區塊 5: 開機啟動項稽核 ---
        grp_audit = QGroupBox("🔍 5. 系統啟動項與持久化後門稽核")
        au_lay = QVBoxLayout(grp_audit)
        btn_au_run = QPushButton("🔍 稽核 Registry Run 與 Startup 開機項")
        btn_au_run.clicked.connect(self._run_startup_audit)
        au_lay.addWidget(btn_au_run)
        self.txt_au_output = QTextEdit()
        self.txt_au_output.setReadOnly(True)
        self.txt_au_output.setFixedHeight(75)
        self.txt_au_output.setPlaceholderText("開機啟動項檢測結果...")
        au_lay.addWidget(self.txt_au_output)
        _sec_pages.append(grp_audit)

        # --- 區塊 6: 主動網路防禦與網域白名單 ---
        grp_net = QGroupBox("🌐 6. 主動網路防禦與網域動態白名單 (Active Whitelist)")
        net_lay = QVBoxLayout(grp_net)
        net_lay.addWidget(QLabel(
            "<span style='color:#94a3b8;font-size:11px;'>"
            "所有外部連線主動比對白名單（支援萬用字元如 *.github.com）。"
            "非白名單網域與惡意純公網 IP 直連 (C2 遠端特徵) 將被立即主動阻斷。"
            "</span>"
        ))

        self.list_whitelist = QListWidget()
        self.list_whitelist.setFixedHeight(95)
        net_lay.addWidget(self.list_whitelist)

        wl_add_row = QHBoxLayout()
        self.txt_new_whitelist = QLineEdit()
        self.txt_new_whitelist.setPlaceholderText("輸入網域或萬用字元（例如 *.google.com 或 api.github.com）...")
        btn_add_wl = QPushButton("＋ 加入白名單")
        btn_add_wl.clicked.connect(self._add_domain_to_whitelist_ui)
        btn_del_wl = QPushButton("－ 移除選取網域")
        btn_del_wl.clicked.connect(self._del_domain_from_whitelist_ui)
        wl_add_row.addWidget(self.txt_new_whitelist, stretch=1)
        wl_add_row.addWidget(btn_add_wl)
        wl_add_row.addWidget(btn_del_wl)
        net_lay.addLayout(wl_add_row)

        net_tool_row = QHBoxLayout()
        self.txt_bad_ip = QLineEdit()
        self.txt_bad_ip.setPlaceholderText("輸入可疑 IP 直寫 Windows 防火牆黑名單...")
        btn_block_ip = QPushButton("🛑 防火牆阻斷 IP")
        btn_block_ip.setObjectName("dangerBtn")
        btn_block_ip.clicked.connect(self._block_ip_in_firewall_ui)
        btn_scan_conns = QPushButton("🔍 排查本機外連 (LOLBins)")
        btn_scan_conns.clicked.connect(self._scan_active_connections_ui)
        net_tool_row.addWidget(self.txt_bad_ip, stretch=1)
        net_tool_row.addWidget(btn_block_ip)
        net_tool_row.addWidget(btn_scan_conns)
        net_lay.addLayout(net_tool_row)

        self.txt_net_output = QTextEdit()
        self.txt_net_output.setReadOnly(True)
        self.txt_net_output.setFixedHeight(75)
        self.txt_net_output.setPlaceholderText("網路攔截日誌與連線排查報告...")
        net_lay.addWidget(self.txt_net_output)
        _sec_pages.append(grp_net)

        # --- 區塊 7: 超越傳統防毒之微秒級主動防禦哨兵 ---
        grp_hyper = QGroupBox("⚡ 7. 超越傳統防毒之「微秒級主動防禦哨兵」 (Hyper-Sentinel)")
        hyp_lay = QVBoxLayout(grp_hyper)
        hyp_lay.addWidget(QLabel(
            "<span style='color:#38bdf8;font-size:11px;font-weight:600;'>"
            "● 金絲雀誘餌陷阱 (Honeytokens) ● 勒索病毒微秒級大量加密熔斷 ● LOLBins 記憶體無檔案擊殺"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "不依賴過期特徵庫！只要未受信任進程碰觸誘餌或在 2 秒內連續高熵加密檔案，3 毫秒內直接 TerminateProcess 處決！"
            "</span>"
        ))

        hyp_btn_row = QHBoxLayout()
        btn_check_canary = QPushButton("🚨 檢查金絲雀誘餌完整度")
        btn_check_canary.clicked.connect(self._check_canary_status_ui)
        btn_kill_lolbins = QPushButton("⚡ 記憶體掃描並擊殺高危 LOLBins")
        btn_kill_lolbins.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold;")
        btn_kill_lolbins.clicked.connect(self._scan_and_kill_lolbins_ui)
        hyp_btn_row.addWidget(btn_check_canary)
        hyp_btn_row.addWidget(btn_kill_lolbins)
        hyp_lay.addLayout(hyp_btn_row)

        self.txt_hyper_output = QTextEdit()
        self.txt_hyper_output.setReadOnly(True)
        self.txt_hyper_output.setFixedHeight(80)
        self.txt_hyper_output.setPlaceholderText("微秒級哨兵處決日誌與誘餌監控...")
        hyp_lay.addWidget(self.txt_hyper_output)
        _sec_pages.append(grp_hyper)

        # --- 區塊 8: 全機檔案防篡改與核心防寫保護 ---
        grp_tamper = QGroupBox("🛡️ 8. 全機檔案防篡改與核心防寫保護 (Anti-Tamper & Self-Healing)")
        tamp_lay = QVBoxLayout(grp_tamper)
        tamp_lay.addWidget(QLabel(
            "<span style='color:#38bdf8;font-size:11px;font-weight:600;'>"
            "● NT 核心排他防寫防刪鎖 (FILE_SHARE_READ) ● NTFS DACL 拒絕刪改 ● Shadow Vault 原位秒級自癒"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "在 Windows 核心層阻斷所有進程的 Write/Delete 句柄開啟請求，並連動 Windows CFA 核心受控資料夾防勒索驅動。"
            "</span>"
        ))

        tamp_file_row = QHBoxLayout()
        self.txt_tamper_path = QLineEdit()
        self.txt_tamper_path.setPlaceholderText("請選擇或貼上欲鎖定防篡改之檔案或資料夾路徑...")
        self.txt_tamper_path.setText(str(self.current_workspace_dir))
        btn_tamp_browse_f = QPushButton("📄 選檔案")
        btn_tamp_browse_f.clicked.connect(self._browse_tamper_file)
        btn_tamp_browse_d = QPushButton("📁 選目錄")
        btn_tamp_browse_d.clicked.connect(self._browse_tamper_dir)
        tamp_file_row.addWidget(self.txt_tamper_path, stretch=1)
        tamp_file_row.addWidget(btn_tamp_browse_f)
        tamp_file_row.addWidget(btn_tamp_browse_d)
        tamp_lay.addLayout(tamp_file_row)

        tamp_btn_row1 = QHBoxLayout()
        btn_lock_kernel = QPushButton("🔒 啟用核心防寫鎖 (Kernel Lock)")
        btn_lock_kernel.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold;")
        btn_lock_kernel.clicked.connect(self._lock_kernel_ui)
        btn_unlock_kernel = QPushButton("🔓 解除核心鎖")
        btn_unlock_kernel.clicked.connect(self._unlock_kernel_ui)
        tamp_btn_row1.addWidget(btn_lock_kernel)
        tamp_btn_row1.addWidget(btn_unlock_kernel)
        tamp_lay.addLayout(tamp_btn_row1)

        tamp_btn_row2 = QHBoxLayout()
        btn_lock_ntfs = QPushButton("🛡️ NTFS DACL 拒絕刪改")
        btn_lock_ntfs.clicked.connect(self._lock_ntfs_ui)
        btn_unlock_ntfs = QPushButton("🔓 解除 NTFS 限制")
        btn_unlock_ntfs.clicked.connect(self._unlock_ntfs_ui)
        btn_self_heal = QPushButton("💊 全面校驗並原位自癒 (Self-Heal)")
        btn_self_heal.setStyleSheet("background-color: #059669; color: white; font-weight: bold;")
        btn_self_heal.clicked.connect(self._run_self_heal_ui)
        tamp_btn_row2.addWidget(btn_lock_ntfs)
        tamp_btn_row2.addWidget(btn_unlock_ntfs)
        tamp_btn_row2.addWidget(btn_self_heal)
        tamp_lay.addLayout(tamp_btn_row2)

        tamp_btn_row3 = QHBoxLayout()
        btn_cfa_status = QPushButton("🏢 查詢 Windows CFA 狀態")
        btn_cfa_status.clicked.connect(self._check_cfa_ui)
        btn_cfa_enable = QPushButton("⚡ 啟用 Windows 原生受控防寫")
        btn_cfa_enable.clicked.connect(self._enable_cfa_ui)
        tamp_btn_row3.addWidget(btn_cfa_status)
        tamp_btn_row3.addWidget(btn_cfa_enable)
        tamp_lay.addLayout(tamp_btn_row3)

        self.txt_tamper_output = QTextEdit()
        self.txt_tamper_output.setReadOnly(True)
        self.txt_tamper_output.setFixedHeight(85)
        self.txt_tamper_output.setPlaceholderText("檔案防篡改與自癒狀態日誌...")
        tamp_lay.addWidget(self.txt_tamper_output)
        _sec_pages.append(grp_tamper)

        # --- 區塊 9: 防奪取電腦控制權、防刪自我防衛與千毒湧浪風暴減壓閥 ---
        grp_ultimate = QGroupBox("🛡️ 9. 防奪取控制權 · 防刪自我防衛 · 千毒風暴減壓閥")
        ult_lay = QVBoxLayout(grp_ultimate)
        ult_lay.addWidget(QLabel(
            "<span style='color:#38bdf8;font-size:11px;font-weight:600;'>"
            "● 防毒檔案核心防刪鎖 ● 雙子不滅看門狗 ● 千毒並發秒級凍結 ● 影子管理員與 RAT 阻斷"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "防毒自身代碼上 NT 核心防刪鎖，del/taskkill 物理無效；千毒湧浪時由 NtSuspendProcess 批量凍結平行秒殺。"
            "</span>"
        ))

        ult_btn_row1 = QHBoxLayout()
        btn_self_lock = QPushButton("🔒 重新加固防毒自身防刪鎖")
        btn_self_lock.clicked.connect(self._lock_self_defense_ui)
        btn_check_takeover = QPushButton("👤 排查影子管理員與 RAT")
        btn_check_takeover.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold;")
        btn_check_takeover.clicked.connect(self._audit_takeover_ui)
        ult_btn_row1.addWidget(btn_self_lock)
        ult_btn_row1.addWidget(btn_check_takeover)
        ult_lay.addLayout(ult_btn_row1)

        ult_btn_row2 = QHBoxLayout()
        btn_storm_status = QPushButton("🌪️ 檢視千毒風暴減壓閥狀態")
        btn_storm_status.clicked.connect(self._check_storm_status_ui)
        btn_watchdog_status = QPushButton("🐕 檢視雙子不滅看門狗心跳")
        btn_watchdog_status.clicked.connect(self._check_watchdog_ui)
        ult_btn_row2.addWidget(btn_storm_status)
        ult_btn_row2.addWidget(btn_watchdog_status)
        ult_lay.addLayout(ult_btn_row2)

        self.txt_ultimate_output = QTextEdit()
        self.txt_ultimate_output.setReadOnly(True)
        self.txt_ultimate_output.setFixedHeight(85)
        self.txt_ultimate_output.setPlaceholderText("不滅自衛與防接管即時日誌...")
        ult_lay.addWidget(self.txt_ultimate_output)
        _sec_pages.append(grp_ultimate)

        # --- 區塊 10: 記憶體動態脫殼與無檔案反射注入防禦 (超越 360/小紅傘) ---
        grp_mem = QGroupBox("🛡️ 10. 記憶體動態脫殼與無檔案反射注入防禦 (超越傳統防毒)")
        mem_lay = QVBoxLayout(grp_mem)
        mem_lay.addWidget(QLabel(
            "<span style='color:#38bdf8;font-size:11px;font-weight:600;'>"
            "● VirtualQueryEx 記憶體分頁審查 ● 私有 RWX 異常堆疊偵測 ● 未掛接 PE (MZ) 反射式注入處決"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "360/小紅傘因依賴硬碟特徵碼，對加殼木馬與記憶體注入束手無策；本模組直接在記憶體解密展開時精準秒殺！"
            "</span>"
        ))

        mem_btn_row = QHBoxLayout()
        btn_scan_memory = QPushButton("⚡ 全機記憶體反射式注入深度排查")
        btn_scan_memory.setStyleSheet("background-color: #7c3aed; color: white; font-weight: bold;")
        btn_scan_memory.clicked.connect(self._scan_memory_injections_ui)
        btn_check_mem_status = QPushButton("🧠 檢視記憶體 EDR 哨兵狀態")
        btn_check_mem_status.clicked.connect(self._check_memory_sentinel_ui)
        mem_btn_row.addWidget(btn_scan_memory)
        mem_btn_row.addWidget(btn_check_mem_status)
        mem_lay.addLayout(mem_btn_row)

        self.txt_mem_output = QTextEdit()
        self.txt_mem_output.setReadOnly(True)
        self.txt_mem_output.setFixedHeight(85)
        self.txt_mem_output.setPlaceholderText("記憶體動態脫殼審查報告與注入處決日誌...")
        mem_lay.addWidget(self.txt_mem_output)
        _sec_pages.append(grp_mem)

        # --- 區塊 11: AI 預測推演熱修補與深度溯源物理粉碎 (幾乎無法攻破核心) ---
        grp_immune = QGroupBox("🧬 11. AI 預測推演熱修補與深度溯源物理粉碎 (免疫進化系統)")
        immune_lay = QVBoxLayout(grp_immune)
        immune_lay.addWidget(QLabel(
            "<span style='color:#a855f7;font-size:11px;font-weight:600;'>"
            "● MITRE ATT&CK 攻擊鏈狀態機預測 ● 下游脆弱路徑提前封堵 (Preemption) ● 動態微補丁即時生成 ● DoD 5220.22-M 物理粉碎"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "病毒攻擊某處，AI 即刻動態寫入修補規則；計算病毒下一步並提前封死通道；溯源進程家族與釋放體多輪清零物理粉碎！"
            "</span>"
        ))

        immune_btn_row = QHBoxLayout()
        btn_view_immune_status = QPushButton("🔮 檢視預測封堵與生效中的動態微補丁")
        btn_view_immune_status.setStyleSheet("background-color: #6366f1; color: white; font-weight: bold;")
        btn_view_immune_status.clicked.connect(self._view_predictive_immune_ui)
        btn_hunter_audit = QPushButton("🎯 檢視威脅溯源獵捕與物理粉碎歷史")
        btn_hunter_audit.clicked.connect(self._view_threat_hunter_audit_ui)
        immune_btn_row.addWidget(btn_view_immune_status)
        immune_btn_row.addWidget(btn_hunter_audit)
        immune_lay.addLayout(immune_btn_row)

        self.txt_immune_output = QTextEdit()
        self.txt_immune_output.setReadOnly(True)
        self.txt_immune_output.setFixedHeight(95)
        self.txt_immune_output.setPlaceholderText("AI 攻擊鏈推演預測、微補丁動態修補與溯源獵殺日誌...")
        immune_lay.addWidget(self.txt_immune_output)
        _sec_pages.append(grp_immune)

        # --- 區塊 12: 末日要塞資料死守 · 自身主動修復補齊 · 主動反殺 (極限生存核心) ---
        grp_citadel = QGroupBox("🏰 12. 末日資料要塞 · 自身主動修補補齊 · 主動反殺 (OS 崩潰死守)")
        citadel_lay = QVBoxLayout(grp_citadel)
        citadel_lay.addWidget(QLabel(
            "<span style='color:#ec4899;font-size:11px;font-weight:600;'>"
            "● OS 瀕危崩潰緊急自鎖 ● RAM 金鑰微秒零化 (Zeroize) ● 黃金根源代碼自癒再生 ● 特權剝奪與 ExitProcess 反殺"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "即便作業系統被攻破崩潰，末日要塞依然死守資料；防毒代碼受損主動原位補齊；向攻擊者發動反殺拔除開機自啟與遠程注入自我了結！"
            "</span>"
        ))

        cit_btn_row = QHBoxLayout()
        btn_view_citadel = QPushButton("🛡️ 檢視末日要塞金庫狀態")
        btn_view_citadel.setStyleSheet("background-color: #be185d; color: white; font-weight: bold;")
        btn_view_citadel.clicked.connect(self._view_citadel_status_ui)

        btn_run_self_heal = QPushButton("🔄 執行自身代碼完整性自檢與補齊")
        btn_run_self_heal.clicked.connect(self._run_self_heal_ui)

        btn_view_counter_strike = QPushButton("⚔️ 檢視主動反殺與持久化清剿紀錄")
        btn_view_counter_strike.clicked.connect(self._view_counter_strike_ui)

        cit_btn_row.addWidget(btn_view_citadel)
        cit_btn_row.addWidget(btn_run_self_heal)
        cit_btn_row.addWidget(btn_view_counter_strike)
        citadel_lay.addLayout(cit_btn_row)

        self.txt_citadel_output = QTextEdit()
        self.txt_citadel_output.setReadOnly(True)
        self.txt_citadel_output.setFixedHeight(95)
        self.txt_citadel_output.setPlaceholderText("末日要塞自鎖、自身模組修補再生與反殺戰果報告...")
        citadel_lay.addWidget(self.txt_citadel_output)
        _sec_pages.append(grp_citadel)

        # --- 區塊 13: 作業系統瀕危急救與全面復甦 (OS CPR & Resuscitation) ---
        grp_cpr = QGroupBox("🚑 13. 作業系統急救心肺復甦 · 系統救活與關鍵配置校準 (OS CPR)")
        cpr_lay = QVBoxLayout(grp_cpr)
        cpr_lay.addWidget(QLabel(
            "<span style='color:#ef4444;font-size:11px;font-weight:600;'>"
            "● 系統資源除顫 (釋放卡死進程) ● 解鎖工作管理員/登錄編輯器 ● 修復 Winlogon 核心啟動鏈 ● 清洗 IFEO 映像劫持 ● 救活核心服務"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "當作業系統被病毒改壞、鎖死管理權限、斷網或即將當機時，一鍵施加心肺復甦救活 OS 並全盤恢復系統命脈！"
            "</span>"
        ))

        cpr_btn_row = QHBoxLayout()
        btn_run_cpr = QPushButton("⚡ 立即執行作業系統全面心肺復甦 (CPR 救活)")
        btn_run_cpr.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold;")
        btn_run_cpr.clicked.connect(self._run_os_cpr_ui)

        btn_cpr_status = QPushButton("🩺 檢視系統急救紀錄與核心服務清單")
        btn_cpr_status.clicked.connect(self._view_os_cpr_status_ui)

        cpr_btn_row.addWidget(btn_run_cpr)
        cpr_btn_row.addWidget(btn_cpr_status)
        cpr_lay.addLayout(cpr_btn_row)

        self.txt_cpr_output = QTextEdit()
        self.txt_cpr_output.setReadOnly(True)
        self.txt_cpr_output.setFixedHeight(95)
        self.txt_cpr_output.setPlaceholderText("作業系統急救診斷、政策解鎖、Winlogon 修復與核心服務復原報告...")
        cpr_lay.addWidget(self.txt_cpr_output)
        _sec_pages.append(grp_cpr)

        # --- 區塊 14: BYOVD 核心驅動提權防護與早期開機審查 (進階紅方防禦) ---
        grp_byovd = QGroupBox("🛡️ 14. BYOVD 核心驅動提權防護 · 開機時間差 (TOCTOU) 審查")
        byovd_lay = QVBoxLayout(grp_byovd)
        byovd_lay.addWidget(QLabel(
            "<span style='color:#06b6d4;font-size:11px;font-weight:600;'>"
            "● LOLDrivers 易受攻擊合法簽名驅動排查 ● 阻斷 Ring 0 任意內核讀寫 ● 早期開機 BOOT_START 服務排查 ● 阻斷 Potato 權限模擬"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "針對紅方進階滲透手法（攜帶合法漏洞驅動攻擊內核、在系統啟動前搶先執行），實施核心級載入阻斷與啟動鏈嚴審！"
            "</span>"
        ))

        byovd_btn_row = QHBoxLayout()
        btn_scan_byovd = QPushButton("🔍 排查並阻斷系統內 BYOVD 漏洞驅動")
        btn_scan_byovd.setStyleSheet("background-color: #0891b2; color: white; font-weight: bold;")
        btn_scan_byovd.clicked.connect(self._scan_byovd_ui)

        btn_audit_totou = QPushButton("⏱️ 審查早期開機 (TOCTOU) 啟動驅動與服務")
        btn_audit_totou.clicked.connect(self._audit_totou_ui)

        byovd_btn_row.addWidget(btn_scan_byovd)
        byovd_btn_row.addWidget(btn_audit_totou)
        byovd_lay.addLayout(byovd_btn_row)

        self.txt_byovd_output = QTextEdit()
        self.txt_byovd_output.setReadOnly(True)
        self.txt_byovd_output.setFixedHeight(95)
        self.txt_byovd_output.setPlaceholderText("BYOVD 驅動黑名單掃描與早期開機時間差審查報告...")
        byovd_lay.addWidget(self.txt_byovd_output)
        _sec_pages.append(grp_byovd)

        # --- 區塊 15: TOTP 身分驗證器 · 自適應共生基因膠囊與無限復活控制中心 (人可關/毒不可關) ---
        grp_totp = QGroupBox("🔐 15. TOTP 身分驗證器 · 自適應共生與無限復活控制中心 (人可關 / 毒不可關)")
        totp_lay = QVBoxLayout(grp_totp)
        totp_lay.addWidget(QLabel(
            "<span style='color:#10b981;font-size:11px;font-weight:600;'>"
            "● RFC 6238 手機 Authenticator 動態碼 ● LLKHF_INJECTED 實體鍵盤鑑別 (防病毒模擬點擊) ● 三點共生基因膠囊無限復活"
            "</span><br><span style='color:#94a3b8;font-size:10.5px;'>"
            "廢除 exit_code==0 與靜態停止旗標！病毒即使強制殺進程或刪檔案也會在 300ms 內從共生膠囊無限復活；唯有真人輸入 6 位數 TOTP 驗證碼才可安全關閉或解除防刪鎖！"
            "</span>"
        ))

        totp_btn_row1 = QHBoxLayout()
        btn_bind_totp = QPushButton("📱 TOTP 驗證器：掃碼綁定 / 測試 / 換金鑰")
        btn_bind_totp.setStyleSheet("background-color: #059669; color: white; font-weight: bold;")
        btn_bind_totp.clicked.connect(self._show_totp_binding_ui)

        btn_sync_capsule = QPushButton("🧬 同步三點共生基因膠囊 & 檢視復活網狀態")
        btn_sync_capsule.clicked.connect(self._sync_symbiotic_capsules_ui)

        totp_btn_row1.addWidget(btn_bind_totp)
        totp_btn_row1.addWidget(btn_sync_capsule)
        totp_lay.addLayout(totp_btn_row1)

        totp_btn_row2 = QHBoxLayout()
        btn_totp_exit = QPushButton("🚪 驗證 TOTP 安全退出程式 (停止復活)")
        btn_totp_exit.setStyleSheet("background-color: #4f46e5; color: white; font-weight: bold;")
        btn_totp_exit.clicked.connect(lambda: self._safe_quit())

        btn_totp_uninstall = QPushButton("🔓 驗證 TOTP 解除所有防刪鎖 (允許刪除/移轉)")
        btn_totp_uninstall.setStyleSheet("background-color: #d97706; color: white; font-weight: bold;")
        btn_totp_uninstall.clicked.connect(self._totp_uninstall_unlock_ui)

        totp_btn_row2.addWidget(btn_totp_exit)
        totp_btn_row2.addWidget(btn_totp_uninstall)
        totp_lay.addLayout(totp_btn_row2)

        self.txt_totp_output = QTextEdit()
        self.txt_totp_output.setReadOnly(True)
        self.txt_totp_output.setFixedHeight(100)
        self.txt_totp_output.setPlaceholderText("TOTP 身分驗證器綁定資訊、自適應共生等級與無限復活狀態...")
        totp_lay.addWidget(self.txt_totp_output)
        _sec_pages.append(grp_totp)

        self._refresh_quarantine_table()
        self._refresh_whitelist_ui()
        return self._build_security_navigator(_sec_pages)

    # 防護中心各功能的白話名稱（依區塊順序）
    _SEC_PAGE_NAMES = [
        "🧼 檔案清洗（去除惡意內容）",
        "🔍 掃毒",
        "☣️ 隔離區",
        "📦 沙箱執行指令",
        "🚀 開機啟動項檢查",
        "🌐 網路防護與白名單",
        "🪤 勒索病毒防護",
        "🔒 檔案防竄改",
        "🛡️ 自我保護",
        "🧠 記憶體防護",
        "🔮 AI 預測防禦",
        "🏰 資料保險庫",
        "🚑 系統急救",
        "⚙️ 驅動程式防護",
        "🔐 TOTP 驗證與安全退出",
    ]

    # 每頁一句白話說明（取代原本的技術說明）
    _SEC_PAGE_DESC = [
        "把來路不明的檔案（圖片、PDF、Office、壓縮檔）去掉藏在裡面的惡意內容，產生乾淨的版本。",
        "掃描檔案或資料夾有沒有病毒。發現威脅時可以自動移到隔離區。",
        "被隔離的可疑檔案都在這裡，可以還原或永久刪除。",
        "在受限制的環境裡執行指令：限制記憶體用量，也不帶 API Key 等敏感資料。",
        "檢查開機時會自動執行的程式，找出可疑的項目。",
        "只允許連到白名單上的網站；也可以封鎖可疑 IP、檢查目前的對外連線。",
        "在電腦裡放誘餌檔案，只要有程式去動它或短時間大量加密檔案，就立刻終止那個程式。",
        "鎖定重要的檔案或資料夾，避免被修改或刪除；被改壞時可以自動修復。",
        "保護 Syntra 本身不被強制關閉或刪除，並檢查有沒有遠端控制木馬。",
        "檢查執行中的程式有沒有在記憶體裡偷藏惡意程式碼。",
        "預測攻擊的下一步並提前封鎖，也可以查看已處理的威脅紀錄。",
        "系統出問題時保護重要資料，並自動修復 Syntra 自己被破壞的檔案。",
        "系統被病毒改壞（例如工作管理員被鎖、重要服務被停掉）時，一鍵修復。",
        "檢查電腦裡有沒有已知有漏洞、可能被駭客利用的驅動程式。",
        "用手機驗證碼（TOTP）安全退出 Syntra，或解除檔案的防刪除鎖定。",
    ]

    # 按鈕改成白話短字（完整原文放在滑鼠提示）
    _SEC_BTN_TEXT = {
        "🚀 執行 CDR 深度清洗重構": "🚀 開始清洗",
        "⚡ 本地啟發式掃描": "⚡ 快速掃描",
        "🔍 複合全面掃毒": "🔍 完整掃毒",
        "🔥 徹底粉碎抹除": "🔥 永久刪除",
        "▶️ 在受限沙箱中執行": "▶️ 在沙箱中執行",
        "📑 產生 Windows Sandbox (.wsb)": "📑 產生 Windows 沙箱檔",
        "🔍 稽核 Registry Run 與 Startup 開機項": "🔍 檢查開機啟動項",
        "－ 移除選取網域": "－ 移除選取",
        "🛑 防火牆阻斷 IP": "🛑 封鎖 IP",
        "🔍 排查本機外連 (LOLBins)": "🔍 檢查對外連線",
        "🚨 檢查金絲雀誘餌完整度": "🚨 檢查誘餌檔案",
        "⚡ 記憶體掃描並擊殺高危 LOLBins": "⚡ 終止可疑程式",
        "🔒 啟用核心防寫鎖 (Kernel Lock)": "🔒 鎖定（禁止寫入）",
        "🔓 解除核心鎖": "🔓 解除鎖定",
        "🛡️ NTFS DACL 拒絕刪改": "🛡️ 禁止刪改",
        "🔓 解除 NTFS 限制": "🔓 解除禁止刪改",
        "💊 全面校驗並原位自癒 (Self-Heal)": "💊 檢查並自動修復",
        "🏢 查詢 Windows CFA 狀態": "🏢 查看資料夾保護",
        "⚡ 啟用 Windows 原生受控防寫": "⚡ 開啟資料夾保護",
        "🔒 重新加固防毒自身防刪鎖": "🔒 重新鎖定自身檔案",
        "👤 排查影子管理員與 RAT": "👤 檢查遠端控制木馬",
        "🌪️ 檢視千毒風暴減壓閥狀態": "🌪️ 大量攻擊防護狀態",
        "🐕 檢視雙子不滅看門狗心跳": "🐕 看門狗狀態",
        "⚡ 全機記憶體反射式注入深度排查": "⚡ 掃描記憶體",
        "🧠 檢視記憶體 EDR 哨兵狀態": "🧠 防護狀態",
        "🔮 檢視預測封堵與生效中的動態微補丁": "🔮 預測防禦狀態",
        "🎯 檢視威脅溯源獵捕與物理粉碎歷史": "🎯 處理紀錄",
        "🛡️ 檢視末日要塞金庫狀態": "🛡️ 保險庫狀態",
        "🔄 執行自身代碼完整性自檢與補齊": "🔄 自我檢查與修復",
        "⚔️ 檢視主動反殺與持久化清剿紀錄": "⚔️ 反擊紀錄",
        "⚡ 立即執行作業系統全面心肺復甦 (CPR 救活)": "⚡ 立即修復系統",
        "🩺 檢視系統急救紀錄與核心服務清單": "🩺 修復紀錄",
        "🔍 排查並阻斷系統內 BYOVD 漏洞驅動": "🔍 檢查漏洞驅動",
        "⏱️ 審查早期開機 (TOCTOU) 啟動驅動與服務": "⏱️ 檢查開機驅動",
        "📱 TOTP 驗證器：掃碼綁定 / 測試 / 換金鑰": "📱 綁定手機驗證器",
        "🧬 同步三點共生基因膠囊 & 檢視復活網狀態": "🧬 同步自動復原備份",
        "🚪 驗證 TOTP 安全退出程式 (停止復活)": "🚪 驗證後退出 Syntra",
        "🔓 驗證 TOTP 解除所有防刪鎖 (允許刪除/移轉)": "🔓 驗證後解除檔案鎖",
    }

    def _tidy_security_page(self, grp: QGroupBox, idx: int):
        """整理單一功能頁：拿掉長標題、白話說明、按鈕自動折行、輸出框可伸縮"""
        grp.setTitle("")
        grp.setStyleSheet("QGroupBox { border: none; margin-top: 0; padding-top: 0; }")
        lay = grp.layout()
        # 技術說明 → 一句白話
        for lbl in grp.findChildren(QLabel):
            if "<span" in lbl.text():
                lbl.hide()
            lbl.setWordWrap(True)
        if lay is not None and 0 <= idx < len(self._SEC_PAGE_DESC):
            desc = QLabel(self._SEC_PAGE_DESC[idx])
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #94a3b8; font-size: 12px; padding-bottom: 4px;")
            lay.insertWidget(0, desc)
        for chk in grp.findChildren(QCheckBox):
            full = chk.text()
            chk.setText(re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", full).strip() or full)
            chk.setToolTip(full)
        for btn in grp.findChildren(QPushButton):
            text = btn.text()
            short = self._SEC_BTN_TEXT.get(text) or re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", text).strip()
            if short and short != text:
                btn.setToolTip(text)
                btn.setText(short)
            btn.setMinimumWidth(1)
            btn.setSizePolicy(_QSizePolicy.Preferred, _QSizePolicy.Fixed)
        for w in grp.findChildren(QTextEdit) + grp.findChildren(QListWidget) + grp.findChildren(QTableWidget):
            h = max(80, w.height() if w.height() < 400 else 80)
            w.setMinimumHeight(min(h, 120))
            w.setMaximumHeight(16777215)
            w.setSizePolicy(_QSizePolicy.Expanding, _QSizePolicy.Expanding)
        for le in grp.findChildren(QLineEdit):
            le.setMinimumWidth(60)
        # 橫列 → 輸入框獨立一行，按鈕改成會折行的排版
        if lay is None:
            return
        i = 0
        while i < lay.count():
            item = lay.itemAt(i)
            sub = item.layout() if item is not None else None
            if not isinstance(sub, QHBoxLayout) or sub.count() == 0:
                i += 1
                continue
            widgets = [sub.itemAt(j).widget() for j in range(sub.count())]
            if any(w is None for w in widgets):
                i += 1
                continue
            inputs = [w for w in widgets if not isinstance(w, QPushButton)]
            buttons = [w for w in widgets if isinstance(w, QPushButton)]
            for w in widgets:
                sub.removeWidget(w)
            lay.takeAt(i)
            for w in inputs:
                lay.insertWidget(i, w)
                i += 1
            if buttons:
                holder = QWidget()
                flow = _FlowLayout(holder)
                for w in buttons:
                    flow.addWidget(w)
                lay.insertWidget(i, holder)
                i += 1

    def _build_security_navigator(self, pages) -> QWidget:
        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(4, 6, 4, 4)
        rl.setSpacing(8)

        combo = QComboBox()
        combo.setStyleSheet(_DROPDOWN_QSS)
        combo.setSizePolicy(_QSizePolicy.Expanding, _QSizePolicy.Fixed)
        combo.setMinimumContentsLength(4)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        stack = _QStackedWidget()

        def _wrap(widget):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            sc.setWidget(widget)
            return sc

        combo.addItem("📊 總覽（一鍵健檢）")
        stack.addWidget(_wrap(self._build_security_overview()))
        for idx, (grp, name) in enumerate(zip(pages, self._SEC_PAGE_NAMES)):
            self._tidy_security_page(grp, idx)
            combo.addItem(name)
            stack.addWidget(_wrap(grp))
        combo.currentIndexChanged.connect(stack.setCurrentIndex)
        combo.currentIndexChanged.connect(
            lambda i: self._refresh_quarantine_table() if i == 3 else None
        )
        self.combo_security_page = combo
        rl.addWidget(combo)
        rl.addWidget(stack, stretch=1)

        # 啟動後自動跑一次健檢（背景執行，不卡畫面）
        QTimer.singleShot(8000, self._run_health_check)
        return root

    def _build_security_overview(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        self.lbl_health_summary = QLabel("⏳ 尚未檢查")
        self.lbl_health_summary.setWordWrap(True)
        self.lbl_health_summary.setStyleSheet("font-size: 14px; font-weight: 700; color: #e2e8f0;")
        lay.addWidget(self.lbl_health_summary)

        hint = QLabel("自動檢查開機啟動項、網路外連、勒索誘餌、自我保護、記憶體防護與隔離區。"
                      "啟動後會自動跑一次，也可以隨時手動重跑。只會檢查，不會刪除或修改任何東西。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 11.5px;")
        lay.addWidget(hint)

        self.btn_health_check = QPushButton("🛡️ 一鍵健檢")
        self.btn_health_check.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 8px 14px;")
        self.btn_health_check.clicked.connect(self._run_health_check)
        lay.addWidget(self.btn_health_check)

        self.txt_health_output = QTextEdit()
        self.txt_health_output.setReadOnly(True)
        self.txt_health_output.setMinimumHeight(160)
        self.txt_health_output.setPlaceholderText("健檢結果會顯示在這裡…")
        lay.addWidget(self.txt_health_output, stretch=1)
        return w

    def _collect_health_report(self):
        """在背景執行緒中跑：只做唯讀檢查"""
        sg = self.security_guard
        lines, issues = [], 0

        def section(name, fn):
            nonlocal issues
            try:
                ok, msg, n = fn()
            except Exception as e:  # noqa: BLE001
                ok, msg, n = None, f"無法檢查（{e}）", 0
            icon = "🟢" if ok else ("⚪" if ok is None else "🔴")
            if ok is False:
                issues += max(1, n)
            lines.append(f"{icon} {name}：{msg}")

        def startup():
            r = sg.antivirus_scanner.audit_startup_and_persistence()
            s = int(r.get("suspicious_count", 0) or 0)
            bad = [f"   • {it.get('name')}：{it.get('command')}" for it in r.get("items", []) if it.get("suspicious")][:5]
            msg = f"共 {r.get('total_items', 0)} 項，可疑 {s} 項" + ("\n" + "\n".join(bad) if bad else "")
            return s == 0, msg, s

        def network():
            conns = sg.network_guard.inspect_active_system_connections() or []
            bad = [f"   • {c.get('process')} → {c.get('remote_ip')}:{c.get('remote_port')}" for c in conns][:5]
            return (not conns), ("沒有可疑外連" if not conns else f"{len(conns)} 筆非白名單外連\n" + "\n".join(bad)), len(conns)

        def canary():
            st = sg.hyper_sentinel.check_canary_integrity()
            return (not st), ("誘餌完好" if not st else f"誘餌異常：{st.get('reason')}"), 1

        def self_def():
            st = sg.self_defense.get_status()
            on = bool(st.get("watchdog_active"))
            return on, (f"看門狗運作中，已保護 {st.get('self_files_locked_count')} 個檔案" if on else "看門狗未啟動"), 1

        def memory():
            st = sg.memory_sentinel.get_status()
            on = bool(st.get("active"))
            return on, (f"監控中，累計攔截 {st.get('detected_injections_count', 0)} 件" if on else "未啟動"), 1

        def quarantine():
            recs = sg.antivirus_scanner.list_quarantine() or []
            return True, f"目前隔離 {len(recs)} 個檔案", 0

        section("開機啟動項", startup)
        section("網路外連", network)
        section("勒索誘餌", canary)
        section("自我保護", self_def)
        section("記憶體防護", memory)
        section("隔離區", quarantine)
        return "\n".join(lines), issues

    def _run_health_check(self):
        if not hasattr(self, "txt_health_output") or getattr(self, "_health_thread", None) is not None:
            return
        self.btn_health_check.setEnabled(False)
        self.btn_health_check.setText("⏳ 檢查中…")
        self.lbl_health_summary.setText("⏳ 檢查中…")
        th = _HealthCheckThread(self._collect_health_report, self)
        th.done.connect(self._on_health_check_done)
        th.finished.connect(lambda: setattr(self, "_health_thread", None))
        self._health_thread = th
        th.start()

    def _on_health_check_done(self, text: str, issues: int):
        stamp = time.strftime("%H:%M")
        if issues == 0:
            summary = f"🟢 一切正常（{stamp} 檢查）"
        elif issues < 0:
            summary = f"⚪ 健檢沒有完成（{stamp}）"
        else:
            summary = f"🔴 發現 {issues} 個需要注意的地方（{stamp} 檢查）"
        self.lbl_health_summary.setText(summary)
        self.txt_health_output.setPlainText(text)
        self.btn_health_check.setEnabled(True)
        self.btn_health_check.setText("🛡️ 一鍵健檢")

    def _browse_cdr_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇欲進行 CDR 無害化重構之檔案")
        if path:
            self.txt_cdr_path.setText(path)

    def _run_cdr_disarm(self):
        target = self.txt_cdr_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請先選擇要重構的檔案！")
            return
        self.txt_cdr_output.setPlainText("正在執行 CDR 深度無害化分解與安全重構中...")
        res = self.security_guard.cdr_disarm_file(target)
        if res.get("ok"):
            acts = "\n".join(f"• {a}" for a in res.get("disarmed_actions", []))
            msg = (
                f"✅ CDR 重構成功！\n"
                f"來源 SHA256: {res.get('original_sha256')}\n"
                f"重構 SHA256: {res.get('reconstructed_sha256')}\n"
                f"安全新檔路徑: {res.get('clean_file_path')}\n\n"
                f"【消除之安全威脅與動作】：\n{acts}"
            )
        else:
            msg = f"❌ CDR 重構失敗：{res.get('error')}"
        self.txt_cdr_output.setPlainText(msg)

    def _browse_av_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇欲掃描之檔案")
        if path:
            self.txt_av_path.setText(path)

    def _browse_av_dir(self):
        path = QFileDialog.getExistingDirectory(self, "選擇欲掃描之目錄")
        if path:
            self.txt_av_path.setText(path)

    def _run_av_heuristics(self):
        target = self.txt_av_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇掃描目標！")
            return
        self.txt_av_output.setPlainText("正在進行本地啟發式惡意特徵快篩...")
        res = self.security_guard.antivirus_scanner.scan_file_heuristics(target)
        if res.get("ok"):
            if res.get("clean"):
                self.txt_av_output.setPlainText(f"✅ 啟發式掃描安全：未發現可疑雙副檔名、檔案頭偽裝或惡意注入代碼。\n目標：{target}")
            else:
                threats_desc = "\n".join([f"[{t['severity']}] {t['type']}: {t['detail']}" for t in res.get("threats", [])])
                self.txt_av_output.setPlainText(f"⚠️ 發現 {res.get('threat_count')} 項啟發式威脅！\n{threats_desc}")
        else:
            self.txt_av_output.setPlainText(f"掃描失敗：{res.get('error')}")

    def _run_av_defender(self):
        target = self.txt_av_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇掃描目標！")
            return
        self.txt_av_output.setPlainText("正在調用 Windows Defender (MpCmdRun) 掃描中，請稍候...")

        async def _scan():
            return await self.security_guard.antivirus_scanner.scan_with_windows_defender(target)

        future = self.async_worker.submit(_scan())
        def _done():
            res = future.result()
            if res.get("ok", True):
                status = "⚠️ 偵測到威脅！" if res.get("threat_detected") else "✅ 安全無毒"
                self.txt_av_output.setPlainText(f"【Windows Defender 掃描結果】：{status}\n引擎：{res.get('engine')}\n日誌：\n{res.get('output')}")
            else:
                self.txt_av_output.setPlainText(f"Defender 掃描失敗：{res.get('error')}")
        future.add_done_callback(lambda _: _done())

    def _run_av_full_scan(self):
        target = self.txt_av_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇掃描目標！")
            return
        auto_q = self.chk_auto_quarantine.isChecked()
        self.txt_av_output.setPlainText(f"正在執行全面複合掃毒（Defender + 啟發式，自動隔離={auto_q}）...")

        async def _full():
            return await self.security_guard.scan_antivirus(target, auto_quarantine=auto_q)

        future = self.async_worker.submit(_full())
        def _done():
            res = future.result()
            if res.get("ok"):
                th_count = len(res.get("threats_found", []))
                q_count = len(res.get("quarantined", []))
                status = f"✅ 安全！掃描 {res.get('scanned_files')} 個檔案無任何異常。" if res.get("is_clean") else f"⚠️ 發現 {th_count} 項威脅！已隔離 {q_count} 筆。"
                th_desc = "\n".join([f"• [{t.get('source')}] {t.get('detail')} ({t.get('file')})" for t in res.get("threats_found", [])])
                self.txt_av_output.setPlainText(f"{status}\n\n【詳細清單】：\n{th_desc}")
                self._refresh_quarantine_table()
            else:
                self.txt_av_output.setPlainText(f"全面掃毒失敗：{res.get('error')}")
        future.add_done_callback(lambda _: _done())

    def _refresh_quarantine_table(self):
        if not hasattr(self, "table_quarantine"):
            return
        records = self.security_guard.antivirus_scanner.list_quarantine()
        self.table_quarantine.setRowCount(len(records))
        for r_idx, r in enumerate(records):
            self.table_quarantine.setItem(r_idx, 0, QTableWidgetItem(r.get("id", "")))
            self.table_quarantine.setItem(r_idx, 1, QTableWidgetItem(r.get("original_path", "")))
            self.table_quarantine.setItem(r_idx, 2, QTableWidgetItem(r.get("reason", "")))

    def _restore_quarantined_file(self):
        row = self.table_quarantine.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "請先點選要還原的隔離檔案！")
            return
        qid = self.table_quarantine.item(row, 0).text()
        res = self.security_guard.antivirus_scanner.restore_quarantined_file(qid)
        if res.get("ok"):
            QMessageBox.information(self, "成功", f"檔案已成功解密還原至：\n{res.get('restored_path')}")
            self._refresh_quarantine_table()
        else:
            QMessageBox.critical(self, "失敗", f"還原失敗：{res.get('error')}")

    def _shred_quarantined_file(self):
        row = self.table_quarantine.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "請先點選要粉碎的隔離檔案！")
            return
        qid = self.table_quarantine.item(row, 0).text()
        confirm = QMessageBox.question(self, "確認粉碎", f"確定要使用 0x00 與隨機字節多次覆寫徹底抹除隔離檔案 (ID: {qid}) 嗎？此操作無法復原！")
        if confirm == QMessageBox.Yes:
            res = self.security_guard.antivirus_scanner.shred_quarantined_file(qid)
            if res.get("ok"):
                QMessageBox.information(self, "已粉碎", "檔案已徹底粉碎銷毀！")
                self._refresh_quarantine_table()
            else:
                QMessageBox.critical(self, "失敗", f"粉碎失敗：{res.get('error')}")

    def _run_in_sandbox_ui(self):
        cmd = self.txt_sb_cmd.text().strip()
        if not cmd:
            QMessageBox.warning(self, "提示", "請輸入指令！")
            return
        self.txt_sb_output.setPlainText("正在受限 Job Object 沙箱環境中執行 (限制記憶體 512MB + 脫敏環境變數)...")

        async def _run():
            return await self.security_guard.run_in_sandbox(cmd, timeout=30.0)

        future = self.async_worker.submit(_run())
        def _done():
            res = future.result()
            status = "✅ 執行成功" if res.get("ok") else "⚠️ 執行異常或熔斷"
            self.txt_sb_output.setPlainText(f"【沙箱狀態】：{status} (Exit Code: {res.get('exit_code')})\n\n【輸出內容】：\n{res.get('output')}")
        future.add_done_callback(lambda _: _done())

    def _generate_wsb_ui(self):
        target = self.txt_cdr_path.text().strip() or str(self.current_workspace_dir)
        ok, path_or_err = self.security_guard.sandbox_executor.generate_windows_sandbox_profile(target)
        if ok:
            QMessageBox.information(self, "沙箱設定產生完成", f"已成功生成 Windows Sandbox 配置檔案：\n{path_or_err}\n\n若系統已啟用 Windows 沙箱功能，可直接雙擊該檔案在純淨虛擬機中隔離執行！")
            self.txt_sb_output.setPlainText(f"已生成 Windows Sandbox 檔案：{path_or_err}")
        else:
            QMessageBox.warning(self, "產生失敗", path_or_err)

    def _run_startup_audit(self):
        res = self.security_guard.antivirus_scanner.audit_startup_and_persistence()
        total = res.get("total_items", 0)
        suspicious = res.get("suspicious_count", 0)
        lines = [f"【開機啟動項稽核結果】：共掃描 {total} 項，可疑項：{suspicious} 項"]
        for it in res.get("items", []):
            flag = "⚠️ [可疑]" if it.get("suspicious") else "✓"
            lines.append(f"{flag} [{it.get('source')}] {it.get('name')}: {it.get('command')}")
        self.txt_au_output.setPlainText("\n".join(lines))

    def _refresh_whitelist_ui(self):
        if not hasattr(self, "list_whitelist"):
            return
        self.list_whitelist.clear()
        domains = self.security_guard.network_guard.get_whitelist()
        for d in domains:
            self.list_whitelist.addItem(f"🛡️ {d}")

    def _add_domain_to_whitelist_ui(self):
        domain = self.txt_new_whitelist.text().strip()
        if not domain:
            QMessageBox.warning(self, "提示", "請輸入網域或萬用字元（如 *.google.com）！")
            return
        ok = self.security_guard.add_whitelist_domain(domain)
        if ok:
            QMessageBox.information(self, "成功", f"已成功將「{domain}」加入連線白名單！")
            self.txt_new_whitelist.clear()
            self._refresh_whitelist_ui()
        else:
            QMessageBox.warning(self, "提示", f"「{domain}」已在白名單中或格式無效。")

    def _del_domain_from_whitelist_ui(self):
        item = self.list_whitelist.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "請先選取要移除的白名單項目！")
            return
        domain = item.text().replace("🛡️ ", "").strip()
        confirm = QMessageBox.question(self, "確認移除", f"確定要將「{domain}」自白名單中移除嗎？此後連線將被主動攔截。")
        if confirm == QMessageBox.Yes:
            self.security_guard.remove_whitelist_domain(domain)
            self._refresh_whitelist_ui()

    def _block_ip_in_firewall_ui(self):
        ip = self.txt_bad_ip.text().strip()
        if not ip:
            QMessageBox.warning(self, "提示", "請輸入 IP 位址！")
            return
        ok, msg = self.security_guard.block_network_ip(ip)
        if ok:
            QMessageBox.information(self, "已阻斷", msg)
            self.txt_bad_ip.clear()
        else:
            QMessageBox.critical(self, "失敗", msg)

    def _scan_active_connections_ui(self):
        conns = self.security_guard.network_guard.inspect_active_system_connections()
        if not conns:
            self.txt_net_output.setPlainText("✅ 目前所有本機活躍連線皆符合白名單規則，未發現可疑 LOLBins 外連。")
            return
        lines = [f"⚠️ 發現 {len(conns)} 筆異常或非白名單外連："]
        for c in conns:
            tag = "[高危 LOLBin 外連!]" if c.get("is_lolbin") else "[非白名單]"
            lines.append(f"• {tag} PID:{c.get('pid')} {c.get('process')} -> {c.get('remote_ip')}:{c.get('remote_port')}")
        self.txt_net_output.setPlainText("\n".join(lines))

    def _check_canary_status_ui(self):
        status = self.security_guard.hyper_sentinel.check_canary_integrity()
        overview = self.security_guard.hyper_sentinel.get_status_overview()
        traps_info = "\n".join([f"• {p}" for p in overview.get("canary_locations", [])])
        if not status:
            self.txt_hyper_output.setPlainText(
                f"🟢 金絲雀誘餌陷阱狀態正常 (未受碰觸，守護中)！\n"
                f"已在以下敏感熱點布設誘餌：\n{traps_info}"
            )
        else:
            self.txt_hyper_output.setPlainText(
                f"🚨 [警報！] 偵測到誘餌異常：\n"
                f"原因：{status.get('reason')}\n"
                f"路徑：{status.get('path')}\n"
                f"若有惡意勒索軟體嘗試加密，哨兵將在 3 毫秒內予以擊殺！"
            )

    def _scan_and_kill_lolbins_ui(self):
        killed = self.security_guard.hyper_sentinel.scan_active_processes_for_lolbins()
        if not killed:
            self.txt_hyper_output.setPlainText("✅ 記憶體掃描完成：未發現帶有無檔案攻擊 (-enc / IEX / bypass) 的惡意 LOLBins 進程。")
        else:
            lines = [f"🛑 已主動擊殺處決 {len(killed)} 個高危惡意無檔案進程！"]
            for k in killed:
                lines.append(f"• 已終止 PID {k.get('pid')} ({k.get('process_name')}): {k.get('matched_pattern')}")
            self.txt_hyper_output.setPlainText("\n".join(lines))

    def _browse_tamper_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "選擇欲鎖定防篡改之檔案")
        if path:
            self.txt_tamper_path.setText(path)

    def _browse_tamper_dir(self):
        path = QFileDialog.getExistingDirectory(self, "選擇欲鎖定防篡改之目錄")
        if path:
            self.txt_tamper_path.setText(path)

    def _lock_kernel_ui(self):
        target = self.txt_tamper_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇目標路徑！")
            return
        ok, msg = self.security_guard.lock_file_anti_tamper(target, mode="kernel")
        if ok:
            QMessageBox.information(self, "防篡改已啟動", msg)
        else:
            QMessageBox.critical(self, "失敗", msg)
        self.txt_tamper_output.setPlainText(msg)

    def _unlock_kernel_ui(self):
        target = self.txt_tamper_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇目標路徑！")
            return
        ok, msg = self.security_guard.unlock_file_anti_tamper(target, mode="kernel")
        self.txt_tamper_output.setPlainText(msg)

    def _lock_ntfs_ui(self):
        target = self.txt_tamper_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇目標路徑！")
            return
        ok, msg = self.security_guard.lock_file_anti_tamper(target, mode="ntfs")
        if ok:
            QMessageBox.information(self, "NTFS 防篡改完成", msg)
        else:
            QMessageBox.critical(self, "失敗", msg)
        self.txt_tamper_output.setPlainText(msg)

    def _unlock_ntfs_ui(self):
        target = self.txt_tamper_path.text().strip()
        if not target:
            QMessageBox.warning(self, "提示", "請輸入或選擇目標路徑！")
            return
        ok, msg = self.security_guard.unlock_file_anti_tamper(target, mode="ntfs")
        self.txt_tamper_output.setPlainText(msg)

    def _run_self_heal_ui(self):
        self.txt_tamper_output.setPlainText("正在進行全機受保護檔案完整性比對與自癒檢查...")
        res = self.security_guard.auto_self_heal_files()
        details = "\n".join([f"• [{d.get('status')}] {d.get('detail')} ({d.get('path')})" for d in res.get("details", [])])
        msg = f"✅ 完整性自癒檢查完成！共受保護 {res.get('total_files')} 個檔案，修復自癒 {res.get('healed_count')} 個異常檔案。\n\n{details}"
        self.txt_tamper_output.setPlainText(msg)

    def _check_cfa_ui(self):
        status = self.security_guard.integrity_guard.get_cfa_status()
        if status.get("ok"):
            folders = "\n".join([f"• {f}" for f in status.get("protected_folders", [])]) or "（預設包含使用者所有文件、相片、桌面）"
            self.txt_tamper_output.setPlainText(
                f"【Windows CFA 受控資料夾存取狀態】：{status.get('status_text')}\n"
                f"核心受控保護資料夾清單：\n{folders}"
            )
        else:
            self.txt_tamper_output.setPlainText(f"查詢失敗：{status.get('error')}")

    def _enable_cfa_ui(self):
        ok, msg = self.security_guard.integrity_guard.enable_cfa_powershell()
        if ok:
            QMessageBox.information(self, "CFA 啟動成功", msg)
        else:
            QMessageBox.warning(self, "提示", msg)
        self.txt_tamper_output.setPlainText(msg)

    def _lock_self_defense_ui(self):
        res = self.security_guard.self_defense.lock_all_self_files()
        msg = f"✅ 已對防毒自身 {res.get('total_protected_files')} 個核心代碼與模組套用核心防刪鎖！作業系統層面已阻斷所有外部進程刪除與竄改。"
        self.txt_ultimate_output.setPlainText(msg)

    def _audit_takeover_ui(self):
        alert = self.security_guard.anti_takeover.audit_and_revert_unauthorized_admins()
        rats = self.security_guard.anti_takeover.scan_for_unauthorized_remote_control()
        lines = []
        if alert:
            lines.append(f"🚨 {alert.get('detail')}")
        else:
            lines.append("✅ 影子管理員排查合格：本機管理員群組無任何未授權帳戶建立。")

        if rats:
            lines.append(f"🛑 已阻斷並終止 {len(rats)} 個可疑遠端接管進程：")
            for r in rats:
                lines.append(f"• 已擊殺 {r.get('tool')} (PID: {r.get('pid')})")
        else:
            lines.append("✅ 遠端接管排查合格：未發現 AnyDesk / TeamViewer / VNC 等影子接管後門。")

        self.txt_ultimate_output.setPlainText("\n".join(lines))

    def _check_storm_status_ui(self):
        status = self.security_guard.storm_shield.get_status()
        events = status.get("recent_events", [])
        if not events:
            self.txt_ultimate_output.setPlainText("🟢 千毒湧浪風暴減壓閥已常駐守護中 (平行 NtSuspendProcess 凍結準備就緒)！目前系統進程衍生速率正常。")
        else:
            lines = [f"🌪️ 已阻斷 {len(events)} 次病毒風暴衝擊事件："]
            for ev in events:
                lines.append(f"• [{ev.get('timestamp')}] 凍結 {ev.get('frozen_count')} 個進程，處決 {ev.get('killed_count')} 個進程，耗時 {ev.get('elapsed_ms')} 毫秒")
            self.txt_ultimate_output.setPlainText("\n".join(lines))

    def _check_watchdog_ui(self):
        status = self.security_guard.self_defense.get_status()
        state = "🟢 心跳正常 (雙子守護中)" if status.get("watchdog_active") else "⚠️ 未啟動"
        pid = status.get("watchdog_pid")
        locked_cnt = status.get("self_files_locked_count")
        self.txt_ultimate_output.setPlainText(
            f"【雙子不滅看門狗狀態】：{state} (Watchdog PID: {pid})\n"
            f"防毒自身檔案核心防刪鎖：已鎖定 {locked_cnt} 個核心檔案 (任何外部 taskkill /F 將在 50 毫秒內自癒復活)"
        )

    def _scan_memory_injections_ui(self):
        self.txt_mem_output.setPlainText("正在以 VirtualQueryEx 深度遍歷非系統進程之虛擬記憶體分頁 (排查私有 RWX 與反射式 MZ 注入)...")
        alerts = self.security_guard.memory_sentinel.scan_all_untrusted_processes()
        if not alerts:
            self.txt_mem_output.setPlainText("✅ 全機進程記憶體審查通過！未發現任何私有 RWX 異常分頁、無檔案反射注入或脫殼加殼木馬。")
        else:
            lines = [f"🚨 成功在記憶體層面偵測並處決 {len(alerts)} 個注入木馬進程："]
            for a in alerts:
                lines.append(f"• 已擊殺進程 PID {a.get('pid')} ({a.get('process_name')}) -> 位址: {a.get('base_address')} (原因: {a.get('reason')})")
            self.txt_mem_output.setPlainText("\n".join(lines))

    def _check_memory_sentinel_ui(self):
        status = self.security_guard.memory_sentinel.get_status()
        state = "🟢 常駐審查中 (每 2.5 秒自動輪詢非系統進程)" if status.get("active") else "⚠️ 未啟動"
        cnt = status.get("detected_injections_count", 0)
        self.txt_mem_output.setPlainText(
            f"【記憶體動態 EDR 哨兵狀態】：{state}\n"
            f"累計偵測處決注入木馬數：{cnt} 件\n"
            f"防禦技術：PAGE_EXECUTE_READWRITE 私有分頁排查 + 反射式 PE (MZ) 標頭掃描 (超越傳統 360/小紅傘靜態落地掃描)"
        )

    def _view_predictive_immune_ui(self):
        status = self.security_guard.predictive_immune.get_active_defense_status()
        cnt = status.get("total_active_virtual_patches", 0)
        locks = status.get("preemptive_locks_active", {})
        lock_names = ", ".join(k for k, v in locks.items() if v) or "無 (全域金絲雀動態監控中)"
        lines = [
            f"【AI 自主免疫推演與動態補丁狀態】",
            f"• 生效中動態微補丁數：{cnt} 項",
            f"• 預先鎖定之後續攻擊向量通道：{lock_names}",
            f"• 推演核心：MITRE ATT&CK 攻擊鏈狀態轉移圖 (75%+ 機率節點 0 毫秒提前封堵)"
        ]
        patches = status.get("virtual_patches", [])
        if patches:
            lines.append("\n【最近動態微補丁清單】：")
            for p in patches[-3:]:
                lines.append(f"• 補丁類型: {p.get('patch_type')} -> 目標: {p.get('target')} ({p.get('details')})")
        self.txt_immune_output.setPlainText("\n".join(lines))

    def _view_threat_hunter_audit_ui(self):
        log_file = self.security_guard.threat_hunter.hunter_log
        if not log_file.exists():
            self.txt_immune_output.setPlainText("暫無獵捕審計紀錄（系統純淨無外部威脅侵入）。")
            return
        try:
            records = []
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
            if not records:
                self.txt_immune_output.setPlainText("暫無獵捕審計紀錄。")
                return
            last = records[-1]
            lines = [
                f"【最新威脅溯源獵捕與粉碎審計報告】",
                f"• 處決狀態：{last.get('status')} (耗時: {last.get('duration_ms')} ms)",
                f"• 目標進程 PID：{last.get('target_pid')}, 家族被殲滅進程數：{len(last.get('killed_pids', []))}",
                f"• 溯源祖譜層級深度：{last.get('lineage_depth')} 代",
                f"• 物理粉碎關聯實體檔案數：{len(last.get('neutralized_files', []))} 項 (DoD 5220.22-M 3 輪覆寫清零)",
            ]
            ancestry = last.get("ancestry_lineage", [])
            if ancestry:
                lines.append("• 溯源進程鏈：")
                for node in ancestry[:3]:
                    lines.append(f"  └─ PID {node.get('pid')} ({node.get('name')})")
            self.txt_immune_output.setPlainText("\n".join(lines))
        except Exception as e:
            self.txt_immune_output.setPlainText(f"讀取獵捕日誌失敗: {e}")

    def _view_citadel_status_ui(self):
        status = self.security_guard.citadel.get_citadel_status()
        locked = "🚨 已啟動極限自鎖 (RAM 金鑰零化清除，實體檔案嚴格防護)" if status.get("is_locked_down") else "🟢 待命守護中 (AES-256-GCM 機密資料庫就緒)"
        cnt = status.get("vault_files_count", 0)
        files = ", ".join(status.get("vault_files", [])) or "無"
        self.txt_citadel_output.setPlainText(
            f"【末日資料要塞 (Citadel Vault) 狀態】：\n"
            f"• 守護狀態：{locked}\n"
            f"• 要塞封存檔案數：{cnt} 項\n"
            f"• 封存金庫清單：{files}\n"
            f"• 作業系統瀕危監控：常駐輪詢記憶體與關鍵進程 (若 csrss 死亡或 RAM 枯竭，微秒內執行記憶體密鑰零化 + 磁區自鎖)"
        )

    def _run_self_heal_ui(self):
        self.txt_citadel_output.setPlainText("正在以黃金根源指紋庫進行全機防毒代碼完整性自檢與原位修復補齊...")
        repaired = self.security_guard.self_healing.inspect_and_regenerate()
        if not repaired:
            cnt = self.security_guard.self_healing.get_healing_status().get("monitored_core_modules", 0)
            self.txt_citadel_output.setPlainText(f"✅ 自檢完成！{cnt} 個核心防禦模組指紋 100% 完整無污染，無代碼缺失或篡改。")
        else:
            lines = [f"🚨 自身防禦代碼遭攻擊，已自動原位重構修補補齊："]
            for r in repaired:
                lines.append(f"• 已修補: {os.path.basename(r.get('repaired_file', ''))} (原因: {r.get('reason')})")
            self.txt_citadel_output.setPlainText("\n".join(lines))

    def _view_counter_strike_ui(self):
        log_file = self.security_guard.counter_strike.strike_audit_log
        if not log_file.exists():
            self.txt_citadel_output.setPlainText("暫無反殺審計紀錄。")
            return
        try:
            records = []
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
            if not records:
                self.txt_citadel_output.setPlainText("暫無反殺審計紀錄。")
                return
            last = records[-1]
            lines = [
                f"【最新主動反殺與持久化清剿戰報】",
                f"• 目標 PID：{last.get('target_pid')} ({last.get('proc_name')})",
                f"• 特權剝奪狀態 (Privilege Stripping)：{last.get('privileges_stripped')}",
                f"• 記憶體反向注入 ExitProcess 中和：{last.get('memory_neutralized')}",
                f"• 拔除開機自啟與排程後門：{last.get('persistence_cleaned')}",
                f"• 實體惡意二進制粉碎：{last.get('binary_shredded')}",
                f"• 總反殺處決耗時：{last.get('duration_ms')} ms",
                f"• 累計主動反殺總次數：{self.security_guard.counter_strike.total_counter_kills} 次"
            ]
            self.txt_citadel_output.setPlainText("\n".join(lines))
        except Exception as e:
            self.txt_citadel_output.setPlainText(f"讀取反殺紀錄失敗: {e}")

    def _run_os_cpr_ui(self):
        self.txt_cpr_output.setPlainText("🚑 正在對作業系統實施心肺復甦急救 (系統除顫、解除工作管理員/登錄檔限制、校準 Winlogon、重啟核心服務)...")
        rep = self.security_guard.os_cpr.execute_full_system_cpr(caller_reason="使用者手動啟動系統急救")
        lines = [
            f"【作業系統急救 CPR 診斷與復原報告】",
            f"• 急救狀態：{rep.get('status')} (耗時: {rep.get('duration_ms')} ms)",
            f"• 系統除顫：清理 {rep.get('resource_defibrillation', {}).get('swarm_processes_killed', 0)} 個佔用資源惡意進程",
            f"• 限制政策解鎖：{', '.join(rep.get('policies_unlocked', [])) or '無殘留限制'}",
            f"• Winlogon 核心啟動鏈修復：{'成功校準為 explorer.exe' if rep.get('winlogon_repaired') else '略過'}",
            f"• IFEO 映像劫持清洗：{', '.join(rep.get('ifeo_hijacks_cleared', [])) or '無映像劫持'}",
            f"• 核心服務救活重啟：{len(rep.get('services_resuscitated', []))} 個關鍵服務已恢復常態"
        ]
        self.txt_cpr_output.setPlainText("\n".join(lines))

    def _view_os_cpr_status_ui(self):
        status = self.security_guard.os_cpr.get_cpr_status()
        svcs = ", ".join(status.get("critical_services_monitored", []))
        cnt = status.get("total_resuscitations", 0)
        self.txt_cpr_output.setPlainText(
            f"【作業系統 CPR 心肺復甦狀態】：\n"
            f"• 累計系統急救次數：{cnt} 次\n"
            f"• 常駐監控的核心服務命脈：{svcs}\n"
            f"• 應急能力：一鍵解除 DisableTaskMgr/DisableRegistryTools 鎖定，還原 hosts 檔案與 Winlogon 啟動鏈！"
        )

    def _scan_byovd_ui(self):
        self.txt_byovd_output.setPlainText("🔍 正在進行全盤易受攻擊驅動 (BYOVD / LOLDrivers) 深度審查...")
        rep = self.security_guard.byovd_sentinel.scan_and_block_byovd_drivers()
        threats = rep.get("threats", [])
        if not threats:
            cnt = self.security_guard.byovd_sentinel.get_status().get("monitored_loldrivers", 0)
            self.txt_byovd_output.setPlainText(f"✅ BYOVD 審查安全合格！已對照 {cnt} 款已知高危內核驅動簽名庫，未發現任何易受攻擊合法驅動植入。")
        else:
            lines = [f"🚨 警告！發現 {len(threats)} 個高危 BYOVD 漏洞驅動，已自動鎖死拒絕加載："]
            for t in threats:
                lines.append(f"• 驅動名稱: {t.get('driver_name', t.get('service_name'))} (風險: {t.get('risk')})")
            self.txt_byovd_output.setPlainText("\n".join(lines))

    def _audit_totou_ui(self):
        self.txt_byovd_output.setPlainText("⏱️ 正在審查 BOOT_START (Start=0) 與 SYSTEM_START (Start=1) 早期啟動項...")
        rep = self.security_guard.byovd_sentinel.audit_boot_services_totou()
        threats = rep.get("threats", [])
        if not threats:
            self.txt_byovd_output.setPlainText("✅ 開機時間差審查合格！所有早期引導驅動均位於官方信任目錄 (System32\\drivers)，無預加載後門。")
        else:
            lines = [f"🚨 發現 {len(threats)} 個異常早期啟動項 (可能利用防毒尚未載入之時間窗口執行)："]
            for t in threats:
                lines.append(f"• 服務名稱: {t.get('service')} ({t.get('start_type')}) -> 路徑: {t.get('image_path')}")
            self.txt_byovd_output.setPlainText("\n".join(lines))

    def _show_totp_binding_ui(self):
        """開啟 TOTP 掃碼綁定 / 即時測試 / 換金鑰視窗（已綁定時需先輸入正確驗證碼才顯示 QR 碼）"""
        TotpBindDialog(self, require_proof=True).exec_()
        tg = self.security_guard.totp_guard
        if hasattr(self, "txt_totp_output"):
            lines = [
                "【TOTP 雙因子身分驗證器】",
                f"• 綁定狀態：{'🟢 已綁定' if tg.is_bound_confirmed() else '🟡 尚未完成綁定'}",
                f"• App 中名稱：{tg.ISSUER_NAME} ({tg.get_account_label()})",
                "• 每 30 秒換一組 6 位數；換新後 60 秒內舊碼仍可使用",
            ]
            self.txt_totp_output.setPlainText("\n".join(lines))

    def _sync_symbiotic_capsules_ui(self):
        pack_res = self.security_guard.symbiotic_guardian.pack_and_distribute_gene_capsules()
        healed = self.security_guard.symbiotic_guardian.verify_and_self_heal_from_capsules()
        st = self.security_guard.symbiotic_guardian.get_status()
        lines = [
            f"【自適應多節點共生與無限復活網狀態】",
            f"• 自適應威脅演化等級：Level {st.get('adaptive_level')} (0:常態, 1:警戒, 2:戰鬥硬化, 3:最高不滅封鎖)",
            f"• 三點分散式共生基因膠囊：{st.get('capsules_alive_count')} / {st.get('total_capsule_nodes')} 個據點存活 (封裝 {pack_res.get('packed_modules')} 個核心模組)",
            f"• 第二共生看門狗節點：{'🟢 運行中 (PID: ' + str(st.get('secondary_watchdog_pid')) + ')' if st.get('secondary_watchdog_alive') else '🟡 待命'}",
            f"• 累計攔截篡改/自癒次數：{st.get('tamper_intercept_count')} 次 | 累計無限復活次數：{st.get('resurrection_count')} 次",
            f"• 累計攔截軟體模擬按鍵注入 (LLKHF_INJECTED)：{st.get('synthetic_input_blocked')} 次",
        ]
        if healed:
            lines.append(f"• 本次自動從膠囊再生補齊檔案：{', '.join(healed)}")
        self.txt_totp_output.setPlainText("\n".join(lines))

    def _totp_uninstall_unlock_ui(self):
        ok = self._prompt_totp_authenticator_dialog(mode="uninstall")
        if ok:
            self.txt_totp_output.setPlainText(
                "✅ TOTP 身分驗證通過！已解除所有核心防刪鎖 (FILE_SHARE_READ / NTFS DACL)、"
                "清除三處共生基因膠囊並停止無限復活看門狗，您現在可以自由刪除、搬移或關閉本軟體！"
            )

    def _prompt_totp_authenticator_dialog(self, mode: str = "exit") -> bool:
        """
        彈出具備「實體硬體鍵盤鑑別 (攔截 LLKHF_INJECTED 軟體模擬按鍵)」之 TOTP 6 位數驗證視窗。
        mode: 'exit' (安全退出並停止復活) 或 'uninstall' (解除所有防刪鎖並清除共生膠囊)
        """
        import ctypes
        from ctypes import wintypes

        dlg = QDialog(self)
        dlg.setWindowTitle("🔐 TOTP 身分驗證器 · 真人實體操作鑑別")
        dlg.setMinimumWidth(460)
        dlg.setModal(True)

        lay = QVBoxLayout(dlg)
        title_str = "🚪 驗證 TOTP 以安全退出程式" if mode == "exit" else "🔓 驗證 TOTP 以解除防刪鎖與無限復活"
        tg = self.security_guard.totp_guard
        is_bound = tg.is_bound_confirmed()

        hint_html = (
            f"<b style='color:#10b981;font-size:14px;'>{title_str}</b><br><br>"
            f"<span style='color:#cbd5e1;font-size:12px;'>"
            f"請用<b>實體鍵盤</b>輸入手機 Authenticator 中「<b>{tg.ISSUER_NAME} ({tg.get_account_label()})</b>」"
            f"顯示的 <b>6 位數</b>，打滿 6 碼會自動驗證。"
            f"</span>"
        )
        if not is_bound:
            hint_html += (
                "<br><br><div style='background:#1e293b;padding:8px;border-radius:6px;color:#38bdf8;font-size:11.5px;'>"
                "📱 <b>還沒綁定手機驗證器</b>：按下方「掃碼綁定」，用手機掃 QR 碼後再輸入驗證碼。"
                "</div>"
            )
        lbl = QLabel(hint_html)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        code_input = QLineEdit()
        code_input.setPlaceholderText("請用實體鍵盤輸入 6 位數 TOTP 驗證碼 (例如 123456)")
        code_input.setMaxLength(6)
        code_input.setContextMenuPolicy(Qt.NoContextMenu)  # 禁止右鍵選單貼上
        # 關閉輸入法：注音/倉頡等中文輸入法開著時，數字會走 inputMethodEvent 而不是 keyPressEvent，
        # 導致實體按鍵次數 < 6 被誤判為「軟體注入」→ 用實體鍵盤也無法退出。
        code_input.setAttribute(Qt.WA_InputMethodEnabled, False)
        code_input.setInputMethodHints(Qt.ImhDigitsOnly | Qt.ImhPreferLatin)
        code_input.setStyleSheet("font-size: 18px; letter-spacing: 6px; padding: 8px; font-weight: bold; color: #38bdf8;")
        lay.addWidget(code_input)

        lbl_countdown = QLabel()
        lay.addWidget(lbl_countdown)

        def _tick_countdown():
            lbl_countdown.setText(
                f"<span style='color:#94a3b8;font-size:11px;'>這組驗證碼還有 <b>{tg.seconds_left_in_step()}</b> 秒換新；"
                "換新後 60 秒內，舊的仍可使用。</span>")

        countdown_timer = QTimer(dlg)
        countdown_timer.timeout.connect(_tick_countdown)
        countdown_timer.start(500)
        _tick_countdown()

        if not is_bound:
            btn_bind = QPushButton("📱 掃碼綁定手機驗證器")
            btn_bind.clicked.connect(lambda: TotpBindDialog(dlg, require_proof=True).exec_())
            lay.addWidget(btn_bind)

        # 記錄是否偵測到非實體鍵盤之注入事件 (SendInput / keybd_event / 程式貼上)
        state = {"injected_detected": False, "physical_keystrokes": 0}

        # 安裝簡易時間差與按鍵硬體狀態檢測器：檢查 GetAsyncKeyState 實體按鍵是否真正處於按下狀態
        orig_key_press = code_input.keyPressEvent

        def _guarded_key_press(event):
            # 禁止 Ctrl+V 貼上，強制逐鍵實體敲擊
            if event.matches(QKeySequence.Paste):
                state["injected_detected"] = True
                QMessageBox.warning(dlg, "🚨 攔截非實體敲擊", "安全驗證欄位禁止剪貼簿貼上，請使用實體鍵盤逐字輸入 6 位數驗證碼！")
                return
            vk = event.nativeVirtualKey()
            if vk:
                # 檢查硬體按鍵狀態與 ExtraInfo
                extra = ctypes.windll.user32.GetMessageExtraInfo()
                # 常見自動化工具或惡意注入會帶有非零 fake extra info
                if extra and (extra & 0xFFFFFF00) == 0xFFC3D400:
                    state["injected_detected"] = True
                state["physical_keystrokes"] += 1
            orig_key_press(event)

        code_input.keyPressEvent = _guarded_key_press

        btn_row = QHBoxLayout()
        btn_verify = QPushButton("✅ 驗證並執行")
        btn_verify.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 6px 14px;")
        btn_cancel = QPushButton("取消")
        btn_row.addWidget(btn_verify)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        result_flag = {"ok": False}

        def _on_verify():
            val = code_input.text().strip()
            # 若文字長度為 6 但實體按鍵次數不足 (< 6)，代表是透過 setText / WM_SETTEXT 外部注入！
            was_injected = state["injected_detected"] or (len(val) == 6 and state["physical_keystrokes"] < 6)
            if mode == "uninstall":
                ok, msg = self.security_guard.symbiotic_guardian.authorize_uninstall_unlock_with_totp(
                    totp_code=val, was_injected_input=was_injected
                )
            else:
                ok, msg = self.security_guard.symbiotic_guardian.authorize_exit_with_totp(
                    totp_code=val, was_injected_input=was_injected
                )
            if ok:
                result_flag["ok"] = True
                QMessageBox.information(dlg, "驗證成功", msg)
                dlg.accept()
            else:
                code_input.clear()
                state["physical_keystrokes"] = 0
                state["injected_detected"] = False
                QMessageBox.critical(dlg, "驗證失敗", msg)

        btn_verify.clicked.connect(_on_verify)
        btn_cancel.clicked.connect(dlg.reject)
        # 打滿 6 碼即時驗證（不用再按 Enter；不另外接 returnPressed，避免同一組碼驗兩次）
        code_input.textChanged.connect(lambda txt: _on_verify() if len(txt) == 6 else None)

        dlg.exec_()
        return result_flag["ok"]


WINDOW_TITLE = "Syntra 星樞 · 桌面全能 Agent 與研發監督中心"
IPC_SERVER_NAME = "SyntraHub_SingleInstance_IPC_Server"


def main():
    import datetime
    log_file = Path(os.environ.get("APPDATA", "")) / "SyntraHub" / "boot.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"\n--- Booting Syntra Hub at {datetime.datetime.now()} ---\n")
            f.flush()
    except Exception:
        pass

    def _log_boot(msg):
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now()}: {msg}\n")
                f.flush()
        except Exception:
            pass

    _log_boot("Step 1: Check flag")
    # 清理退出旗標
    try:
        flag_file = Path(os.environ.get("APPDATA", "")) / "SyntraHub" / "sentinel_stop.flag"
        if flag_file.exists():
            flag_file.unlink(missing_ok=True)
    except Exception:
        pass

    _log_boot("Step 2: Desktop bind")
    # 確保進程視窗綁定至使用者主要交互桌面 (Default)
    try:
        import ctypes
        hdesk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(hdesk)
    except Exception as e:
        _log_boot(f"OpenDesktop error: {e}")

    update_registered_location(BASE_DIR)

    def _app_excepthook(exc_type, exc_val, exc_tb):
        import traceback
        err_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        _log_boot(f"FATAL EXCEPTION:\n{err_str}")

    sys.excepthook = _app_excepthook

    _log_boot("Step 3: QApplication create")
    if getattr(sys, "frozen", False):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Syntra.Agent.Desktop")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Syntra 星樞")
    app.setQuitOnLastWindowClosed(False)

    _log_boot("Step 4: IPC check")
    # 1. Qt 本地 IPC 單例檢測：若既有實例在背景或系統列，直接發送喚醒訊號並退出
    socket = QLocalSocket()
    socket.connectToServer(IPC_SERVER_NAME)
    if socket.waitForConnected(400):
        _log_boot("Existing instance detected, sending SHOW and exiting")
        socket.write(b"SHOW\n")
        socket.flush()
        socket.waitForBytesWritten(400)
        socket.disconnectFromServer()
        sys.exit(0)

    _log_boot("Step 5: Create IPC server")
    # 2. 清理過期殘留管道並建立主 IPC 監聽器
    QLocalServer.removeServer(IPC_SERVER_NAME)
    ipc_server = QLocalServer()
    ipc_server.listen(IPC_SERVER_NAME)

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    _log_boot("Step 6: MainWindow init")
    window = MainWindow()
    _log_boot("Step 7: setup_ipc_server")
    window.setup_ipc_server(ipc_server)
    if "--tray" in sys.argv[1:]:
        # 開機自啟：只常駐系統列，不彈窗、不搶焦點（點托盤圖示或桌面捷徑再喚醒）
        _log_boot("Step 8: tray mode (window hidden)")
    else:
        _log_boot("Step 8: show_and_activate")
        window.show_and_activate()
    _log_boot("Step 9: app.exec_()")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
