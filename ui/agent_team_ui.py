# -*- coding: utf-8 -*-
"""
主視窗的「多代理團隊」整合（以 mixin 掛進 MainWindow）：

- 每個代理的分頁內容 = 用量條 ＋ 對話 ＋ 自己的終端機（上下可拖動調整）。
- 分頁列：主代理後面接它的子代理（↳），每個分頁下方有細用量條；右鍵可新增子代理。
- 代理畫布：卡片＋連線，拖線串接共用終端；畫布與分頁、並排監控三種檢視切換。
- 提供 core.agent_team 需要的 host 介面（建立子代理、送訊息、讀狀態），自動轉回 UI 執行緒。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QActionGroup, QHBoxLayout, QMenu, QPushButton, QSizePolicy, QSplitter, QVBoxLayout,
                             QWidget)

from core.agent_team import team
from core.agent_terminal import terminal_manager
from ui.agent_canvas import AgentCanvas, CanvasModel
from ui.agent_team_extras import AgentTeamExtrasMixin
from ui.agent_terminal_widget import AgentTerminalWidget
from ui.usage_bar import UsageBar, usage_text, usage_tooltip
from ui.font_scaler import WordFontScaleMixin, current_app_scale, hook_text_browser_scaling, scale_css_font_sizes

_TAB_ACTIVE = ("background: #283044; color: #38bdf8; border: 1px solid #38bdf8; border-radius: 6px;"
               " font-weight: bold; padding: 2px 10px; font-size: 12.5px;")
_TAB_IDLE = ("background: #1e2230; color: #94a3b8; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px;"
             " padding: 2px 10px; font-size: 12.5px;")
_TAB_SUB_IDLE = ("background: #171b26; color: #8391a7; border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;"
                 " padding: 2px 8px; font-size: 11.5px;")


class _Bridge(QObject):
    """背景執行緒 → UI 執行緒。"""
    call = pyqtSignal(object)
    team_event = pyqtSignal(str)


class AgentTeamMixin(AgentTeamExtrasMixin, WordFontScaleMixin):
    # ------------------------------------------------ 初始化
    def _team_setup(self, view_layout):
        self._font_scaler_setup()
        self._team_bridge = _Bridge()
        self._team_bridge.call.connect(lambda job: job())
        self._team_bridge.team_event.connect(self._team_on_event)
        self._team_pending: Dict[str, List[str]] = {}
        self._team_chats: Dict[str, dict] = {}
        self._team_restoring = False
        self._team_save_timer = QTimer(self)
        self._team_save_timer.setSingleShot(True)
        self._team_save_timer.timeout.connect(self.save_workspace)
        self._team_busy: set = set()
        self._team_ui_thread = threading.current_thread()
        try:
            from pathlib import Path
            terminal_manager.default_cwd = str(Path(__file__).resolve().parents[1])
        except Exception:
            pass
        team.set_host(self._team_host_create, self._team_host_ask, self._team_host_status)
        team.set_session_resolver(self._team_resolve_session)
        team.on_event(lambda kind, data: self._team_bridge.team_event.emit(kind))
        terminal_manager.on_change(lambda: self._team_bridge.team_event.emit("changed"))

        self.is_canvas_view = False
        self.agent_view_mode = "tab"       # tab | split | canvas
        self._last_non_canvas_view = "tab"
        self.agent_canvas = AgentCanvas(CanvasModel(
            nodes=self._team_canvas_nodes, links=terminal_manager.links, term_tail=self._team_term_tail,
            focus=self._team_canvas_focus, new_main=lambda: self._new_agent_from_bar(),
            new_sub=lambda aid: self.create_sub_agent(aid), close=lambda aid: self.close_agent_slot(aid),
            link=self._team_link, unlink=self._team_unlink, set_master=lambda aid: self.set_main_agent(aid),
            rename=lambda aid: self._rename_agent_dialog(aid),
            tools=self._team_tool_nodes, tool_links=self._team_tool_links, connect=self._team_connect,
            unlink_tool=self._team_unlink_tool, add_tool=self._team_add_tool, edit_tool=self._team_edit_tool,
            remove_tool=self._team_remove_tool, agent_menu_extra=self._team_agent_menu_extra,
            moved=self._team_schedule_save, pick_model=self._team_pick_model))
        self.agent_canvas_box = self._team_build_canvas_box(self.agent_canvas)
        self.agent_canvas_box.hide()
        view_layout.addWidget(self.agent_canvas_box)
        self._canvas_timer = QTimer(self)
        self._canvas_timer.timeout.connect(self._team_tick)
        self._canvas_timer.start(1000)
        self._hook_main_google_profile_roaming()
        try:
            from ui.syntra_evolution_hub import install_main_window_evolution
            QTimer.singleShot(0, lambda: install_main_window_evolution(self))
        except Exception as e:
            print(f"[AgentTeamMixin] install_main_window_evolution error: {e}")

    def _hook_main_google_profile_roaming(self):
        """
        1. 修復主視窗右側『🚀 登入 Google 帳號授權』原本 interactive=False 無法彈出瀏覽器的問題，
           改用非同步 GoogleLoginWorker 真實啟動 OAuth 流程，並在完成後自動詢問連回雲端個資。
        2. 於主視窗右側『🌐 Google & 習慣』分頁動態掛載『🔒 個資雲端漫遊』與『⚡ 日常桌面工具箱』按鈕列。
        """
        if getattr(self, "_profile_login_hooked", False):
            return
        self._profile_login_hooked = True

        def _real_main_login():
            import os
            from PyQt5.QtWidgets import QMessageBox
            from core.google_workspace_suite import google_suite
            from core.permissions import enabled_google_scopes
            from ui.google_signin_button import GoogleLoginWorker, prompt_cloud_profile_after_login

            # 若已有快取 token 先嘗試無感刷新
            if google_suite._try_authenticate(interactive=False):
                if hasattr(self, "_refresh_main_google_hub"):
                    self._refresh_main_google_hub()
                prompt_cloud_profile_after_login(
                    self, google_suite, getattr(self, "settings_manager", None)
                )
                if hasattr(self, "_refresh_main_google_hub"):
                    self._refresh_main_google_hub()
                return

            if not os.path.exists(google_suite.creds_path):
                # 直接引導開啟設定視窗的 Google 分頁匯入 credentials.json
                if hasattr(self, "open_settings_dialog"):
                    self.open_settings_dialog(initial_tab=5)
                return

            worker = getattr(self, "_main_google_worker", None)
            if worker is not None and worker.isRunning():
                return

            settings_mgr = getattr(self, "settings_manager", None)
            scopes = enabled_google_scopes(settings_mgr.get_raw()) if settings_mgr else None
            if not scopes:
                from core.google_workspace_suite import WORKSPACE_SCOPES
                scopes = WORKSPACE_SCOPES

            if hasattr(self, "lbl_main_google_status"):
                self.lbl_main_google_status.setText("🔵 <b>請在瀏覽器完成 Google 帳號授權…</b>")
                self.lbl_main_google_status.setStyleSheet("color: #60a5fa; font-size: 12.5px; font-weight: 600;")

            self._main_google_worker = GoogleLoginWorker(google_suite, scopes, self)

            def _on_done(ok: bool, err: str):
                if hasattr(self, "_refresh_main_google_hub"):
                    self._refresh_main_google_hub()
                if hasattr(self, "_update_google_login_button"):
                    self._update_google_login_button()
                if ok:
                    prompt_cloud_profile_after_login(self, google_suite, settings_mgr)
                    if hasattr(self, "_refresh_main_google_hub"):
                        self._refresh_main_google_hub()
                else:
                    QMessageBox.warning(self, "Google 登入未完成", err)

            self._main_google_worker.done.connect(_on_done)
            self._main_google_worker.start()

        self._main_login_google = _real_main_login
        QTimer.singleShot(0, self._inject_main_daily_and_vault_hub)

    def _inject_main_daily_and_vault_hub(self):
        """在主視窗右側『🌐 Google & 習慣』分頁注入真實可用的個資雲端同步與日常桌面整理/情境切換控制面板"""
        if getattr(self, "_daily_hub_injected", False):
            return
        txt_view = getattr(self, "txt_main_habit_view", None)
        if txt_view is None or txt_view.parentWidget() is None:
            return
        tab_widget = txt_view.parentWidget().parentWidget()
        if tab_widget is None or tab_widget.layout() is None:
            return
        self._daily_hub_injected = True
        tab_layout = tab_widget.layout()

        from PyQt5.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
        from core.user_profile_manager import user_profile_manager
        from core.daily_life_tools import (
            generate_wellbeing_report,
            organize_directory,
            switch_workspace_scene,
            undo_last_organize,
        )
        from core.google_workspace_suite import google_suite
        from ui.google_signin_button import prompt_cloud_profile_after_login

        # 1. 個資隔離與雲端連回卡片
        grp_vault = QGroupBox("🔒 個資隔離資料夾 & 雲端漫遊")
        v_lay = QVBoxLayout(grp_vault)
        v_lay.setSpacing(6)
        self.lbl_main_vault_path = QLabel(f"🛡️ 保護路徑：<code>{user_profile_manager.profile_dir}</code>")
        self.lbl_main_vault_path.setWordWrap(True)
        self.lbl_main_vault_path.setStyleSheet("color: #38bdf8; font-size: 11.5px;")
        v_lay.addWidget(self.lbl_main_vault_path)

        row_v = QHBoxLayout()
        btn_v_backup = QPushButton("☁️ 備份個資至雲端")
        btn_v_backup.setStyleSheet("padding: 5px 8px; font-size: 11.5px; font-weight: 600;")
        btn_v_restore = QPushButton("📥 從雲端詢問連回")
        btn_v_restore.setStyleSheet("padding: 5px 8px; font-size: 11.5px;")
        btn_v_open = QPushButton("📂 開啟資料夾")
        btn_v_open.setStyleSheet("padding: 5px 8px; font-size: 11.5px;")

        def _do_backup():
            if not google_suite.is_authenticated():
                QMessageBox.warning(self, "尚未登入", "請先點擊上方「🚀 登入 Google 帳號授權」再備份至雲端。")
                return
            res = user_profile_manager.sync_to_cloud(google_suite, getattr(self, "settings_manager", None))
            if res.get("success"):
                QMessageBox.information(self, "備份成功", "☁️ 已將個人化資料與長期記憶（已剔除金鑰）備份至您的 Google Drive！")
            else:
                QMessageBox.warning(self, "備份失敗", str(res.get("error")))

        def _do_restore():
            if not google_suite.is_authenticated():
                QMessageBox.warning(self, "尚未登入", "請先點擊上方「🚀 登入 Google 帳號授權」再從雲端連回。")
                return
            prompt_cloud_profile_after_login(self, google_suite, getattr(self, "settings_manager", None))
            if hasattr(self, "_refresh_main_google_hub"):
                self._refresh_main_google_hub()

        def _do_open_dir():
            import os
            p = str(user_profile_manager.profile_dir)
            os.makedirs(p, exist_ok=True)
            try:
                os.startfile(p)
            except Exception:
                pass

        btn_v_backup.clicked.connect(_do_backup)
        btn_v_restore.clicked.connect(_do_restore)
        btn_v_open.clicked.connect(_do_open_dir)
        row_v.addWidget(btn_v_backup)
        row_v.addWidget(btn_v_restore)
        row_v.addWidget(btn_v_open)
        v_lay.addLayout(row_v)
        tab_layout.addWidget(grp_vault)

        # 2. 日常電腦助手快捷面板（檔案整理 + 情境切換 + 用機報告）
        grp_daily = QGroupBox("⚡ 日常桌面整理與情境切換")
        d_lay = QVBoxLayout(grp_daily)
        d_lay.setSpacing(6)

        row_org = QHBoxLayout()
        btn_org_dl = QPushButton("🧹 整理下載區")
        btn_org_desk = QPushButton("🖥️ 整理桌面")
        btn_org_undo = QPushButton("↩️ 還原整理")
        btn_wellbeing = QPushButton("📊 用機報告")
        for b in (btn_org_dl, btn_org_desk, btn_org_undo, btn_wellbeing):
            b.setStyleSheet("padding: 5px 6px; font-size: 11.5px;")
            row_org.addWidget(b)
        d_lay.addLayout(row_org)

        def _confirm_and_organize(target_key: str, label_name: str):
            pre = organize_directory(target_key, dry_run=True)
            if not pre.get("ok"):
                QMessageBox.warning(self, "整理提示", str(pre.get("error")))
                return
            cnt = pre.get("total_moved", 0)
            if cnt == 0:
                QMessageBox.information(self, "無須整理", f"✨ 您的{label_name}目前沒有需要分類歸檔的雜亂檔案！")
                return
            preview_lines = "\n".join(pre.get("preview", [])[:10])
            ans = QMessageBox.question(
                self,
                f"確認整理{label_name}",
                f"預覽發現共有 {cnt} 個檔案可自動歸檔至分類子資料夾：\n\n"
                f"{preview_lines}\n"
                f"{'...(更多)' if cnt > 10 else ''}\n\n"
                f"確定要立即整理嗎？（事後隨時可點「↩️ 還原整理」復原）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ans == QMessageBox.Yes:
                res = organize_directory(target_key, dry_run=False)
                txt_view.setPlainText(
                    f"✅ 已完成{label_name}自動歸檔（共搬移 {res.get('total_moved', 0)} 個檔案）：\n"
                    + "\n".join(res.get("preview", []))
                )

        def _do_undo_org():
            res = undo_last_organize()
            if res.get("ok"):
                QMessageBox.information(self, "還原完成", f"↩️ 已將 {res.get('restored_count', 0)} 個檔案還原回原本位置！")
            else:
                QMessageBox.information(self, "還原提示", str(res.get("error")))

        def _do_wellbeing():
            rep = generate_wellbeing_report(hours=12)
            cats = rep.get("category_minutes", {})
            lines = [
                f"📊 【近 12 小時電腦用機統計】總活躍：{rep.get('total_active_minutes', 0)} 分鐘",
                *(f"  • {k}：{v} 分鐘" for k, v in cats.items()),
                f"\n💡 護眼建議：{rep.get('health_advice', '')}",
            ]
            txt_view.setPlainText("\n".join(lines))

        btn_org_dl.clicked.connect(lambda: _confirm_and_organize("downloads", "下載區"))
        btn_org_desk.clicked.connect(lambda: _confirm_and_organize("desktop", "桌面"))
        btn_org_undo.clicked.connect(_do_undo_org)
        btn_wellbeing.clicked.connect(_do_wellbeing)

        row_scene = QHBoxLayout()
        for s_label, s_code in [("💻 工作", "work"), ("🎤 開會", "meeting"), ("🎮 娛樂", "entertainment"), ("🌿 休息", "rest")]:
            bs = QPushButton(s_label)
            bs.setStyleSheet("padding: 5px 6px; font-size: 11.5px; font-weight: 600;")

            def _switch_s(_chk=False, code=s_code):
                res = switch_workspace_scene(code, getattr(self, "settings_manager", None))
                if hasattr(self, "lbl_context"):
                    self.lbl_context.setText(res.get("title", "🟢 待命"))
                min_list = res.get("minimized_windows") or []
                extra = f"\n（已自動收起干擾視窗：{', '.join(min_list)}）" if min_list else ""
                txt_view.setPlainText(f"🎯 已切換至【{res.get('title')}】\n{res.get('description')}{extra}")

            bs.clicked.connect(_switch_s)
            row_scene.addWidget(bs)
        d_lay.addLayout(row_scene)
        tab_layout.addWidget(grp_daily)

    # ------------------------------------------------ 執行緒工具
    def _team_in_ui(self, fn: Callable[[], Any], timeout: float = 15.0) -> Any:
        if threading.current_thread() is self._team_ui_thread:
            return fn()
        box: Dict[str, Any] = {}
        done = threading.Event()

        def job():
            try:
                box["v"] = fn()
            except Exception as e:  # noqa: BLE001
                box["e"] = e
            finally:
                done.set()
        self._team_bridge.call.emit(job)
        if not done.wait(timeout):
            return None
        if "e" in box:
            raise box["e"]
        return box.get("v")

    # ------------------------------------------------ 代理建立 / 關閉
    def _team_on_slot_created(self, slot, parent_id: Optional[str]):
        slot.parent_id = parent_id
        if getattr(slot, "chat_browser", None) is not None:
            hook_text_browser_scaling(slot.chat_browser)
        team.add(slot.agent_id, slot.name, slot.session_id, parent_id)

    def _team_on_slot_closed(self, agent_id: str):
        self.stop_agent_chat(agent_id)
        self.agent_canvas.positions.pop(agent_id, None)
        self._team_schedule_save()
        self._team_pending.pop(agent_id, None)
        self._team_busy.discard(agent_id)
        for cid in team.remove(agent_id):
            child = self.agent_slots.get(cid)
            if child is not None:
                child.parent_id = None  # 主代理被關：子代理升為主代理
        self._team_bridge.team_event.emit("changed")

    def _team_build_container(self, slot) -> QWidget:
        """分頁內容：用量條＋對話＋終端。"""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        slot.usage_bar = UsageBar(compact=False)
        slot.usage_bar.setContentsMargins(8, 0, 8, 0)
        bar_wrap = QWidget()
        bl = QHBoxLayout(bar_wrap)
        bl.setContentsMargins(10, 2, 10, 2)
        bl.addWidget(slot.usage_bar)
        lay.addWidget(bar_wrap)
        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(5)
        split.setChildrenCollapsible(True)
        split.addWidget(slot.chat_browser)
        slot.chat_split = split
        slot.terminal_widget = AgentTerminalWidget(slot.agent_id, terminal_manager, self._team_name_of)
        split.addWidget(slot.terminal_widget)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([620, 170])
        lay.addWidget(split, 1)
        slot.container = box
        return box

    def create_sub_agent(self, parent_id: str, name: Optional[str] = None, focus: bool = True):
        if parent_id not in self.agent_slots:
            return None
        parent = self.agent_slots[parent_id]
        if getattr(parent, "parent_id", None):  # 子代理不能再開子代理：改掛在它的主代理下
            parent_id = parent.parent_id
        n = len(team.children(parent_id)) + 1
        return self.create_agent_slot(name or f"子代理 {n}", parent_id=parent_id, focus=focus)

    # ------------------------------------------------ host 介面（給 core.agent_team）
    def _team_host_create(self, parent_id: Optional[str], name: str) -> Optional[str]:
        def make():
            prev = getattr(self, "active_agent_id", None)
            slot = self.create_sub_agent(parent_id, name, focus=False) if parent_id else \
                self.create_agent_slot(name, focus=False)
            if prev in self.agent_slots:
                self.switch_to_agent(prev)
            return slot.agent_id if slot else None
        return self._team_in_ui(make)

    def _team_host_ask(self, agent_id: str, text: str) -> bool:
        def ask():
            if agent_id not in self.agent_slots:
                return False
            self._team_busy.add(agent_id)
            fut = self._turn_by_agent.get(agent_id)
            if fut is not None and not fut.done():
                self._team_pending.setdefault(agent_id, []).append(text)
                return True
            ok = self._team_send_now(agent_id, text)
            if not ok:
                self._team_busy.discard(agent_id)
            return ok
        return bool(self._team_in_ui(ask))

    def _team_host_status(self, agent_id: str) -> Tuple[str, str]:
        slot = self.agent_slots.get(agent_id)
        if slot is None:
            return "CLOSED", ""
        last = ""
        for m in reversed(slot.messages):
            if m.get("role") == "agent":
                last = m.get("text") or ""
                break
        busy = slot.status == "RUNNING" or agent_id in self._team_busy or bool(self._team_pending.get(agent_id))
        return ("RUNNING" if busy else (slot.status or "IDLE")), last

    def _team_resolve_session(self, session_id: str) -> Optional[str]:
        for aid, s in self.agent_slots.items():
            if s.session_id == session_id:
                return aid
        return None

    def _team_send_now(self, agent_id: str, text: str) -> bool:
        """在不打擾使用者目前畫面與輸入框的情況下，替指定代理送出一輪。"""
        slot = self.agent_slots.get(agent_id)
        if slot is None:
            return False
        prev = getattr(self, "active_agent_id", None)
        draft = self.input_text.toPlainText()
        files, shot = list(self.attached_files), self.attached_screenshot_b64
        self.attached_files, self.attached_screenshot_b64 = [], None
        before = len(slot.messages)
        try:
            self.switch_to_agent(agent_id)
            self.send_current_prompt(text, allow_commands=False)
        finally:
            self.attached_files, self.attached_screenshot_b64 = files, shot
            if self.input_text.toPlainText() != draft:
                self.input_text.setPlainText(draft)
            if prev in self.agent_slots and prev != agent_id:
                self.switch_to_agent(prev)
        return len(slot.messages) > before

    def _team_after_reply(self, agent_id: str):
        """某個代理這一輪結束：送出排隊中的訊息，或標記為空閒。"""
        self._team_chat_after_reply(agent_id)  # 代理互相對話：把回覆轉給對方
        self._team_schedule_save()
        queue = self._team_pending.get(agent_id) or []
        if queue:
            text = queue.pop(0)
            QTimer.singleShot(150, lambda: self._team_send_now(agent_id, text) or self._team_busy.discard(agent_id))
        else:
            self._team_busy.discard(agent_id)
        self._team_bridge.team_event.emit("usage")

    # ------------------------------------------------ 分頁列
    def _team_ordered_ids(self) -> List[str]:
        ids = list(self.agent_slots)
        out: List[str] = []
        for aid in ids:
            if not getattr(self.agent_slots[aid], "parent_id", None):
                out.append(aid)
                out.extend(c for c in ids if getattr(self.agent_slots[c], "parent_id", None) == aid)
        out.extend(a for a in ids if a not in out)
        return out

    def _team_name_of(self, agent_id: str) -> str:
        if agent_id == "user":
            return "你"
        s = self.agent_slots.get(agent_id)
        return s.name if s else agent_id

    def _team_make_tab(self, aid: str, can_close: bool) -> QWidget:
        slot = self.agent_slots[aid]
        is_sub = bool(getattr(slot, "parent_id", None))
        status_dot = "⏳" if slot.status == "RUNNING" else ("✅" if slot.status == "DONE" else "🟢")
        label = f"{'↳ ' if is_sub else ''}{status_dot} {self._agent_display_name(aid)}"
        u = team.usage_of(aid)
        ud = u.as_dict() if u else None
        if aid in team.members and team.members[aid].name != slot.name:
            team.members[aid].name = slot.name  # 同步改名（不發事件，避免重畫中又重畫）
        model = self._team_model_label(aid)
        if model:
            label += f" · {model}"
        self._team_schedule_save()

        tab = QWidget()
        tab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)  # 分頁照內容寬度，不被用量條撐開
        v = QVBoxLayout(tab)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        scale = current_app_scale()
        btn = QPushButton(label)
        btn.setMinimumHeight(max(24, int(round(24 * scale))))
        raw_tab_qss = _TAB_ACTIVE if aid == getattr(self, "active_agent_id", None) else (_TAB_SUB_IDLE if is_sub else _TAB_IDLE)
        btn.setProperty("_orig_qss", raw_tab_qss)
        scaled_tab_qss = scale_css_font_sizes(raw_tab_qss, scale)
        btn.setProperty("_last_scaled_qss", scaled_tab_qss)
        btn.setStyleSheet(scaled_tab_qss)
        btn.clicked.connect(lambda _, a=aid: self.switch_to_agent(a))
        btn.setToolTip(usage_tooltip(ud) + f"\n使用模型：{model or '跟隨全域設定'}"
                       + "\n\n右鍵：新增子代理、模型、對話、掛載、設為主控、重新命名、關閉")
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda pos, a=aid, w=btn: self._team_tab_menu(a, w, pos))
        row.addWidget(btn)
        if can_close:
            bx = QPushButton("✕")
            bx.setFixedSize(20, 20)
            bx.setToolTip(f"關閉 {slot.name}")
            bx.setCursor(Qt.PointingHandCursor)
            bx.setStyleSheet("QPushButton { background: transparent; border: none; color: #94a3b8; border-radius: 4px;"
                             " padding: 0; font-size: 11px; } QPushButton:hover { background: rgba(239,68,68,0.25);"
                             " color: #f87171; }")
            bx.clicked.connect(lambda _, a=aid: self.close_agent_slot(a))
            row.addWidget(bx)
        v.addLayout(row)
        bar = UsageBar(compact=True)
        bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        bar.set_usage(ud)
        bar.setFixedHeight(3)
        v.addWidget(bar)
        return tab

    def _team_tab_menu(self, agent_id: str, widget, pos):
        if agent_id not in self.agent_slots:
            return
        is_master = agent_id == getattr(self, "_main_agent_id", None)
        is_sub = bool(getattr(self.agent_slots[agent_id], "parent_id", None))
        menu = QMenu(self)
        a_switch = menu.addAction("切換到這個代理")
        a_sub = menu.addAction("＋ 新增子代理（屬於它的主代理）" if is_sub else "＋ 新增子代理")
        a_master = menu.addAction("⭐ 已是主控" if is_master else "⭐ 設為主控")
        a_master.setEnabled(not is_master)
        a_rename = menu.addAction("✏️ 重新命名…")
        a_canvas = menu.addAction("🕸 在畫布上查看")
        menu.addSeparator()
        extra = self._team_agent_menu_extra(agent_id, menu)
        menu.addSeparator()
        a_new = menu.addAction("＋ 新增主代理")
        a_close = menu.addAction("✕ 關閉這個代理")
        a_close.setEnabled(len(self.agent_slots) > 1)
        chosen = menu.exec_(widget.mapToGlobal(pos))
        if chosen is a_switch:
            self.switch_to_agent(agent_id)
        elif chosen is a_sub:
            self.create_sub_agent(agent_id)
        elif chosen is a_master:
            self.set_main_agent(agent_id)
        elif chosen is a_rename:
            self._rename_agent_dialog(agent_id)
        elif chosen is a_canvas:
            self.toggle_canvas_view(True)
        elif chosen is a_new:
            self._new_agent_from_bar()
        elif chosen is a_close:
            self.close_agent_slot(agent_id)
        elif chosen is not None:
            extra(chosen)

    # ------------------------------------------------ 三種檢視：分頁 / 並排監控 / 代理畫布
    def set_agent_view(self, mode: str):
        if mode not in ("tab", "split", "canvas"):
            return
        self.agent_view_mode = mode
        if mode != "canvas":
            self._last_non_canvas_view = mode
        self.is_split_view = mode == "split"
        self.is_canvas_view = mode == "canvas"
        for slot in self.agent_slots.values():
            self._team_place_chat(slot)
        self.agent_stack.setVisible(mode == "tab")
        self.agent_split.setVisible(mode == "split")
        self.agent_canvas_box.setVisible(mode == "canvas")
        active = self.agent_slots.get(getattr(self, "active_agent_id", None))
        if mode == "tab" and active is not None:
            self.agent_stack.setCurrentWidget(active.container or active.chat_browser)
        btn = getattr(self, "btn_toggle_split", None)
        if btn is not None:
            btn.setText("🗖 分頁聚焦" if mode == "split" else "🗗 並排監控")
            btn.setStyleSheet("background: #0284c7; color: white;" if mode == "split" else "")
        if mode == "canvas":
            self.agent_canvas.refresh()
            QTimer.singleShot(60, self.agent_canvas.fit_all)
        self._team_schedule_save()

    def toggle_canvas_view(self, on: Optional[bool] = None):
        on = (self.agent_view_mode != "canvas") if on is None else on
        self.set_agent_view("canvas" if on else self._last_non_canvas_view)

    def _team_place_chat(self, slot):
        """對話框只能有一個位置：並排監控時放進並排面板，其他時候放回分頁（終端上方）。"""
        b = slot.chat_browser
        if getattr(self, "agent_view_mode", "tab") == "split" and slot.panel_widget is not None:
            lay = slot.panel_widget.layout()
            if b.parentWidget() is not slot.panel_widget and lay is not None:
                lay.insertWidget(1, b, 1)
        else:
            sp = getattr(slot, "chat_split", None)
            if sp is not None and b.parentWidget() is not sp:
                sp.insertWidget(0, b)
                sp.setStretchFactor(0, 4)
        b.show()

    def _team_build_view_menu(self, menu: QMenu):
        group = QActionGroup(menu)
        group.setExclusive(True)
        acts = {}
        for mode, text in (("tab", "🗖 分頁（一次看一個代理）"), ("split", "🗗 並排監控"),
                           ("canvas", "🕸 代理畫布（拖線串接代理）")):
            a = menu.addAction(text, lambda m=mode: self.set_agent_view(m))
            a.setCheckable(True)
            group.addAction(a)
            acts[mode] = a
        self._act_split_view = acts["split"]
        menu.aboutToShow.connect(lambda: acts[getattr(self, "agent_view_mode", "tab")].setChecked(True))

    def _team_canvas_nodes(self) -> List[dict]:
        nodes = []
        for aid in self._team_ordered_ids():
            s = self.agent_slots[aid]
            preview = ""
            for m in reversed(s.messages):
                if m.get("role") in ("agent", "user") and m.get("text"):
                    preview = ("你：" if m["role"] == "user" else "") + m["text"]
                    break
            u = team.usage_of(aid)
            nodes.append({"id": aid, "name": s.name, "is_main": not getattr(s, "parent_id", None),
                          "is_master": aid == getattr(self, "_main_agent_id", None),
                          "parent": getattr(s, "parent_id", None), "status": s.status, "preview": preview[:900],
                          "usage": u.as_dict() if u else {}, "active": aid == getattr(self, "active_agent_id", None),
                          "model": self._team_model_label(aid), "model_display": self._team_model_display(aid)})
        return nodes

    def _team_term_tail(self, agent_id: str) -> List[str]:
        try:
            sess = terminal_manager.session_for(agent_id)
        except Exception:
            return []
        lines = []
        for event, text, _by in sess.tail(20):
            if event == "cmd":
                lines.append("PS> " + (text.splitlines() or [""])[0])
            elif event in ("out", "info") and text.strip():
                lines.append(text)
        return lines[-14:]

    def _team_canvas_focus(self, agent_id: str):
        self.set_agent_view(self._last_non_canvas_view)
        self.switch_to_agent(agent_id)

    def _team_link(self, a: str, b: str):
        if terminal_manager.link(a, b):
            self.statusBar().showMessage(f"🔗 已串接 {self._team_name_of(a)} ↔ {self._team_name_of(b)}："
                                         f"共用終端並可互傳訊息", 5000)

    def _team_unlink(self, a: str, b: str):
        if terminal_manager.unlink(a, b):
            self.statusBar().showMessage(f"✂ 已斷開 {self._team_name_of(a)} ↔ {self._team_name_of(b)}", 4000)

    # ------------------------------------------------ 更新
    def _team_on_event(self, kind: str):
        # 這是 Qt 訊號處理函式：任何例外都不能往外丟，否則 PyQt 會直接結束整個程式
        try:
            self._team_on_event_impl(kind)
        except Exception:
            import traceback
            traceback.print_exc()

    def _team_on_event_impl(self, kind: str):
        if not hasattr(self, "agent_bar_layout"):
            return
        self._team_schedule_save()
        if kind in ("usage", "changed", "spawned"):
            for aid, s in self.agent_slots.items():
                bar = getattr(s, "usage_bar", None)
                if bar is not None:
                    u = team.usage_of(aid)
                    bar.set_usage(u.as_dict() if u else None)
            self._refresh_agent_tab_bar()
        if self.is_canvas_view:
            if kind == "changed":
                self.agent_canvas.refresh()
            else:
                self.agent_canvas.update_cards()

    def _team_tick(self):
        try:
            self._team_tick_impl()
        except Exception:
            import traceback
            traceback.print_exc()

    def _team_tick_impl(self):
        if self.is_canvas_view and self.agent_canvas.isVisible():
            if set(self.agent_canvas.cards) != set(self.agent_slots):
                self.agent_canvas.refresh()
            else:
                self.agent_canvas.update_cards()

    def _team_shutdown(self):
        try:
            self._team_save_timer.stop()
            self.save_workspace()
        except Exception:
            pass
        try:
            terminal_manager.shutdown()
        except Exception:
            pass


__all__ = ["AgentTeamMixin", "usage_text"]
