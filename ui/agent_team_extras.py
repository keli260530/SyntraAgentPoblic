# -*- coding: utf-8 -*-
"""
多代理團隊 v2 的介面功能（由 AgentTeamMixin 繼承使用）：

- 畫布工具列＋工具節點（便利貼 / 圖片 / 連結 / 讀取電腦）的新增、編輯、刪除。
- 拖線放開時的選單：串接、開始對話、掛為子代理；代理 ↔ 工具直接連上。
- 兩個代理互相對話（每輪回覆自動轉給對方，達到輪數或出現「[結束對話]」就停）。
- 每個代理可以選不同模型。
- 工作區記憶：代理、子代理關係、模型、對話、串線、工具、畫布位置、終端目錄、用量都存到
  data/agent_workspace.json，關掉重開或重新開機後自動還原。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt5.QtCore import QPoint, QPointF, QTimer
from PyQt5.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton,
                             QVBoxLayout, QWidget)

from core.agent_team import team
from core.agent_terminal import terminal_manager

try:  # 舊版核心沒有工具節點時，畫布工具功能自動停用（不影響其他功能）
    from core.agent_team import TOOL_KINDS, ToolNode
except ImportError:  # pragma: no cover
    TOOL_KINDS, ToolNode = {}, None

from core.user_profile_manager import user_profile_manager

WORKSPACE_FILE = user_profile_manager.workspace_path
MAX_SAVED_MESSAGES = 200
END_MARK = "[結束對話]"

_BAR_STYLE = """
#canvasBar { background: #10141d; border-bottom: 1px solid rgba(255,255,255,0.07); }
#canvasBar QPushButton { background: #1a2030; color: #cbd5e1; border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px; padding: 3px 10px; font-size: 12px; }
#canvasBar QPushButton:hover { background: #24304a; color: #38bdf8; border-color: #38bdf8; }
#canvasBar QLabel { color: #64748b; font-size: 11px; }
"""


class AgentTeamExtrasMixin:
    # ================================================================ 畫布外框＋工具列
    def _team_build_canvas_box(self, canvas) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("canvasBar")
        bar.setStyleSheet(_BAR_STYLE)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 4, 8, 4)
        bl.setSpacing(6)

        def btn(text, tip, fn):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _: fn())
            bl.addWidget(b)
            return b

        btn("＋ 主代理", "新增一個主代理", lambda: self._new_agent_from_bar())
        if ToolNode is not None:
            for kind, (icon, label) in TOOL_KINDS.items():
                btn(f"{icon} {label}", f"在畫布上新增「{label}」工具，拖線連給代理就能使用",
                    lambda k=kind: self._team_add_tool(k, None))
        btn("🔍 全部顯示", "把所有卡片縮放到畫面內", lambda: canvas.fit_all())
        bl.addStretch(1)
        bl.addWidget(QLabel("從卡片四邊的 ● 拖線連接 · 線上按右鍵可斷開"))
        lay.addWidget(bar)
        lay.addWidget(canvas, 1)
        return box

    # ================================================================ 工具節點
    def _team_tool_nodes(self) -> List[dict]:
        out = []
        for t in list(getattr(team, "tools", {}).values()):
            icon, label = TOOL_KINDS.get(t.kind, ("•", t.kind))
            content = t.content
            if t.kind == "image" and t.extracted:
                content = f"{t.content}\n{t.extracted[:120]}"
            if t.kind == "computer" and not t.content:
                content = "允許代理讀取目前畫面文字（ocr_screen）"
            out.append({"id": t.node_id, "kind": t.kind, "icon": icon, "label": label, "title": t.title,
                        "content": content})
        return out

    def _team_tool_links(self):
        return sorted(getattr(team, "tool_links", set()))

    def _team_add_tool(self, kind: str, pos: Optional[QPointF]):
        if ToolNode is None:
            return
        node = ToolNode(node_id=f"tool_{uuid.uuid4().hex[:10]}", kind=kind)
        if not self._team_edit_tool_node(node, creating=True):
            return
        team.add_tool(node)
        canvas = self.agent_canvas
        canvas.positions[node.node_id] = pos if pos is not None else canvas.visible_center() - QPointF(100, 50)
        canvas.refresh()
        self.statusBar().showMessage("工具已加到畫布：從它的 ● 拖線到代理，代理就能使用", 5000)
        self._team_schedule_save()

    def _team_edit_tool(self, node_id: str):
        node = getattr(team, "tools", {}).get(node_id)
        if node is not None and self._team_edit_tool_node(node, creating=False):
            team._emit("changed")
            self._team_schedule_save()

    def _team_edit_tool_node(self, node, creating: bool) -> bool:
        if node.kind == "note":
            text, ok = QInputDialog.getMultiLineText(self, "便利貼", "內容（連到的代理每一輪都會看到）：", node.content)
            if not ok:
                return False
            node.content = text.strip()
            node.title = (node.content.splitlines() or [""])[0][:16]
        elif node.kind == "link":
            url, ok = QInputDialog.getText(self, "連結", "網址：", text=node.content or "https://")
            if not ok or not url.strip():
                return False
            node.content = url.strip()
            title, ok2 = QInputDialog.getText(self, "連結", "名稱（可留空）：", text=node.title)
            node.title = title.strip() if ok2 else node.title
        elif node.kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "選擇圖片", os.path.dirname(node.content) if node.content else "",
                                                  "圖片 (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
            if not path:
                return False
            node.content, node.title, node.extracted = path, Path(path).name, ""
            self._team_ocr_image(node)
        elif node.kind == "computer":
            box = QMessageBox(self)
            box.setWindowTitle("讀取電腦")
            box.setText("要讓連到的代理讀取什麼？")
            b_folder = box.addButton("指定一個資料夾", QMessageBox.AcceptRole)
            b_screen = box.addButton("只讀目前畫面文字", QMessageBox.ActionRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is b_folder:
                folder = QFileDialog.getExistingDirectory(self, "選擇允許代理查閱的資料夾", node.content or str(Path.home()))
                if not folder:
                    return False
                node.content, node.title = folder, Path(folder).name or folder
            elif box.clickedButton() is b_screen:
                node.content, node.title = "", "目前畫面"
            else:
                return False
        return True

    def _team_ocr_image(self, node):
        def work():
            try:
                from core.local_tools import ocr_image_file
                node.extracted = ocr_image_file(node.content)[:4000]
            except Exception as e:  # noqa: BLE001
                node.extracted = ""
                print(f"[canvas] 圖片文字辨識失敗：{e}")
            self._team_bridge.team_event.emit("changed")
        threading.Thread(target=work, daemon=True).start()

    def _team_remove_tool(self, node_id: str):
        team.remove_tool(node_id)
        self.agent_canvas.positions.pop(node_id, None)
        self.agent_canvas.refresh()
        self._team_schedule_save()

    def _team_unlink_tool(self, node_id: str, agent_id: str):
        team.unlink_tool(node_id, agent_id)
        self._team_schedule_save()

    # ================================================================ 拖線放開
    def _team_connect(self, src: str, dst: str, global_pos: QPoint):
        is_tool = lambda x: x in getattr(team, "tools", {})  # noqa: E731
        if is_tool(src) and is_tool(dst):
            self.statusBar().showMessage("工具之間不能互連；請把工具連到代理", 4000)
            return
        if is_tool(src) or is_tool(dst):
            tool, agent = (src, dst) if is_tool(src) else (dst, src)
            if team.link_tool(tool, agent):
                self.statusBar().showMessage(f"已把工具連給 {self._team_name_of(agent)}", 4000)
                self._team_schedule_save()
            return
        if src not in self.agent_slots or dst not in self.agent_slots:
            return
        menu = QMenu(self)
        a_link = menu.addAction("🔗 串接（共用終端＋互傳訊息）")
        a_chat = menu.addAction("💬 讓它們開始對話…")
        a_attach = a_attach_rev = None
        if self._team_can_attach(src, dst):
            a_attach = menu.addAction(f"📎 把「{self._team_name_of(src)}」掛到「{self._team_name_of(dst)}」底下（變子代理）")
        if self._team_can_attach(dst, src):
            a_attach_rev = menu.addAction(f"📎 把「{self._team_name_of(dst)}」掛到「{self._team_name_of(src)}」底下（變子代理）")
        chosen = menu.exec_(global_pos)
        if chosen is a_link:
            self._team_link(src, dst)
        elif chosen is a_chat:
            self.start_agent_chat(src, dst)
        elif a_attach is not None and chosen is a_attach:
            self.attach_agent(src, dst)
        elif a_attach_rev is not None and chosen is a_attach_rev:
            self.attach_agent(dst, src)
        self._team_schedule_save()

    # ================================================================ 掛載子代理
    def _team_can_attach(self, child: str, parent: Optional[str]) -> bool:
        c, p = self.agent_slots.get(child), self.agent_slots.get(parent) if parent else None
        if c is None or child == parent:
            return False
        if parent is None:
            return bool(getattr(c, "parent_id", None))
        if p is None or getattr(p, "parent_id", None):
            return False
        has_children = any(getattr(s, "parent_id", None) == child for s in self.agent_slots.values())
        return not has_children and getattr(c, "parent_id", None) != parent

    def attach_agent(self, child: str, parent: Optional[str]):
        if not self._team_can_attach(child, parent):
            return False
        setter = getattr(team, "set_parent", None)
        if setter is not None:
            setter(child, parent)
        elif child in team.members:
            team.members[child].parent_id = parent
        self.agent_slots[child].parent_id = parent
        if parent:
            self.statusBar().showMessage(f"📎 {self._team_name_of(child)} 現在是 {self._team_name_of(parent)} 的子代理", 4000)
        else:
            self.statusBar().showMessage(f"↩ {self._team_name_of(child)} 已變回主代理", 4000)
        self._refresh_agent_tab_bar()
        if getattr(self, "agent_view_mode", "") == "canvas":
            self.agent_canvas.refresh()
        self._team_schedule_save()
        return True

    # ================================================================ 代理互相對話
    def start_agent_chat(self, a: str, b: str, topic: Optional[str] = None, rounds: Optional[int] = None):
        if a not in self.agent_slots or b not in self.agent_slots or a == b:
            return
        if topic is None:
            topic, ok = QInputDialog.getMultiLineText(
                self, "代理對話", f"讓「{self._team_name_of(a)}」和「{self._team_name_of(b)}」討論什麼？", "")
            if not ok or not topic.strip():
                return
        if rounds is None:
            rounds, ok = QInputDialog.getInt(self, "代理對話", "最多來回幾次？（每人各說一次算一次）", 4, 1, 30)
            if not ok:
                return
        conv = {"a": a, "b": b, "topic": topic.strip(), "left": int(rounds) * 2 - 1, "intro": {a}}
        self._team_chats[a] = conv
        self._team_chats[b] = conv
        name_b = self._team_name_of(b)
        self._team_host_ask(a, (
            f"[你正在和代理「{name_b}」對話，主題：{conv['topic']}]\n"
            f"請你先開口。你的每次回覆都會直接轉給「{name_b}」，對方的回覆也會轉給你。"
            f"請用繁體中文、每次簡短（3～6 句），聚焦主題、推進討論；需要時可以使用工具。"
            f"當你們已經得出結論，請在回覆最後加上「{END_MARK}」。對話期間不需要使用 send_to_agent。"))
        self.statusBar().showMessage(f"💬 {self._team_name_of(a)} 和 {name_b} 開始對話（最多 {rounds} 個來回）", 5000)

    def stop_agent_chat(self, agent_id: str):
        conv = self._team_chats.pop(agent_id, None)
        if conv:
            self._team_chats.pop(conv["a"] if conv["b"] == agent_id else conv["b"], None)

    def _team_chat_after_reply(self, agent_id: str):
        conv = self._team_chats.get(agent_id)
        if not conv:
            return
        slot = self.agent_slots.get(agent_id)
        reply = ""
        for m in reversed(slot.messages if slot else []):
            if m.get("role") == "agent":
                reply = m.get("text") or ""
                break
        other = conv["b"] if agent_id == conv["a"] else conv["a"]
        done = (not reply.strip() or END_MARK in reply or conv["left"] <= 0 or other not in self.agent_slots
                or reply.startswith("⏹") or reply.startswith("🛑"))
        if done:
            self.stop_agent_chat(agent_id)
            self.statusBar().showMessage(
                f"💬 {self._team_name_of(conv['a'])} 與 {self._team_name_of(conv['b'])} 的對話已結束", 6000)
            return
        conv["left"] -= 1
        me = self._team_name_of(agent_id)
        if other not in conv["intro"]:
            conv["intro"].add(other)
            text = (f"[你正在和代理「{me}」對話，主題：{conv['topic']}]\n"
                    f"你的每次回覆都會直接轉給「{me}」。請用繁體中文、每次簡短（3～6 句）；"
                    f"得出結論時在回覆最後加上「{END_MARK}」。對話期間不需要使用 send_to_agent。\n\n"
                    f"「{me}」說：\n{reply}")
        else:
            text = f"「{me}」說：\n{reply}"
        self._team_host_ask(other, text)

    # ================================================================ 每個代理的模型
    def _team_models(self) -> List[tuple]:
        combo = getattr(self, "combo_models", None)
        out = []
        if combo is None:
            return out
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data and not str(data).startswith("--"):
                out.append((str(data), combo.itemText(i)))
        return out

    def _team_model_label(self, agent_id: str) -> str:
        slot = self.agent_slots.get(agent_id)
        mid = getattr(slot, "model_id", None) if slot else None
        if not mid:
            return ""
        for full, text in self._team_models():
            if full == mid:
                return text.split("·")[-1].strip()[:28]
        return mid.split(":", 1)[-1][:28]

    def _team_model_display(self, agent_id: str) -> str:
        """卡片上顯示的模型：自己選的模型，或「全域：目前全域模型」。"""
        own = self._team_model_label(agent_id)
        if own:
            return own
        combo = getattr(self, "combo_models", None)
        cur = combo.currentText().split("·")[-1].strip() if combo is not None and combo.count() else ""
        return f"全域：{cur}" if cur else "跟隨全域設定"

    def _team_pick_model(self, agent_id: str, global_pos):
        """畫布卡片上點模型標籤：跳出模型清單直接選。"""
        slot = self.agent_slots.get(agent_id)
        if slot is None:
            return
        cur = getattr(slot, "model_id", None)
        menu = QMenu(self)
        title = menu.addAction(f"「{slot.name}」要用的模型")
        title.setEnabled(False)
        menu.addSeparator()
        acts = {}
        a = menu.addAction(("✓ " if not cur else "") + "跟隨全域設定")
        acts[a] = None
        for full, text in self._team_models():
            act = menu.addAction(("✓ " if full == cur else "") + text)
            acts[act] = full
        if len(acts) == 1:
            none = menu.addAction("（還沒有可用的模型，請先到 API Key 管理新增）")
            none.setEnabled(False)
        chosen = menu.exec_(global_pos)
        if chosen in acts:
            self.set_agent_model(agent_id, acts[chosen])
            if getattr(self, "agent_view_mode", "") == "canvas":
                self.agent_canvas.update_cards()

    def _team_model_for_active(self) -> Optional[str]:
        slot = self.agent_slots.get(getattr(self, "active_agent_id", None))
        return getattr(slot, "model_id", None) if slot else None

    def set_agent_model(self, agent_id: str, model_id: Optional[str]):
        slot = self.agent_slots.get(agent_id)
        if slot is None:
            return
        slot.model_id = model_id or None
        label = self._team_model_label(agent_id) or "跟隨全域設定"
        self.statusBar().showMessage(f"🧠 {slot.name} 改用：{label}", 4000)
        self._refresh_agent_tab_bar()
        self._team_schedule_save()

    # ================================================================ 代理右鍵選單（畫布與分頁共用）
    def _team_agent_menu_extra(self, agent_id: str, menu: QMenu) -> Callable[[Any], bool]:
        handlers: Dict[Any, Callable[[], None]] = {}
        slot = self.agent_slots.get(agent_id)
        cur = getattr(slot, "model_id", None) if slot else None

        m_model = menu.addMenu("🧠 模型")
        a = m_model.addAction("✓ 跟隨全域設定" if not cur else "跟隨全域設定")
        handlers[a] = lambda: self.set_agent_model(agent_id, None)
        for full, text in self._team_models():
            act = m_model.addAction(("✓ " if full == cur else "") + text)
            handlers[act] = (lambda f=full: self.set_agent_model(agent_id, f))

        others = [x for x in self.agent_slots if x != agent_id]
        if others:
            m_chat = menu.addMenu("💬 和…對話")
            for o in others:
                act = m_chat.addAction(self._team_name_of(o))
                handlers[act] = (lambda o=o: self.start_agent_chat(agent_id, o))
        if agent_id in self._team_chats:
            act = menu.addAction("⏹ 結束目前的代理對話")
            handlers[act] = lambda: self.stop_agent_chat(agent_id)

        parents = [x for x in self.agent_slots if self._team_can_attach(agent_id, x)]
        if parents:
            m_att = menu.addMenu("📎 掛到主代理底下")
            for p in parents:
                act = m_att.addAction(self._team_name_of(p))
                handlers[act] = (lambda p=p: self.attach_agent(agent_id, p))
        if self._team_can_attach(agent_id, None):
            act = menu.addAction("↩ 解除掛載（變回主代理）")
            handlers[act] = lambda: self.attach_agent(agent_id, None)

        def handle(action) -> bool:
            fn = handlers.get(action)
            if fn is None:
                return False
            fn()
            return True
        return handle

    # ================================================================ 工作區記憶
    def _team_schedule_save(self):
        if getattr(self, "_team_restoring", False) or not hasattr(self, "_team_save_timer"):
            return
        self._team_save_timer.start(800)

    def _team_workspace_state(self) -> Dict[str, Any]:
        agents = []
        for aid in self._team_ordered_ids():
            s = self.agent_slots[aid]
            own = getattr(terminal_manager, "_own", {}).get(aid)
            u = team.usage_of(aid)
            msgs = [{"role": m.get("role"), "text": (m.get("text") or "")[:20000]}
                    for m in s.messages if m.get("role") in ("user", "agent") and m.get("text")]
            agents.append({
                "agent_id": aid, "name": s.name, "parent_id": getattr(s, "parent_id", None),
                "session_id": s.session_id, "model_id": getattr(s, "model_id", None),
                "cwd": own.cwd if own else None, "usage": u.as_dict() if u else None,
                "messages": msgs[-MAX_SAVED_MESSAGES:],
            })
        pos = {k: [v.x(), v.y()] for k, v in self.agent_canvas.positions.items()}
        sizes = {k: [float(v[0]), float(v[1])] for k, v in getattr(self.agent_canvas, "sizes", {}).items()}
        return {
            "version": 1, "saved_at": time.time(), "agents": agents,
            "master": getattr(self, "_main_agent_id", None), "active": getattr(self, "active_agent_id", None),
            "links": [list(p) for p in terminal_manager.links()],
            "tools": [t.as_dict() for t in getattr(team, "tools", {}).values()],
            "tool_links": [list(p) for p in self._team_tool_links()],
            "positions": pos, "sizes": sizes, "view": getattr(self, "agent_view_mode", "tab"),
        }

    def save_workspace(self):
        try:
            state = self._team_workspace_state()
            WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = WORKSPACE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, WORKSPACE_FILE)
        except Exception as e:  # noqa: BLE001
            print(f"[workspace] 儲存失敗：{e}")

    def _team_restore_workspace(self):
        """啟動時還原上次的代理工作區；沒有存檔時回傳 None（由呼叫端建立預設代理）。"""
        try:
            state = json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
        agents = state.get("agents") or []
        if not agents:
            return None
        self._team_restoring = True
        if not hasattr(self, "active_agent_id"):
            self.active_agent_id = None  # 啟動時還沒有任何代理
        idmap: Dict[str, str] = {}
        try:
            roots = [a for a in agents if not a.get("parent_id")]
            subs = [a for a in agents if a.get("parent_id")]
            for a in roots + subs:
                parent = idmap.get(a.get("parent_id")) if a.get("parent_id") else None
                slot = self.create_agent_slot(a.get("name") or None, parent_id=parent, focus=False)
                idmap[a["agent_id"]] = slot.agent_id
                self._team_restore_slot(slot, a)
            master = idmap.get(state.get("master"))
            if master:
                self._main_agent_id = master
            for x, y in state.get("links") or []:
                if x in idmap and y in idmap:
                    terminal_manager.link(idmap[x], idmap[y])
            if ToolNode is not None:
                for t in state.get("tools") or []:
                    try:
                        team.add_tool(ToolNode(**t))
                    except TypeError:
                        continue
                for t, a in state.get("tool_links") or []:
                    if a in idmap:
                        team.link_tool(t, idmap[a])
            for k, (x, y) in (state.get("positions") or {}).items():
                key = idmap.get(k, k)
                self.agent_canvas.positions[key] = QPointF(float(x), float(y))
            for k, wh in (state.get("sizes") or {}).items():
                if isinstance(wh, (list, tuple)) and len(wh) == 2:
                    key = idmap.get(k, k)
                    self.agent_canvas.sizes[key] = (float(wh[0]), float(wh[1]))
            active = idmap.get(state.get("active")) or next(iter(idmap.values()))
            self._update_agent_panel_names()
            self.switch_to_agent(active)
            if hasattr(self, "_refresh_nav_dots"):
                self._refresh_nav_dots()
            if hasattr(self, "_scroll_chat_to_bottom"):
                self._scroll_chat_to_bottom()
            view = state.get("view") or "tab"
            if view in ("split", "canvas"):
                QTimer.singleShot(0, lambda: self.set_agent_view(view))
            return self.agent_slots.get(active)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"[workspace] 還原失敗：{e}")
            return self.agent_slots.get(next(iter(idmap.values()))) if idmap else None
        finally:
            self._team_restoring = False

    def _team_restore_slot(self, slot, a: Dict[str, Any]):
        slot.model_id = a.get("model_id")
        session_id = a.get("session_id") or slot.session_id
        messages = None
        try:
            sess = self.history_manager.get_session(session_id)
            messages = (sess or {}).get("messages")
        except Exception:
            messages = None
        if not messages:  # 對話紀錄被清掉時，用工作區裡備份的文字還原
            messages = [{"role": m.get("role"), "text": m.get("text"), "img_b64": None} for m in a.get("messages") or []]
        slot.session_id = session_id
        slot.messages = list(messages)
        set_session = getattr(team, "set_session", None)
        if set_session:
            set_session(slot.agent_id, session_id)
        if slot.messages:
            slot.chat_browser.append("<div style='font-size:11px;color:#94a3b8;margin:8px 0;text-align:center;'>"
                                     "── 已還原上次的對話 ──</div>")
            for idx, m in enumerate(slot.messages):
                try:
                    self._render_bubble_html_for_slot(slot, m.get("role", "user"), m.get("text", ""),
                                                      m.get("img_b64"), msg_idx=idx)
                except Exception:
                    continue
            # 讓模型接得上之前的內容（之後太長會自動摘要）
            conv = [{"role": "system", "content": self.agent_brain.SYSTEM_PROMPT}]
            for m in slot.messages:
                conv.append({"role": "user" if m.get("role") == "user" else "assistant", "content": m.get("text", "")})
            self.agent_brain.conversations[session_id] = conv
            if hasattr(self, "_scroll_chat_to_bottom"):
                self._scroll_chat_to_bottom(slot.chat_browser)
        cwd = a.get("cwd")
        if cwd and os.path.isdir(cwd):
            terminal_manager._own_session(slot.agent_id).cwd = cwd
        u = a.get("usage") or {}
        usage = team.usage_of(slot.agent_id)
        if usage is not None and u:
            for k in ("context_tokens", "context_limit", "input_total", "output_total", "calls", "estimated", "model"):
                if k in u:
                    setattr(usage, k, u[k])
