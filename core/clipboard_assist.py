# -*- coding: utf-8 -*-
"""
複製錯誤訊息 → 右下角跳出「要解釋嗎？」小卡片

接上既有但從未啟用的 core/semantic_clipboard_hud.py（剪貼簿監聽 + 本機分類器）：
- 只對「錯誤堆疊 / 例外訊息」這一類跳提示，其他類型不打擾。
- 卡片不搶焦點、8 秒後自動消失；打遊戲時、或是複製來源就是 agent 自己時不跳。
- 同一段內容 2 分鐘內不重複提示。
- 按「解釋並修正」才會把內容交給 agent，不會自動外傳任何剪貼簿內容。
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable, Optional

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

MAX_CHARS = 6_000
REPEAT_WINDOW = 120.0


class ClipboardToast(QWidget):
    accepted = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName("clipToast")
        self.setStyleSheet("""
            #clipToast { background:#111827; border:1px solid #f59e0b; border-radius:12px; }
            QLabel { color:#f8fafc; font-size:12.5px; }
            QPushButton { border-radius:6px; padding:5px 12px; font-weight:bold; }
            QPushButton#go { background:#f59e0b; color:#111827; }
            QPushButton#no { background:#334155; color:#e2e8f0; }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.title = QLabel()
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        row = QHBoxLayout()
        go, no = QPushButton("🛠 解釋並修正"), QPushButton("忽略")
        go.setObjectName("go")
        no.setObjectName("no")
        go.clicked.connect(self._accept)
        no.clicked.connect(self.hide)
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(go)
        lay.addLayout(row)
        self.setFixedWidth(360)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def popup(self, headline: str):
        self.title.setText(f"📋 偵測到你複製了錯誤訊息：<br><b>{headline[:90]}</b>")
        self.adjustSize()
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - self.width() - 20, geo.bottom() - self.height() - 20)
        self.show()
        self._timer.start(8000)

    def _accept(self):
        self.hide()
        self.accepted.emit()


class ClipboardAssist(QObject):
    """監聽剪貼簿（背景執行緒）→ 以 signal 回到 UI 執行緒顯示卡片。"""
    _sig_insight = pyqtSignal(dict, str)

    def __init__(self, on_explain: Callable[[str], None], is_busy: Optional[Callable[[], bool]] = None):
        super().__init__()
        self.on_explain = on_explain
        self.is_busy = is_busy or (lambda: False)
        self.toast = ClipboardToast()
        self.toast.accepted.connect(self._explain)
        self._pending_text = ""
        self._recent: dict = {}
        self._listener = None
        self._sig_insight.connect(self._show)

    def start(self) -> bool:
        try:
            from core.semantic_clipboard_hud import SemanticClipboardListener
        except Exception:
            return False
        listener = SemanticClipboardListener(callback=self._on_insight)
        self._listener = listener
        listener.start()
        return True

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    # 背景執行緒
    def _on_insight(self, insight: dict):
        if insight.get("type") != "error_traceback" or self._listener is None:
            return
        text = self._listener._get_clipboard_text() or ""
        if text.strip():
            self._sig_insight.emit(insight, text)

    # UI 執行緒
    def _show(self, insight: dict, text: str):
        if self.is_busy():
            return
        key = hashlib.sha1(text.strip().encode("utf-8", "replace")).hexdigest()
        now = time.time()
        if now - self._recent.get(key, 0) < REPEAT_WINDOW:
            return
        self._recent = {k: t for k, t in self._recent.items() if now - t < REPEAT_WINDOW}
        self._recent[key] = now
        self._pending_text = text[:MAX_CHARS]
        self.toast.popup(insight.get("headline") or "錯誤訊息")

    def _explain(self):
        if self._pending_text:
            self.on_explain(
                "我剛複製了下面這段錯誤訊息，請用繁體中文說明可能的原因，並給出具體的修正方法"
                "（若需要看相關檔案或執行指令再進一步確認，可以使用工具）：\n```\n" + self._pending_text + "\n```")
            self._pending_text = ""
