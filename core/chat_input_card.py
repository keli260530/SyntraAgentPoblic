# -*- coding: utf-8 -*-
"""
Syntra 星樞 · 現代卡片式整合輸入框與指令補全組件 (ChatInputCard)
完全落實 OOP 與模組化架構，對齊 Antigravity / Cursor 頂級視覺與互動規範。
指令面板採用內嵌可收合式架構，杜絕懸浮視窗殘留桌面無法退出的問題。
"""
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QIcon, QImage, QKeyEvent, QPainter, QPixmap, QTextCursor
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.slash_commands import SlashCommandManager


class PromptTextEdit(QTextEdit):
    """
    無框無縫多行輸入框：
    1. 支援 Enter 送出、Shift+Enter 換行。
    2. 嚴格限縮偵測開頭 '/' 字元，防止在一般文字或檔案路徑中誤觸發。
    3. 攔截 ↑ / ↓ / Enter / Tab / Esc 鍵盤事件以導航或退出指令面板。
    """
    sig_send_requested = pyqtSignal()
    sig_slash_query = pyqtSignal(str)
    sig_slash_dismiss = pyqtSignal()
    sig_arrow_up = pyqtSignal()
    sig_arrow_down = pyqtSignal()
    sig_autocomplete_commit = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Ask anything, @ to mention, / for actions... (輸入 / 查看快捷指令，@ 提及上下文)")
        self.setStyleSheet("""
            QTextEdit {
                border: none;
                background: transparent;
                color: #f1f5f9;
                font-size: 13.5px;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Microsoft JhengHei', sans-serif;
                line-height: 1.45;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                padding: 4px 2px;
            }
        """)
        self.setMinimumHeight(38)
        self.setMaximumHeight(140)
        self.textChanged.connect(self._on_text_changed)
        self._popup_active = False
        # 使用者拖曳分隔線後改用固定高度；None 代表依內容自動長高
        self._manual_height: Optional[int] = None

    def set_manual_height(self, height: Optional[int]):
        """手動模式（拖曳分隔線用）：不限高度，填滿外層分到的空間；傳 None 恢復依內容自動長高"""
        if height is None:
            self._manual_height = None
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.setMinimumHeight(38)
            self.setMaximumHeight(140)
            self._on_text_changed()
            return
        self._manual_height = max(0, int(height))
        # 不設最小/最大值、忽略內容建議高度 → 分隔線往上往下都能自由拉
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)

    def set_popup_active(self, active: bool):
        self._popup_active = active

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        if self._popup_active:
            if key == Qt.Key_Down:
                self.sig_arrow_down.emit()
                return
            elif key == Qt.Key_Up:
                self.sig_arrow_up.emit()
                return
            elif key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab):
                self.sig_autocomplete_commit.emit()
                return
            elif key == Qt.Key_Escape:
                self.sig_slash_dismiss.emit()
                return

        # 正常輸入狀態下 Enter 送出，Shift+Enter 換行
        if key in (Qt.Key_Enter, Qt.Key_Return):
            if modifiers & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.sig_send_requested.emit()
            return

        super().keyPressEvent(event)

    def _on_text_changed(self):
        # 動態調整高度（使用者手動拖曳過高度時不自動調整）
        if self._manual_height is None:
            doc_height = int(self.document().size().height()) + 14
            new_height = max(38, min(140, doc_height))
            self.setFixedHeight(new_height)

        raw = self.toPlainText()
        if not raw:
            self.sig_slash_dismiss.emit()
            return

        # 嚴格規則：僅當整個輸入框以 '/' 開頭，且正在輸入指令本身（尚未輸入空格）時才觸發指令提示
        # 絕不在路徑 (C:/...)、網址 (https://...) 或內文斜線中誤觸發
        s = raw.lstrip()
        m = re.match(r"^/([a-zA-Z0-9_-]*)$", s)
        if m:
            query = m.group(1)
            self.sig_slash_query.emit(query)
        else:
            self.sig_slash_dismiss.emit()

    def replace_slash_command(self, cmd_text: str):
        """將輸入框開頭的指令替換為選定的指令並附帶空格"""
        self.setText(f"{cmd_text} ")
        new_cursor = self.textCursor()
        new_cursor.movePosition(QTextCursor.End)
        self.setTextCursor(new_cursor)


class AttachmentThumbnailChip(QFrame):
    """
    縮圖附件卡片 (對齊圖五左上角)
    支援圖片縮圖、檔案圖示、名稱與一鍵移除按鈕 '✕'
    """
    sig_remove = pyqtSignal(str)

    def __init__(self, item_id: str, label: str, icon_str: str = "📄", pixmap: Optional[QPixmap] = None, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.setStyleSheet("""
            QFrame {
                background: rgba(30, 41, 59, 0.85);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 2px 6px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        if pixmap and not pixmap.isNull():
            lbl_thumb = QLabel()
            lbl_thumb.setFixedSize(28, 28)
            lbl_thumb.setScaledContents(True)
            lbl_thumb.setPixmap(pixmap.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lbl_thumb.setStyleSheet("border-radius: 4px; border: 1px solid rgba(255,255,255,0.1);")
            layout.addWidget(lbl_thumb)
        else:
            lbl_icon = QLabel(icon_str)
            lbl_icon.setStyleSheet("font-size: 14px;")
            layout.addWidget(lbl_icon)

        short_label = label if len(label) <= 18 else label[:15] + "..."
        lbl_text = QLabel(short_label)
        lbl_text.setToolTip(label)
        lbl_text.setStyleSheet("color: #cbd5e1; font-size: 11.5px; font-weight: 500;")
        layout.addWidget(lbl_text)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(16, 16)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 11px;
                font-weight: bold;
                border-radius: 8px;
            }
            QPushButton:hover {
                background: #ef4444;
                color: #ffffff;
            }
        """)
        btn_close.clicked.connect(lambda: self.sig_remove.emit(self.item_id))
        layout.addWidget(btn_close)


class ChatInputCard(QFrame):
    """
    現代整合卡片式輸入容器 (對齊圖五設計)：
    - 頂部：縮圖與檔案預覽列 (可水平捲動、個別 '✕' 移除)
    - 中間：指令建議收合卡片 (嚴格觸發、即時過濾、內建 ✕ 關閉按鈕與 Esc 退出)
    - 下方：平滑多行文字輸入區 (無邊框、自適應行高)
    - 底部工具列：
        - 左側：[+] 上下文按鈕 (圖二選單)、[⚡ 指令] 快捷按鈕、模型切換器 (圖三選單)
        - 右側：執行/審批模式切換器 (圖四選單)、📸 快捷截圖、圓形藍色發送鍵 (➔)
    """
    sig_send_prompt = pyqtSignal(str)
    sig_request_files = pyqtSignal()
    sig_request_folder = pyqtSignal()
    sig_request_snap = pyqtSignal()
    sig_request_browser = pyqtSignal()
    sig_request_mentions = pyqtSignal()
    sig_model_changed = pyqtSignal(str)
    sig_mode_changed = pyqtSignal(str)
    sig_open_api_manager = pyqtSignal()
    sig_chip_removed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatInputCard")
        self.setStyleSheet("""
            QFrame#chatInputCard {
                background: #141722;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
            }
        """)

        self.card_layout = QVBoxLayout(self)
        self.card_layout.setContentsMargins(12, 8, 12, 8)
        self.card_layout.setSpacing(6)

        # 1. 頂部縮圖預覽列 (水平捲動)
        self.scroll_thumbs = QScrollArea()
        self.scroll_thumbs.setWidgetResizable(True)
        self.scroll_thumbs.setFixedHeight(38)
        self.scroll_thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_thumbs.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_thumbs.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.widget_thumbs = QWidget()
        self.layout_thumbs = QHBoxLayout(self.widget_thumbs)
        self.layout_thumbs.setContentsMargins(0, 0, 0, 0)
        self.layout_thumbs.setSpacing(6)
        self.layout_thumbs.addStretch()
        self.scroll_thumbs.setWidget(self.widget_thumbs)
        self.scroll_thumbs.hide()
        self.card_layout.addWidget(self.scroll_thumbs)

        # 2. 內嵌式指令建議面板 (不使用獨立懸浮 OS 視窗，永遠安全收合，附帶明確 ✕ 關閉按鈕)
        self.slash_container = QFrame()
        self.slash_container.setStyleSheet("""
            QFrame {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 10px;
            }
        """)
        self.slash_container.setMaximumHeight(190)
        slash_vbox = QVBoxLayout(self.slash_container)
        slash_vbox.setContentsMargins(8, 6, 8, 6)
        slash_vbox.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(4, 2, 4, 2)
        lbl_h = QLabel("⚡ 快捷指令庫 (輸入字母即時比對，↑↓ 選擇，Enter 帶入)")
        lbl_h.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        header_row.addWidget(lbl_h)
        header_row.addStretch()

        btn_close_slash = QPushButton("✕ 關閉 (Esc)")
        btn_close_slash.setFixedSize(76, 20)
        btn_close_slash.setCursor(Qt.PointingHandCursor)
        btn_close_slash.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                color: #94a3b8;
                border: none;
                border-radius: 4px;
                font-size: 10.5px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #ef4444;
                color: #ffffff;
            }
        """)
        btn_close_slash.clicked.connect(self.hide_slash_panel)
        header_row.addWidget(btn_close_slash)
        slash_vbox.addLayout(header_row)

        self.slash_list = QListWidget()
        self.slash_list.setStyleSheet("""
            QListWidget {
                border: none;
                background: transparent;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border-radius: 6px;
                padding: 4px 8px;
                color: #e2e8f0;
            }
            QListWidget::item:hover {
                background: rgba(56, 189, 248, 0.12);
            }
            QListWidget::item:selected {
                background: #0284c7;
                color: #ffffff;
            }
        """)
        self.slash_list.itemClicked.connect(self._on_list_item_clicked)
        slash_vbox.addWidget(self.slash_list)
        self.slash_container.hide()
        self.card_layout.addWidget(self.slash_container)

        # 3. 中間多行文字輸入框
        self.text_edit = PromptTextEdit()
        self.text_edit.sig_send_requested.connect(self._on_send_clicked)
        self.text_edit.sig_slash_query.connect(self._filter_and_show_slash)
        self.text_edit.sig_slash_dismiss.connect(self.hide_slash_panel)
        self.text_edit.sig_arrow_down.connect(self._select_next_slash)
        self.text_edit.sig_arrow_up.connect(self._select_prev_slash)
        self.text_edit.sig_autocomplete_commit.connect(self._commit_current_slash)
        self.card_layout.addWidget(self.text_edit, 1)

        # 4. 底部整合按鈕列
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 2, 0, 0)
        bottom_row.setSpacing(8)

        # 左側工具：[+] 上下文按鈕 (圖二)
        self.btn_context = QPushButton("+")
        self.btn_context.setFixedSize(26, 26)
        self.btn_context.setCursor(Qt.PointingHandCursor)
        self.btn_context.setToolTip("新增上下文：附加檔案、資料夾、提及或瀏覽器 (圖二)")
        self.btn_context.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.2);
                border-color: #38bdf8;
                color: #ffffff;
            }
        """)
        self.btn_context.clicked.connect(self._show_add_context_menu)
        bottom_row.addWidget(self.btn_context)

        # 左側快捷：[⚡ 指令] 捷徑按鈕 (方便直接瀏覽或開關指令清單)
        self.btn_slash_quick = QPushButton("⚡ 指令")
        self.btn_slash_quick.setFixedHeight(26)
        self.btn_slash_quick.setCursor(Qt.PointingHandCursor)
        self.btn_slash_quick.setToolTip("查看或切換常用快捷指令庫")
        self.btn_slash_quick.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                color: #94a3b8;
                font-size: 11.5px;
                padding: 0 8px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.15);
                color: #38bdf8;
                border-color: #38bdf8;
            }
        """)
        self.btn_slash_quick.clicked.connect(self._toggle_slash_panel_manual)
        bottom_row.addWidget(self.btn_slash_quick)

        # 左側工具：模型選取器 (圖三)
        self.btn_model = QPushButton("🤖 智慧自動路由 ▾")
        self.btn_model.setFixedHeight(26)
        self.btn_model.setCursor(Qt.PointingHandCursor)
        self.btn_model.setToolTip("切換目前使用的 AI 模型 (圖三)")
        self.btn_model.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #cbd5e1;
                font-size: 12.5px;
                font-weight: 500;
                padding: 0 4px;
            }
            QPushButton:hover {
                color: #38bdf8;
            }
        """)
        self.btn_model.clicked.connect(self._show_model_menu)
        bottom_row.addWidget(self.btn_model)

        bottom_row.addStretch(1)

        # 右側工具：執行/審批模式切換 (圖四)
        self.btn_mode = QPushButton("🛡️ Turbo ▾")
        self.btn_mode.setFixedHeight(26)
        self.btn_mode.setCursor(Qt.PointingHandCursor)
        self.btn_mode.setToolTip("設定指令審批與執行防護層級 (圖四)")
        self.btn_mode.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #94a3b8;
                font-size: 12px;
                font-weight: 500;
                padding: 0 4px;
            }
            QPushButton:hover {
                color: #38bdf8;
            }
        """)
        self.btn_mode.clicked.connect(self._show_mode_menu)
        bottom_row.addWidget(self.btn_mode)

        # 右側快捷：📸 截圖按鈕
        self.btn_snap_quick = QPushButton("📸")
        self.btn_snap_quick.setFixedSize(26, 26)
        self.btn_snap_quick.setCursor(Qt.PointingHandCursor)
        self.btn_snap_quick.setToolTip("即時擷取右側視窗畫面附加到此對話")
        self.btn_snap_quick.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }
        """)
        self.btn_snap_quick.clicked.connect(self.sig_request_snap.emit)
        bottom_row.addWidget(self.btn_snap_quick)

        # 右側核心：圓形藍色發送鍵 (↑ 送出 / ■ 終止，使用向量 QIcon 避免字型/ClearType 殘影)
        self.btn_send = QPushButton("")
        self.btn_send.setFixedSize(30, 30)
        self.btn_send.setCursor(Qt.PointingHandCursor)
        self.btn_send.setIconSize(QSize(18, 18))
        self.btn_send.clicked.connect(self._on_send_clicked)
        bottom_row.addWidget(self.btn_send)
        self.set_running(False)

        self.card_layout.addLayout(bottom_row)

        # 狀態資料
        self._attached_chips: Dict[str, AttachmentThumbnailChip] = {}
        self._current_model_id = "auto_router"
        self._available_models: List[Dict[str, Any]] = []
        self._current_mode = "turbo"
        self._all_commands = SlashCommandManager.get_command_list()

    # ================= 指令內嵌面板控制 =================

    def hide_slash_panel(self):
        """徹底隱藏並重置指令補全面板"""
        self.slash_container.hide()
        self.text_edit.set_popup_active(False)

    def _toggle_slash_panel_manual(self):
        if self.slash_container.isVisible():
            self.hide_slash_panel()
        else:
            self._filter_and_show_slash("")

    def _filter_and_show_slash(self, query: str):
        q = query.lower().strip()
        matched = []

        for item in self._all_commands:
            cmd = item.get("cmd", "")
            title = item.get("title", "")
            desc = item.get("desc", "")
            badge = item.get("badge", "")

            if not q or cmd.lower().startswith("/" + q) or cmd.lower().startswith(q):
                matched.append((0, item))
            elif q in title.lower() or q in desc.lower() or q in badge.lower():
                matched.append((1, item))

        matched.sort(key=lambda x: x[0])

        self.slash_list.clear()
        if not matched:
            self.hide_slash_panel()
            return

        for _, item in matched:
            cmd_str = item.get("cmd")
            title_str = item.get("title")
            desc_str = item.get("desc")

            list_item = QListWidgetItem(self.slash_list)
            list_item.setSizeHint(QSize(400, 36))
            list_item.setData(Qt.UserRole, cmd_str)

            container = QWidget()
            c_layout = QVBoxLayout(container)
            c_layout.setContentsMargins(4, 1, 4, 1)
            c_layout.setSpacing(1)

            top_row = QLabel(f"<b><span style='color: #38bdf8;'>{cmd_str}</span></b> &nbsp; <span style='color: #cbd5e1; font-size: 11px;'>{title_str}</span>")
            sub_row = QLabel(desc_str)
            sub_row.setStyleSheet("color: #94a3b8; font-size: 10px;")

            c_layout.addWidget(top_row)
            c_layout.addWidget(sub_row)
            self.slash_list.setItemWidget(list_item, container)

        self.slash_list.setCurrentRow(0)
        self.slash_container.show()
        self.text_edit.set_popup_active(True)

    def _select_next_slash(self):
        cur = self.slash_list.currentRow()
        count = self.slash_list.count()
        if count > 0:
            self.slash_list.setCurrentRow((cur + 1) % count)

    def _select_prev_slash(self):
        cur = self.slash_list.currentRow()
        count = self.slash_list.count()
        if count > 0:
            self.slash_list.setCurrentRow((cur - 1 + count) % count)

    def _commit_current_slash(self):
        item = self.slash_list.currentItem()
        if item:
            cmd = item.data(Qt.UserRole)
            if cmd:
                self.text_edit.replace_slash_command(cmd)
        self.hide_slash_panel()
        self.text_edit.setFocus()

    def _on_list_item_clicked(self, item):
        cmd = item.data(Qt.UserRole)
        if cmd:
            self.text_edit.replace_slash_command(cmd)
        self.hide_slash_panel()
        self.text_edit.setFocus()

    # ================= 縮圖預覽列管理 =================

    def add_thumbnail_chip(self, item_id: str, label: str, icon_str: str = "📄", pixmap: Optional[QPixmap] = None):
        """新增一個縮圖晶片至頂部列"""
        if item_id in self._attached_chips:
            return

        chip = AttachmentThumbnailChip(item_id, label, icon_str, pixmap, self.widget_thumbs)
        chip.sig_remove.connect(self.remove_thumbnail_chip)

        self._attached_chips[item_id] = chip
        self.layout_thumbs.insertWidget(self.layout_thumbs.count() - 1, chip)
        self.scroll_thumbs.show()

    def remove_thumbnail_chip(self, item_id: str):
        """移除單一縮圖晶片並向外通知宿主釋放資源"""
        if item_id in self._attached_chips:
            chip = self._attached_chips.pop(item_id)
            self.layout_thumbs.removeWidget(chip)
            chip.deleteLater()
            self.sig_chip_removed.emit(item_id)

        if not self._attached_chips:
            self.scroll_thumbs.hide()

    def clear_all_chips(self):
        """清空所有縮圖晶片"""
        for chip in list(self._attached_chips.values()):
            self.layout_thumbs.removeWidget(chip)
            chip.deleteLater()
        self._attached_chips.clear()
        self.scroll_thumbs.hide()

    # ================= 選單觸發邏輯 =================

    def _show_add_context_menu(self):
        """彈出「Add Context」選單 (圖二)"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181d28;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
                color: #e2e8f0;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background: #0284c7;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        act_title = QAction("Add Context", menu)
        act_title.setEnabled(False)
        menu.addAction(act_title)
        menu.addSeparator()

        act_files = QAction("📎 Files (附加多個檔案)", menu)
        act_files.triggered.connect(self.sig_request_files.emit)
        menu.addAction(act_files)

        act_folder = QAction("📁 Folder (指定工作資料夾)", menu)
        act_folder.triggered.connect(self.sig_request_folder.emit)
        menu.addAction(act_folder)

        act_mentions = QAction("@ Mentions (提及監控視窗或檔案)", menu)
        act_mentions.triggered.connect(self.sig_request_mentions.emit)
        menu.addAction(act_mentions)

        act_actions = QAction("↗️ Actions (即時螢幕截圖)", menu)
        act_actions.triggered.connect(self.sig_request_snap.emit)
        menu.addAction(act_actions)

        act_browser = QAction("🌐 Browser (深度網頁瀏覽與分析)", menu)
        act_browser.triggered.connect(self.sig_request_browser.emit)
        menu.addAction(act_browser)

        pos = self.btn_context.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        menu.exec_(pos)

    def set_available_models(self, catalog: List[Dict[str, Any]], current_selected: str):
        """接收 ApiManager 解析出的可用模型清單並更新狀態"""
        self._available_models = catalog
        self._current_model_id = current_selected or "auto_router"

        display = "🤖 智慧自動路由"
        for m in catalog:
            if m.get("full_id") == self._current_model_id:
                display = m.get("display_name", display)
                break
        self.btn_model.setText(f"{display} ▾")

    def _show_model_menu(self):
        """彈出「Model」可用模型選單 (圖三)"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181d28;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
                color: #e2e8f0;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background: #0284c7;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        act_title = QAction("Model", menu)
        act_title.setEnabled(False)
        menu.addAction(act_title)
        menu.addSeparator()

        is_auto = (self._current_model_id == "auto_router")
        act_auto = QAction(f"{'✓ ' if is_auto else '    '}🤖 智慧自動路由 (動態分配視覺/推理/代碼)", menu)
        act_auto.triggered.connect(lambda: self._select_model("auto_router", "🤖 智慧自動路由"))
        menu.addAction(act_auto)

        if self._available_models:
            menu.addSeparator()
            for m in self._available_models:
                m_id = m.get("full_id")
                m_name = m.get("display_name")
                tag = "🟢" if m.get("has_key") else "⚪"
                is_sel = (self._current_model_id == m_id)
                check_str = "✓ " if is_sel else "    "
                act = QAction(f"{check_str}{tag} {m_name}", menu)
                act.triggered.connect(lambda checked, mid=m_id, name=m_name: self._select_model(mid, name))
                menu.addAction(act)
        else:
            menu.addSeparator()
            presets = [
                ("gemini-2.5-flash", "Gemini 2.5 Flash"),
                ("gemini-2.5-pro", "Gemini 2.5 Pro"),
                ("gpt-4o", "OpenAI GPT-4o"),
                ("claude-3-7-sonnet", "Claude 3.7 Sonnet"),
                ("deepseek-chat", "DeepSeek V3"),
            ]
            for p_id, p_name in presets:
                is_sel = (self._current_model_id == p_id)
                check_str = "✓ " if is_sel else "    "
                act = QAction(f"{check_str}⚡ {p_name}", menu)
                act.triggered.connect(lambda checked, mid=p_id, name=p_name: self._select_model(mid, name))
                menu.addAction(act)

        menu.addSeparator()
        act_settings = QAction("⚙️ View Usage / API 設定與金鑰管理...", menu)
        act_settings.triggered.connect(self.sig_open_api_manager.emit)
        menu.addAction(act_settings)

        pos = self.btn_model.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        menu.exec_(pos)

    def _select_model(self, model_id: str, display_name: str):
        self._current_model_id = model_id
        clean_name = display_name.replace("🤖 ", "").replace("⚡ ", "")
        self.btn_model.setText(f"{clean_name} ▾")
        self.sig_model_changed.emit(model_id)

    def _show_mode_menu(self):
        """彈出執行/審批模式選單 (圖四)"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #181d28;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 4px;
                color: #e2e8f0;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background: #0284c7;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        modes = [
            ("request_review", "🛡️ Request Review", "Every command requires approval. (每次指令皆需手動審查)"),
            ("default", "🛡️ Default", "Ask before sensitive operations. (標準防護，攔截敏感操作)"),
            ("auto", "🛡️ Auto (Preview)", "Automatically decide if commands run. (智慧評估安全判定)"),
            ("turbo", "🛡️ Turbo", "Run all commands without restrictions. (極速無阻自動推進)"),
        ]

        for m_key, m_title, m_desc in modes:
            is_sel = (self._current_mode == m_key)
            check_str = "✓ " if is_sel else "    "
            act = QAction(f"{check_str}{m_title}\n    {m_desc}", menu)
            act.triggered.connect(lambda checked, k=m_key, t=m_title: self._select_mode(k, t))
            menu.addAction(act)

        pos = self.btn_mode.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        menu.exec_(pos)

    def set_execution_mode(self, mode_key: str):
        """外部設定執行模式並同步更新按鈕文字"""
        mode_titles = {
            "request_review": "Request Review",
            "default": "Default",
            "auto": "Auto",
            "turbo": "Turbo",
        }
        self._current_mode = mode_key
        t = mode_titles.get(mode_key, "Default")
        self.btn_mode.setText(f"🛡️ {t} ▾")

    def _select_mode(self, mode_key: str, mode_title: str):
        self._current_mode = mode_key
        short_title = mode_title.split()[1] if len(mode_title.split()) > 1 else mode_title
        self.btn_mode.setText(f"🛡️ {short_title} ▾")
        self.sig_mode_changed.emit(mode_key)

    @staticmethod
    def _make_send_or_stop_icon(running: bool) -> QIcon:
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        if running:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(9, 9, 14, 14, 2, 2)
        else:
            from PyQt5.QtGui import QPen
            pen = QPen(QColor("#ffffff"), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(16, 24, 16, 8)
            p.drawLine(10, 14, 16, 8)
            p.drawLine(22, 14, 16, 8)
        p.end()
        return QIcon(pm)

    def set_running(self, running: bool):
        """切換送出 (↑) 與終止 (■) 狀態，確保單一圖示置中不重疊。"""
        self.btn_send.setText("")
        self.btn_send.setIcon(self._make_send_or_stop_icon(running))
        if running:
            self.btn_send.setToolTip("停止這一輪（不會鎖定 agent）")
            self.btn_send.setStyleSheet(
                "QPushButton { background: #334155; border: 1px solid #475569; border-radius: 15px; padding: 0px; }"
                "QPushButton:hover { background: #475569; }"
                "QPushButton:pressed { background: #1e293b; }"
            )
        else:
            self.btn_send.setToolTip("送出指令 (Enter)")
            self.btn_send.setStyleSheet(
                "QPushButton { background: #0284c7; border: none; border-radius: 15px; padding: 0px; }"
                "QPushButton:hover { background: #0369a1; }"
                "QPushButton:pressed { background: #075985; }"
            )
        self.btn_send.repaint()

    def _on_send_clicked(self):
        self.hide_slash_panel()
        text = self.text_edit.toPlainText().strip()
        self.sig_send_prompt.emit(text)

    def clear_text(self):
        self.text_edit.clear()
        self.hide_slash_panel()

    def set_text(self, text: str):
        self.text_edit.setText(text)
        self.text_edit.setFocus()
