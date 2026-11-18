# -*- coding: utf-8 -*-
"""
快速輸入列：在任何畫面按全域熱鍵（預設 Ctrl+Shift+Space）就跳出一條輸入框，
打完按 Enter 直接交給 agent；Esc 或點到別處就收起來。類似 Spotlight / PowerToys Run。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QWidget


class QuickInputBar(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setObjectName("quickBar")
        self.setStyleSheet("""
            #quickBar { background: #0f172a; border: 2px solid #38bdf8; border-radius: 14px; }
            QLabel { color: #38bdf8; font-size: 20px; padding-left: 6px; }
            QLineEdit { background: transparent; border: none; color: #f8fafc; font-size: 18px; padding: 10px; }
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.addWidget(QLabel("✦"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("問 Syntra 任何事…（Enter 送出，Esc 關閉）")
        self.edit.returnPressed.connect(self._submit)
        lay.addWidget(self.edit, 1)
        self.resize(680, 64)

    def summon(self):
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.top() + geo.height() // 4)
        self.show()
        self.raise_()
        self.activateWindow()
        try:  # 熱鍵觸發時本行程剛收到輸入，Windows 允許我們把輸入框拉到前景
            import win32gui
            win32gui.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass
        self.edit.setFocus()
        self.edit.selectAll()

    def _submit(self):
        text = self.edit.text().strip()
        if text:
            self.edit.clear()
            self.hide()
            self.submitted.emit(text)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.ActivationChange and not self.isActiveWindow() and self.isVisible():
            self.hide()  # 點到別的視窗就收起來
