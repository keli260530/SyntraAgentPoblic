# -*- coding: utf-8 -*-
"""
代理的終端機面板：顯示這個代理（或和它串在一起的代理們）共用的 PowerShell 終端。
代理用 terminal_run 打的指令、輸出都會即時出現；你也可以自己在下方輸入指令。
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from core.agent_terminal import TerminalManager, TerminalSession

_STYLE = """
#termPanel { background: #0b0d13; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; }
#termPanel QLabel { color: #94a3b8; font-size: 11px; }
#termPanel QPlainTextEdit { background: #0b0d13; color: #d1d5db; border: none;
    font-family: Consolas, 'Cascadia Mono', monospace; font-size: 11.5px; }
#termPanel QLineEdit { background: #11141c; color: #e5e7eb; border: 1px solid rgba(255,255,255,0.08);
    border-radius: 4px; padding: 3px 6px; font-family: Consolas, monospace; font-size: 11.5px; }
#termPanel QPushButton { background: transparent; color: #94a3b8; border: none; padding: 2px 6px; font-size: 11px; }
#termPanel QPushButton:hover { color: #38bdf8; }
"""


class AgentTerminalWidget(QWidget):
    _sig_event = pyqtSignal(str, str, str)

    def __init__(self, agent_id: str, manager: TerminalManager,
                 name_of: Callable[[str], str] = lambda a: a, parent=None):
        super().__init__(parent)
        self.agent_id = agent_id
        self.manager = manager
        self.name_of = name_of
        self.session: Optional[TerminalSession] = None
        self.setObjectName("termPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(3)
        head = QHBoxLayout()
        self.lbl_title = QLabel()
        head.addWidget(self.lbl_title, 1)
        self.btn_stop = QPushButton("⏹ 中斷")
        self.btn_stop.setToolTip("中斷正在跑的指令（終端會重開，目前目錄保留）")
        self.btn_stop.clicked.connect(self._interrupt)
        self.btn_clear = QPushButton("清除畫面")
        self.btn_clear.clicked.connect(lambda: self.view.clear())
        head.addWidget(self.btn_stop)
        head.addWidget(self.btn_clear)
        lay.addLayout(head)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(3000)
        self.view.setFont(QFont("Consolas", 9))
        lay.addWidget(self.view, 1)

        self.input = QLineEdit()
        self.input.setPlaceholderText("PS> 在這個終端輸入指令，按 Enter 執行")
        self.input.returnPressed.connect(self._run_user_command)
        lay.addWidget(self.input)

        self._sig_event.connect(self._on_event)
        manager.on_change(self._rebind_threadsafe)
        self.rebind()

    # ------------------------------------------------ 綁定終端（串線後會換成共用的那個）
    def _rebind_threadsafe(self):
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self.rebind)

    def rebind(self):
        try:
            new = self.manager.session_for(self.agent_id)
        except Exception:
            return
        if new is not self.session:
            if self.session is not None:
                self.session.remove_listener(self._listener)
            self.session = new
            new.add_listener(self._listener)
            self.view.clear()
            for event, text, by in new.tail(400):
                self._on_event(event, text, by)
        self._update_title()

    def _update_title(self):
        group = self.manager.group_of(self.agent_id)
        cwd = self.session.cwd if self.session else ""
        if len(group) > 1:
            others = "、".join(self.name_of(a) for a in group if a != self.agent_id)
            self.lbl_title.setText(f"🔗 共用終端（和 {others}）· {cwd}")
        else:
            self.lbl_title.setText(f"🖥 終端 · {cwd}")

    def _listener(self, event: str, text: str, by: str):
        self._sig_event.emit(event, text, by)  # 從終端讀取執行緒轉回 UI 執行緒

    # ------------------------------------------------ 顯示
    def _append(self, html: str):
        self.view.moveCursor(QTextCursor.End)
        self.view.appendHtml(html)
        self.view.moveCursor(QTextCursor.End)

    @staticmethod
    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")

    def _on_event(self, event: str, text: str, by: str):
        if event == "cmd":
            who = "你" if by == "user" else self.name_of(by) if by else ""
            tag = f"<span style='color:#64748b'>[{self._esc(who)}]</span> " if who else ""
            first, *rest = text.splitlines() or [""]
            more = f"<span style='color:#64748b'> …（+{len(rest)} 行）</span>" if rest else ""
            self._append(f"{tag}<span style='color:#38bdf8'>PS&gt;</span> "
                         f"<span style='color:#f8fafc'>{self._esc(first)}</span>{more}")
        elif event == "out":
            self._append(self._esc(text) or "&nbsp;")
        elif event == "done":
            code, _, cwd = text.partition("|")
            if code.strip() not in ("0", ""):
                self._append(f"<span style='color:#f87171'>↳ 結束碼 {self._esc(code)}</span>")
            self._update_title()
        elif event == "info":
            self._append(f"<span style='color:#a78bfa'>{self._esc(text)}</span>")

    # ------------------------------------------------ 使用者操作
    def _run_user_command(self):
        cmd = self.input.text().strip()
        if not cmd:
            return
        self.input.clear()
        if cmd in ("cls", "clear"):
            self.view.clear()
            return
        threading.Thread(target=lambda: self.manager.run(self.agent_id, cmd, by="user", timeout=600),
                         daemon=True).start()

    def _interrupt(self):
        if self.session is not None:
            threading.Thread(target=self.session.interrupt, daemon=True).start()

    def detach(self):
        self.manager.off_change(self._rebind_threadsafe)
        if self.session is not None:
            self.session.remove_listener(self._listener)
            self.session = None
