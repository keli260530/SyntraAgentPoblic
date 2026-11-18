# -*- coding: utf-8 -*-
"""代理用量條：顯示上下文占用（這一輪送出的 token ÷ 模型上下文上限）與累計用量。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QSizePolicy, QWidget

from core.agent_team import fmt_tokens
from ui.font_scaler import current_app_scale


def usage_color(ratio: float) -> QColor:
    if ratio >= 0.85:
        return QColor("#ef4444")
    if ratio >= 0.6:
        return QColor("#f59e0b")
    return QColor("#22c55e")


def usage_text(u: Optional[Dict[str, Any]], compact: bool = False) -> str:
    if not u or not u.get("calls"):
        return "尚未使用" if not compact else "—"
    est = "≈" if u.get("estimated") else ""
    ctx = f"{est}{fmt_tokens(u['context_tokens'])}/{fmt_tokens(u['context_limit'])}"
    if compact:
        return f"{ctx} {u['ratio']:.0%}"
    return f"上下文 {ctx}（{u['ratio']:.0%}）· 累計 {fmt_tokens(u['input_total'] + u['output_total'])}"


def usage_tooltip(u: Optional[Dict[str, Any]]) -> str:
    if not u or not u.get("calls"):
        return "這個代理還沒呼叫過模型"
    lines = [
        f"模型：{u.get('model') or '未知'}",
        f"上下文占用：{u['context_tokens']:,} / {u['context_limit']:,} tokens（{u['ratio']:.0%}）",
        f"累計輸入：{u['input_total']:,} tokens",
        f"累計輸出：{u['output_total']:,} tokens",
        f"模型呼叫次數：{u['calls']}",
    ]
    if u.get("estimated"):
        lines.append("（這個模型沒有回報用量，數字為估算值）")
    if u["ratio"] >= 0.85:
        lines.append("⚠️ 上下文快滿了：舊對話會被自動摘要，回答品質可能下降")
    return "\n".join(lines)


class UsageBar(QWidget):
    """細長的用量條；compact=True 時只畫條（給分頁用），否則條＋文字。"""

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.compact = compact
        self.usage: Optional[Dict[str, Any]] = None
        self.setFixedHeight(4 if compact else 16)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(usage_tooltip(None))

    def set_usage(self, usage: Optional[Dict[str, Any]]):
        self.usage = usage
        self.setToolTip(usage_tooltip(usage))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ratio = float((self.usage or {}).get("ratio") or 0.0)
        h = 4 if self.compact else 5
        y = 0 if self.compact else self.height() - h
        track = QRectF(0, y, self.width(), h)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(track, 2, 2)
        if ratio > 0:
            p.setBrush(usage_color(ratio))
            p.drawRoundedRect(QRectF(0, y, max(3.0, self.width() * ratio), h), 2, 2)
        if not self.compact:
            scale = current_app_scale()
            want_h = max(16, int(round(16 * scale)))
            if self.height() != want_h:
                self.setFixedHeight(want_h)
            p.setPen(QColor("#94a3b8"))
            f = QFont(self.font())
            f.setPointSizeF(max(5.5, round(7.5 * scale, 1)))
            p.setFont(f)
            p.drawText(QRectF(0, 0, self.width(), self.height() - h - 1), Qt.AlignLeft | Qt.AlignVCenter,
                       usage_text(self.usage))
        p.end()
