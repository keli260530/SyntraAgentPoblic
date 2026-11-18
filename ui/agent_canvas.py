# -*- coding: utf-8 -*-
"""
代理畫布：每個代理一張卡片，工具（便利貼 / 圖片 / 連結 / 讀取電腦）也是卡片。

- 每張卡片上下左右四邊都有 ● 接點；從任一個接點拖線到另一張卡片：
    代理 → 代理：選「串接（共用終端＋互傳訊息）」「開始對話」「掛為子代理」
    代理 ↔ 工具：把工具連給代理（一個工具可以連很多代理，一個代理也可以連很多工具）
- 線：灰色虛線＝主代理→子代理；青色＝串接；琥珀色點線＝工具。線上按右鍵可以斷開。
- 卡片右鍵：代理（開啟、新增子代理、模型、設為主控、重新命名、關閉）；工具（編輯、刪除）。
- 空白處右鍵：新增主代理、新增工具；滾輪縮放；卡片可拖動。

畫布只負責顯示與操作，資料與動作都透過 CanvasModel（由主視窗提供）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QLineF, QPoint, QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPainterPathStroker, QPen
from PyQt5.QtWidgets import (QGraphicsItem, QGraphicsLineItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene,
                             QGraphicsView, QMenu)

from ui.usage_bar import usage_color, usage_text
from ui.font_scaler import current_app_scale

CARD_W, CARD_H = 310.0, 224.0
MIN_CARD_W, MIN_CARD_H = 240.0, 175.0
MAX_CARD_W, MAX_CARD_H = 780.0, 640.0
MODEL_CHIP = QRectF(10, 45, CARD_W - 20, 22)  # 卡片上的模型標籤（點一下選模型）
TOOL_W, TOOL_H = 220.0, 124.0
PORT_R = 6.5
RESIZE_GRIP = 18.0
SIDES = ("left", "right", "top", "bottom")


@dataclass
class CanvasModel:
    nodes: Callable[[], List[dict]]           # 代理 [{id, name, is_main, is_master, parent, status, preview, usage, active, model}]
    links: Callable[[], List[Tuple[str, str]]]
    term_tail: Callable[[str], List[str]]
    focus: Callable[[str], None]
    new_main: Callable[[], None]
    new_sub: Callable[[str], None]
    close: Callable[[str], None]
    link: Callable[[str, str], None]
    unlink: Callable[[str, str], None]
    set_master: Callable[[str], None]
    rename: Callable[[str], None]
    # v2
    tools: Callable[[], List[dict]] = field(default=lambda: [])          # [{id, kind, icon, label, title, content}]
    tool_links: Callable[[], List[Tuple[str, str]]] = field(default=lambda: [])  # (tool_id, agent_id)
    connect: Callable[[str, str, QPoint], None] = field(default=lambda a, b, p: None)  # 拖線放開
    unlink_tool: Callable[[str, str], None] = field(default=lambda t, a: None)
    add_tool: Callable[[str, Optional[QPointF]], None] = field(default=lambda kind, pos: None)
    edit_tool: Callable[[str], None] = field(default=lambda t: None)
    remove_tool: Callable[[str], None] = field(default=lambda t: None)
    agent_menu_extra: Callable[[str, QMenu], Callable[[object], bool]] = field(default=lambda a, m: (lambda act: False))
    pick_model: Callable[[str, QPoint], None] = field(default=lambda a, p: None)
    moved: Callable[[], None] = field(default=lambda: None)


_STATUS = {"RUNNING": ("⏳ 執行中", "#fbbf24"), "DONE": ("✅ 完成", "#4ade80"),
           "ERROR": ("🔴 錯誤", "#f87171"), "IDLE": ("🟢 待命", "#4ade80")}


class _Card(QGraphicsObject):
    """代理卡片與工具卡片共用：四邊接點、拖動、拖線、右下角自由縮放大小。"""
    W, H = CARD_W, CARD_H
    MIN_W, MIN_H = MIN_CARD_W, MIN_CARD_H

    def __init__(self, view: "AgentCanvas", data: dict):
        super().__init__()
        self.view = view
        self.data = data
        saved_size = getattr(view, "sizes", {}).get(data["id"])
        self.w: float = float(saved_size[0]) if saved_size else float(self.W)
        self.h: float = float(saved_size[1]) if saved_size else float(self.H)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(2)
        self._hover_side: Optional[str] = None
        self._hover_resize: bool = False
        self._resizing: bool = False
        self._resize_start_scene: QPointF = QPointF()
        self._resize_start_size: Tuple[float, float] = (self.w, self.h)

    @property
    def node_id(self) -> str:
        return self.data["id"]

    def boundingRect(self) -> QRectF:
        m = PORT_R + 4
        return QRectF(-m, -m, self.w + 2 * m, self.h + 2 * m)

    def port_local(self, side: str) -> QPointF:
        return {"left": QPointF(0, self.h / 2), "right": QPointF(self.w, self.h / 2),
                "top": QPointF(self.w / 2, 0), "bottom": QPointF(self.w / 2, self.h)}[side]

    def port_scene(self, side: str) -> QPointF:
        return self.mapToScene(self.port_local(side))

    def side_at(self, local: QPointF) -> Optional[str]:
        for side in SIDES:
            if QLineF(local, self.port_local(side)).length() <= PORT_R + 5:
                return side
        return None

    def _in_resize_grip(self, local: QPointF) -> bool:
        return (self.w - RESIZE_GRIP <= local.x() <= self.w + 2) and (self.h - RESIZE_GRIP <= local.y() <= self.h + 2)

    def set_card_size(self, w: float, h: float, notify: bool = True):
        new_w = max(self.MIN_W, min(MAX_CARD_W, float(w)))
        new_h = max(self.MIN_H, min(MAX_CARD_H, float(h)))
        if abs(new_w - self.w) < 0.5 and abs(new_h - self.h) < 0.5:
            return
        self.prepareGeometryChange()
        self.w, self.h = new_w, new_h
        self.view.sizes[self.node_id] = (self.w, self.h)
        self.view.update_edges()
        self.update()
        if notify:
            self.view.model.moved()

    def reset_card_size(self):
        self.set_card_size(self.W, self.H, notify=True)

    def set_data(self, data: dict):
        self.data = data
        self.update()

    def _paint_ports(self, p: QPainter, color: str):
        for side in SIDES:
            p.setPen(QPen(QColor("#0b0d13"), 2))
            p.setBrush(QColor("#22d3ee") if side == self._hover_side else QColor(color))
            p.drawEllipse(self.port_local(side), PORT_R, PORT_R)

    def _paint_resize_grip(self, p: QPainter):
        grip_col = QColor("#38bdf8") if (self._hover_resize or self._resizing) else QColor(148, 163, 184, 130)
        pen = QPen(grip_col, 1.8, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        for offset in (5.0, 9.5, 14.0):
            p.drawLine(QPointF(self.w - offset, self.h - 3.0), QPointF(self.w - 3.0, self.h - offset))

    def hoverMoveEvent(self, e):
        in_grip = self._in_resize_grip(e.pos())
        side = None if in_grip else self.side_at(e.pos())
        if side != self._hover_side or in_grip != self._hover_resize:
            self._hover_side = side
            self._hover_resize = in_grip
            if in_grip:
                self.setCursor(Qt.SizeFDiagCursor)
                self.setToolTip("拖曳右下角自由調整此卡片大小")
            elif side:
                self.setCursor(Qt.CrossCursor)
                self.setToolTip("拖到另一張卡片來連線")
            else:
                self.setCursor(Qt.OpenHandCursor)
                self.setToolTip("")
            self.update()

    def hoverLeaveEvent(self, e):
        self._hover_side = None
        self._hover_resize = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._in_resize_grip(e.pos()):
                self._resizing = True
                self._resize_start_scene = e.scenePos()
                self._resize_start_size = (self.w, self.h)
                self.setZValue(10)
                e.accept()
                return
            side = self.side_at(e.pos())
            if side:
                self.view.begin_link(self, side)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resizing:
            delta = e.scenePos() - self._resize_start_scene
            self.set_card_size(self._resize_start_size[0] + delta.x(), self._resize_start_size[1] + delta.y(), notify=False)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resizing:
            self._resizing = False
            self.setZValue(2)
            self.view.model.moved()
            self.update()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.view.positions[self.node_id] = self.pos()
            self.view.update_edges()
            self.view.model.moved()
        return super().itemChange(change, value)


class AgentCard(_Card):
    W, H = CARD_W, CARD_H
    MIN_W, MIN_H = MIN_CARD_W, MIN_CARD_H

    def __init__(self, view: "AgentCanvas", data: dict):
        super().__init__(view, data)
        self._hover_chip = False

    def _chip_rect(self) -> QRectF:
        return QRectF(10, 45, self.w - 20, 22)

    def hoverMoveEvent(self, e):
        chip = self._chip_rect()
        hit = chip.contains(e.pos()) and not self.side_at(e.pos()) and not self._in_resize_grip(e.pos())
        if hit != self._hover_chip:
            self._hover_chip = hit
            self.update()
        super().hoverMoveEvent(e)
        if hit:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("點一下選擇這個代理要用的模型")

    def hoverLeaveEvent(self, e):
        self._hover_chip = False
        super().hoverLeaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._chip_rect().contains(e.pos()) and not self.side_at(e.pos()) and not self._in_resize_grip(e.pos()):
            self.view.model.pick_model(self.agent_id, e.screenPos())
            e.accept()
            return
        super().mousePressEvent(e)

    @property
    def agent_id(self) -> str:
        return self.data["id"]

    def paint(self, p: QPainter, _opt, _w=None):
        d = self.data
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        rect = QRectF(0, 0, self.w, self.h)
        is_active = bool(d.get("active"))
        border = QColor("#38bdf8") if is_active else QColor(148, 163, 184, 65)
        if self.isSelected():
            border = QColor("#38bdf8") if is_active else QColor("#a78bfa")
        p.setPen(QPen(border, 2.2 if (is_active or self.isSelected()) else 1.2))
        p.setBrush(QColor("#141a28") if d.get("is_main") else QColor("#111622"))
        p.drawRoundedRect(rect, 10, 10)

        scale = max(0.85, min(1.6, current_app_scale()))
        badge = "主" if d.get("is_main") else "子"
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0284c7") if d.get("is_main") else QColor("#475569"))
        p.drawRoundedRect(QRectF(10, 10, 22, 20), 5, 5)
        f = QFont(p.font())
        f.setBold(True)
        f.setPointSizeF(round(9.0 * scale, 1))
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(10, 10, 22, 20), Qt.AlignCenter, badge)

        f.setPointSizeF(round(10.8 * scale, 1))
        p.setFont(f)
        p.setPen(QColor("#f8fafc"))
        name = d.get("name", "") + ("  ⭐" if d.get("is_master") else "")
        p.drawText(QRectF(38, 8, self.w - 134, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(name, Qt.ElideRight, int(self.w - 134)))
        st, col = _STATUS.get(d.get("status", "IDLE"), _STATUS["IDLE"])
        f.setBold(False)
        f.setPointSizeF(round(8.8 * scale, 1))
        p.setFont(f)
        p.setPen(QColor(col))
        p.drawText(QRectF(self.w - 94, 8, 84, 24), Qt.AlignRight | Qt.AlignVCenter, st)

        u = d.get("usage") or {}
        ratio = float(u.get("ratio") or 0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 28))
        p.drawRoundedRect(QRectF(10, 36, self.w - 20, 5), 2, 2)
        if ratio > 0:
            p.setBrush(usage_color(ratio))
            p.drawRoundedRect(QRectF(10, 36, max(3.0, (self.w - 20) * ratio), 5), 2, 2)

        # 模型標籤：直接看到目前用哪個模型，點一下就能換
        chip = self._chip_rect()
        own = bool(d.get("model"))
        p.setPen(QPen(QColor("#38bdf8") if self._hover_chip else QColor(255, 255, 255, 55), 1))
        p.setBrush(QColor(14, 165, 233, 48) if own else QColor(255, 255, 255, 18))
        p.drawRoundedRect(chip, 5, 5)
        f.setPointSizeF(round(8.8 * scale, 1))
        p.setFont(f)
        p.setPen(QColor("#e0f2fe") if own else QColor("#cbd5e1"))
        label = d.get("model_display") or d.get("model") or "跟隨全域設定"
        text = f"🧠 {label}"
        p.drawText(chip.adjusted(8, 0, -20, 0), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(text, Qt.ElideRight, int(chip.width() - 28)))
        p.setPen(QColor("#94a3b8"))
        p.drawText(chip.adjusted(0, 0, -6, 0), Qt.AlignRight | Qt.AlignVCenter, "▾")

        p.setPen(QColor("#cbd5e1"))
        f.setPointSizeF(round(8.2 * scale, 1))
        p.setFont(f)
        p.drawText(QRectF(10, 70, self.w - 20, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(usage_text(u), Qt.ElideRight, int(self.w - 20)))

        # 動態分配對話預覽區與終端機高度（卡片拉大時自動顯示更多行數與清晰文字）
        avail_h = max(80.0, self.h - 94.0)
        preview_h = max(36.0, min(avail_h * 0.48, avail_h - 52.0))
        preview_rect = QRectF(10, 88, self.w - 20, preview_h)

        f.setPointSizeF(round(9.2 * scale, 1))
        p.setFont(f)
        p.setPen(QColor("#f1f5f9"))
        preview = " ".join((d.get("preview") or "（還沒有對話，雙擊開啟或拉大卡片檢視更多內容）").split())
        p.drawText(preview_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, preview[:900])

        term_top = 88.0 + preview_h + 6.0
        term = QRectF(8, term_top, self.w - 16, max(44.0, self.h - term_top - 10.0))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor("#090b10"))
        p.drawRoundedRect(term, 6, 6)
        mono = QFont("Consolas")
        mono.setPointSizeF(round(8.4 * scale, 1))
        p.setFont(mono)
        fmm = QFontMetrics(mono)
        line_h = max(15, int(round(16 * scale)))
        max_lines = max(2, int((term.height() - 8) // line_h))
        all_lines = self.view.model.term_tail(self.agent_id) or ["PS> （終端尚未使用）"]
        lines = all_lines[-max_lines:]
        p.setPen(QColor("#cbd5e1"))
        for i, ln in enumerate(lines):
            p.drawText(QRectF(term.x() + 7, term.y() + 4 + i * line_h, term.width() - 14, line_h),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fmm.elidedText(ln, Qt.ElideRight, int(term.width() - 14)))
        self._paint_ports(p, "#0891b2")
        self._paint_resize_grip(p)

    def mouseDoubleClickEvent(self, e):
        self.view.model.focus(self.agent_id)

    def contextMenuEvent(self, e):
        m = self.view.model
        d = self.data
        menu = QMenu()
        a_open = menu.addAction("開啟這個代理")
        a_sub = menu.addAction("＋ 新增子代理") if d.get("is_main") else None
        extra = m.agent_menu_extra(self.agent_id, menu)
        a_master = menu.addAction("⭐ 已是主控" if d.get("is_master") else "⭐ 設為主控")
        a_master.setEnabled(not d.get("is_master"))
        a_rename = menu.addAction("✏️ 重新命名…")
        a_reset_size = menu.addAction("📐 重設卡片預設大小")
        menu.addSeparator()
        a_close = menu.addAction("✕ 關閉這個代理")
        chosen = menu.exec_(e.screenPos())
        if chosen is None:
            return
        if chosen is a_open:
            m.focus(self.agent_id)
        elif a_sub is not None and chosen is a_sub:
            m.new_sub(self.agent_id)
        elif chosen is a_master:
            m.set_master(self.agent_id)
        elif chosen is a_rename:
            m.rename(self.agent_id)
        elif chosen is a_reset_size:
            self.reset_card_size()
        elif chosen is a_close:
            m.close(self.agent_id)
        else:
            extra(chosen)


class ToolCard(_Card):
    W, H = TOOL_W, TOOL_H
    MIN_W, MIN_H = 180.0, 96.0
    _COLORS = {"note": "#fbbf24", "image": "#a78bfa", "link": "#34d399", "computer": "#60a5fa"}

    def paint(self, p: QPainter, _opt, _w=None):
        d = self.data
        col = QColor(self._COLORS.get(d.get("kind"), "#94a3b8"))
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QPen(QColor("#a78bfa") if self.isSelected() else col, 1.5))
        bg = QColor(col)
        bg.setAlpha(28)
        p.setBrush(QColor("#11141c"))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 9, 9)
        p.setBrush(bg)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(1, 1, self.w - 2, 26), 8, 8)
        scale = max(0.85, min(1.5, current_app_scale()))
        f = QFont(p.font())
        f.setBold(True)
        f.setPointSizeF(round(9.5 * scale, 1))
        p.setFont(f)
        p.setPen(col)
        title = f"{d.get('icon', '')} {d.get('title') or d.get('label', '')}"
        p.drawText(QRectF(10, 3, self.w - 20, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(f).elidedText(title, Qt.ElideRight, int(self.w - 20)))
        f.setBold(False)
        f.setPointSizeF(round(8.8 * scale, 1))
        p.setFont(f)
        p.setPen(QColor("#f1f5f9"))
        body = d.get("content") or "（雙擊編輯）"
        p.drawText(QRectF(10, 32, self.w - 20, self.h - 40), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   body[:500])
        self._paint_ports(p, self._COLORS.get(d.get("kind"), "#64748b"))
        self._paint_resize_grip(p)

    def mouseDoubleClickEvent(self, e):
        self.view.model.edit_tool(self.node_id)

    def contextMenuEvent(self, e):
        menu = QMenu()
        a_edit = menu.addAction("✏️ 編輯內容…")
        a_del = menu.addAction("🗑 刪除這個工具")
        chosen = menu.exec_(e.screenPos())
        if chosen is a_edit:
            self.view.model.edit_tool(self.node_id)
        elif chosen is a_del:
            self.view.model.remove_tool(self.node_id)


class EdgeItem(QGraphicsPathItem):
    STYLES = {
        "parent": (QColor(148, 163, 184, 150), 1.4, Qt.DashLine, "主代理 → 子代理（可互傳訊息）"),
        "link": (QColor("#22d3ee"), 2.4, Qt.SolidLine, "串接：共用終端、可互傳訊息（右鍵可斷開）"),
        "tool": (QColor("#f59e0b"), 1.8, Qt.DotLine, "工具連線：代理每一輪都會看到這個工具的內容（右鍵可斷開）"),
    }

    def __init__(self, view: "AgentCanvas", a: str, b: str, kind: str):
        super().__init__()
        self.view, self.a, self.b, self.kind = view, a, b, kind
        self.setZValue(1)
        color, width, style, tip = self.STYLES[kind]
        self.setPen(QPen(color, width, style))
        self.setToolTip(tip)
        if kind != "parent":
            self.setCursor(Qt.PointingHandCursor)

    def shape(self) -> QPainterPath:
        st = QPainterPathStroker()
        st.setWidth(12)
        return st.createStroke(self.path())

    def refresh(self):
        ca, cb = self.view.card(self.a), self.view.card(self.b)
        if not ca or not cb:
            return
        if self.kind == "parent":
            sa, sb = "bottom", "top"
        else:
            sa, sb = min(((x, y) for x in SIDES for y in SIDES),
                         key=lambda s: QLineF(ca.port_scene(s[0]), cb.port_scene(s[1])).length())
        p1, p2 = ca.port_scene(sa), cb.port_scene(sb)
        out = {"left": QPointF(-1, 0), "right": QPointF(1, 0), "top": QPointF(0, -1), "bottom": QPointF(0, 1)}
        bend = max(40.0, QLineF(p1, p2).length() / 3)
        path = QPainterPath(p1)
        path.cubicTo(p1 + out[sa] * bend, p2 + out[sb] * bend, p2)
        self.setPath(path)

    def contextMenuEvent(self, e):
        if self.kind == "parent":
            return
        menu = QMenu()
        text = "✂ 斷開串接（各自回到自己的終端）" if self.kind == "link" else "✂ 斷開工具連線"
        a = menu.addAction(text)
        if menu.exec_(e.screenPos()) is a:
            if self.kind == "link":
                self.view.model.unlink(self.a, self.b)
            else:
                self.view.model.unlink_tool(self.a, self.b)


class AgentCanvas(QGraphicsView):
    def __init__(self, model: CanvasModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QBrush(QColor("#0b0e15")))
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setStyleSheet("border: none;")
        self.cards: Dict[str, AgentCard] = {}
        self.tool_cards: Dict[str, ToolCard] = {}
        self.edges: List[EdgeItem] = []
        self.positions: Dict[str, QPointF] = {}
        self.sizes: Dict[str, Tuple[float, float]] = {}
        self._drag_from: Optional[_Card] = None
        self._drag_line: Optional[QGraphicsLineItem] = None

    def card(self, node_id: str) -> Optional[_Card]:
        return self.cards.get(node_id) or self.tool_cards.get(node_id)

    # ------------------------------------------------ 版面
    def _place(self, node: dict, nodes: List[dict]) -> QPointF:
        if node["id"] in self.positions:
            return self.positions[node["id"]]
        parent = node.get("parent")
        if parent and parent in self.positions:
            siblings = [n["id"] for n in nodes if n.get("parent") == parent]
            i = siblings.index(node["id"]) if node["id"] in siblings else len(siblings)
            base = self.positions[parent]
            return QPointF(base.x() + (i - (len(siblings) - 1) / 2) * (CARD_W + 30), base.y() + CARD_H + 70)
        used_x = [pt.x() for k, pt in self.positions.items() if k in self.cards]
        return QPointF(max(used_x) + CARD_W + 80 if used_x else 0, 0)

    def _place_tool(self, idx: int) -> QPointF:
        ys = [pt.y() for k, pt in self.positions.items() if k in self.cards]
        top = (min(ys) if ys else 0) - TOOL_H - 70
        return QPointF(idx * (TOOL_W + 30), top)

    def refresh(self):
        nodes = self.model.nodes()
        tools = self.model.tools()
        ids = {n["id"] for n in nodes}
        tids = {t["id"] for t in tools}
        for aid in list(self.cards):
            if aid not in ids:
                self.scene_.removeItem(self.cards.pop(aid))
                self.positions.pop(aid, None)
        for tid in list(self.tool_cards):
            if tid not in tids:
                self.scene_.removeItem(self.tool_cards.pop(tid))
                self.positions.pop(tid, None)
        for n in sorted(nodes, key=lambda x: 0 if not x.get("parent") else 1):
            card = self.cards.get(n["id"])
            if card is None:
                card = AgentCard(self, n)
                self.cards[n["id"]] = card
                self.scene_.addItem(card)
                pos = self._place(n, nodes)
                self.positions[n["id"]] = pos
                card.setPos(pos)
            else:
                card.set_data(n)
        for i, t in enumerate(tools):
            card = self.tool_cards.get(t["id"])
            if card is None:
                card = ToolCard(self, t)
                self.tool_cards[t["id"]] = card
                self.scene_.addItem(card)
                pos = self.positions.get(t["id"]) or self._place_tool(i)
                self.positions[t["id"]] = pos
                card.setPos(pos)
            else:
                card.set_data(t)
        for e in self.edges:
            self.scene_.removeItem(e)
        self.edges = []
        for n in nodes:
            if n.get("parent") and n["parent"] in self.cards:
                self.edges.append(EdgeItem(self, n["parent"], n["id"], "parent"))
        for a, b in self.model.links():
            if a in self.cards and b in self.cards:
                self.edges.append(EdgeItem(self, a, b, "link"))
        for t, a in self.model.tool_links():
            if t in self.tool_cards and a in self.cards:
                self.edges.append(EdgeItem(self, t, a, "tool"))
        for e in self.edges:
            self.scene_.addItem(e)
        self.update_edges()
        self.scene_.setSceneRect(self.scene_.itemsBoundingRect().adjusted(-300, -300, 600, 600))

    def update_cards(self):
        data = {n["id"]: n for n in self.model.nodes()}
        for aid, card in self.cards.items():
            if aid in data:
                card.set_data(data[aid])
        tdata = {t["id"]: t for t in self.model.tools()}
        for tid, card in self.tool_cards.items():
            if tid in tdata:
                card.set_data(tdata[tid])

    def update_edges(self):
        for e in self.edges:
            e.refresh()

    # ------------------------------------------------ 拖線
    def begin_link(self, card: _Card, side: str):
        self._drag_from = card
        start = card.port_scene(side)
        self._drag_line = QGraphicsLineItem(QLineF(start, start))
        self._drag_line.setPen(QPen(QColor("#22d3ee"), 2, Qt.DashLine))
        self._drag_line.setZValue(5)
        self.scene_.addItem(self._drag_line)
        self.setDragMode(QGraphicsView.NoDrag)

    def mouseMoveEvent(self, e):
        if self._drag_line is not None:
            line = self._drag_line.line()
            line.setP2(self.mapToScene(e.pos()))
            self._drag_line.setLine(line)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag_line is not None:
            target = self._card_at(self.mapToScene(e.pos()))
            src = self._drag_from
            self.scene_.removeItem(self._drag_line)
            self._drag_line, self._drag_from = None, None
            self.setDragMode(QGraphicsView.RubberBandDrag)
            if target is not None and src is not None and target is not src:
                self.model.connect(src.node_id, target.node_id, self.viewport().mapToGlobal(e.pos()))
            return
        super().mouseReleaseEvent(e)

    def _card_at(self, scene_pt: QPointF) -> Optional[_Card]:
        for item in self.scene_.items(scene_pt):
            if isinstance(item, _Card):
                return item
        return None

    # ------------------------------------------------ 其他
    def wheelEvent(self, e):
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        scale = self.transform().m11() * factor
        if 0.3 <= scale <= 2.5:
            self.scale(factor, factor)

    def contextMenuEvent(self, e):
        if self.itemAt(e.pos()) is not None:
            return super().contextMenuEvent(e)
        scene_pt = self.mapToScene(e.pos())
        menu = QMenu(self)
        a_new = menu.addAction("＋ 新增主代理")
        sub = menu.addMenu("＋ 新增工具")
        tool_acts = {sub.addAction(text): kind for kind, text in
                     (("note", "📝 便利貼"), ("image", "🖼 圖片"), ("link", "🔗 連結"), ("computer", "🖥 讀取電腦"))}
        a_fit = menu.addAction("🔍 全部顯示")
        chosen = menu.exec_(e.globalPos())
        if chosen is a_new:
            self.model.new_main()
        elif chosen in tool_acts:
            self.model.add_tool(tool_acts[chosen], scene_pt)
        elif chosen is a_fit:
            self.fit_all()

    def visible_center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def fit_all(self):
        cards = list(self.cards.values()) + list(self.tool_cards.values())
        if cards:
            rect = QRectF()
            for card in cards:
                rect = rect.united(card.sceneBoundingRect())
            rect = rect.adjusted(-40, -40, 40, 40)
            self.fitInView(rect, Qt.KeepAspectRatio)
            if self.transform().m11() > 1.0:
                self.resetTransform()
            self.centerOn(rect.center())
