# -*- coding: utf-8 -*-
"""
獨立軟體授權多選勾選視窗（AppConsentDialog）。

讓使用者在「掃描學習使用說明」與「正式打開畫面實測」前，
自由勾選哪些軟體願意授權、哪些不願意（不掃描／不測試），不寫死任何清單。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class AppConsentDialog(QDialog):
    """獨立的多選勾選彈窗，回傳使用者勾選允許的軟體與排除的軟體 key。"""

    def __init__(
        self,
        title: str,
        subtitle: str,
        apps: List[Dict[str, Any]],
        confirm_label: str = "確認執行勾選項目",
        phase: str = "scan",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(560, 480)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self._apps = list(apps)
        self._phase = phase
        self._items: List[Tuple[QListWidgetItem, Dict[str, Any]]] = []

        self.setStyleSheet(
            "QDialog { background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', 'Microsoft JhengHei'; }"
            "QLineEdit { background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 6px 10px; }"
            "QListWidget { background: #111827; color: #e2e8f0; border: 1px solid #1e293b; border-radius: 6px; padding: 4px; }"
            "QPushButton { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; padding: 6px 12px; }"
            "QPushButton:hover { background: #334155; }"
            "QPushButton#primary { background: #0284c7; border-color: #0284c7; font-weight: bold; }"
            "QPushButton#primary:hover { background: #0369a1; }"
        )

        root = QVBoxLayout(self)
        root.setSpacing(10)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        lbl_title.setWordWrap(True)
        root.addWidget(lbl_title)

        lbl_sub = QLabel(subtitle)
        lbl_sub.setStyleSheet("font-size: 12.5px; color: #94a3b8;")
        lbl_sub.setWordWrap(True)
        root.addWidget(lbl_sub)

        # 搜尋與全選列
        bar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜尋軟體名稱、出版商或路徑...")
        self.search_input.textChanged.connect(self._filter_items)
        bar.addWidget(self.search_input, 1)

        btn_all = QPushButton("全選")
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = QPushButton("全不選")
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        bar.addWidget(btn_all)
        bar.addWidget(btn_none)
        root.addLayout(bar)

        self.list_widget = QListWidget()
        for app in self._apps:
            name = str(app.get("name") or app.get("key") or "未命名軟體")
            src = str(app.get("source") or "")
            pub = str(app.get("publisher") or "")
            restricted = bool(app.get("chat_or_payment_restricted"))
            tag = " [僅學習，禁自動實測]" if (restricted and phase == "test") else ""
            label = f"{name}{tag}"
            if pub or src:
                label += f"\n    {pub} · {src}".strip(" ·")
            it = QListWidgetItem(label)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            if restricted and phase == "test":
                it.setCheckState(Qt.Unchecked)
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            else:
                it.setCheckState(Qt.Checked)
            self.list_widget.addItem(it)
            self._items.append((it, app))
        root.addWidget(self.list_widget, 1)

        self.chk_remember = QCheckBox("記住我未勾選的項目，以後不再詢問這些軟體")
        self.chk_remember.setChecked(True)
        self.chk_remember.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        root.addWidget(self.chk_remember)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btn_cancel = QPushButton("全部跳過 / 暫不執行")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton(confirm_label)
        btn_ok.setObjectName("primary")
        btn_ok.clicked.connect(self.accept)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)
        root.addLayout(btns)

    def _filter_items(self, text: str):
        q = (text or "").strip().lower()
        for it, app in self._items:
            hay = " ".join([
                str(app.get("name") or ""),
                str(app.get("key") or ""),
                str(app.get("publisher") or ""),
                str(app.get("launch_target") or ""),
            ]).lower()
            it.setHidden(bool(q) and q not in hay)

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for it, app in self._items:
            if not it.isHidden() and (it.flags() & Qt.ItemIsEnabled):
                it.setCheckState(state)

    def selected_and_skipped(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
        selected: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for it, app in self._items:
            if it.checkState() == Qt.Checked:
                selected.append(app)
            else:
                skipped.append(app)
        return selected, skipped, bool(self.chk_remember.isChecked())


def prompt_app_consent_blocking(
    title: str,
    subtitle: str,
    apps: List[Dict[str, Any]],
    confirm_label: str = "確認執行勾選項目",
    phase: str = "scan",
    parent=None,
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]]:
    """在 Qt 主執行緒安全彈出多選視窗；若無法取得 QApplication 則回傳 None 退回審批卡。"""
    try:
        from PyQt5.QtWidgets import QApplication
        app_inst = QApplication.instance()
        if app_inst is None:
            return None
        dlg = AppConsentDialog(
            title=title,
            subtitle=subtitle,
            apps=apps,
            confirm_label=confirm_label,
            phase=phase,
            parent=parent,
        )
        if dlg.exec_() == QDialog.Accepted:
            return dlg.selected_and_skipped()
        return ([], list(apps), bool(dlg.chk_remember.isChecked()))
    except Exception:
        return None
