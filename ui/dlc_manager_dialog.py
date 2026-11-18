# -*- coding: utf-8 -*-
"""
ui/dlc_manager_dialog.py
========================
Syntra 星樞 · 專屬獨立圖形化 DLC 與模組擴充管理器 (GUI DLC Manager)
提供卡片式瀏覽、官方 Ed25519 簽章認證狀態、一鍵安裝/啟用/停用、
線上兌換碼解鎖、以及外部 ZIP/資料夾模組包匯入。
"""

from __future__ import annotations

import os
import shutil
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
    QFrame,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QLineEdit,
)

from core.addon_module_manager import addon_module_manager
from core.hot_update_manager import hot_update_manager
from core.licensing import has_valid_dlc_license, save_dlc_license_token, verify_license_token
from core.user_profile_manager import user_profile_manager
from core.i18n import t

DLC_REDEEM_URL = "https://syntraagent.keli260530.workers.dev/#dlc-marketplace"


class DlcManagerDialog(QDialog):
    """獨立高質感暗黑風 DLC / Mod 擴充管理器對話框"""

    sig_dlc_changed = pyqtSignal()

    def __init__(self, settings_manager=None, parent=None):
        # 傳入 parent=None 讓它成為完全獨立的頂級視窗，不再作為附屬子對話框
        super().__init__(None)
        self.settings_manager = settings_manager
        self.setWindowTitle("🧩 Syntra 擴充模組與 DLC 管理器 (GUI)")
        
        # 明確指定為標準獨立視窗，確保 Windows 頂部標題列具備完整的「縮小」、「最大化/全螢幕」、「關閉」按鈕
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        # 強制移除 QDialog 預設的 "?" 說明按鈕
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        
        self.resize(920, 700)
        self.setMinimumSize(640, 480)
        self._init_ui()
        self.refresh_list()

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0b0f19;
                color: #f1f5f9;
                font-family: 'Segoe UI', 'Microsoft JhengHei UI', sans-serif;
            }
            QLabel {
                color: #f1f5f9;
            }
            QScrollArea {
                border: 1px solid #1e293b;
                background-color: transparent;
                border-radius: 8px;
            }
            QScrollBar:vertical {
                background: #0f172a;
                width: 10px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QScrollBar:horizontal {
                height: 0px;
            }
            QPushButton {
                background-color: #1e293b;
                color: #f1f5f9;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 11.5px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QPushButton#primaryBtn {
                background-color: #2563eb;
                border-color: #3b82f6;
                color: #ffffff;
            }
            QPushButton#primaryBtn:hover {
                background-color: #1d4ed8;
            }
            QPushButton#successBtn {
                background-color: #059669;
                border-color: #10b981;
                color: #ffffff;
            }
            QPushButton#successBtn:hover {
                background-color: #047857;
            }
            QPushButton#dangerBtn {
                background-color: #dc2626;
                border-color: #ef4444;
                color: #ffffff;
            }
            QPushButton#dangerBtn:hover {
                background-color: #b91c1c;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 頂部標題與說明橫幅
        top_box = QFrame()
        top_box.setStyleSheet("background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 12px;")
        top_layout = QVBoxLayout(top_box)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(6)

        title_lbl = QLabel("<h2 style='margin:0; color:#60a5fa;'>🧩 可選配專業模組 (DLC / Mod) 管理中心</h2>")
        desc_lbl = QLabel(
            "Syntra 核心架構秉持純淨無毒原則，所有高權限或領域專屬功能均採選配 DLC 式架構。\n"
            "所有官方模組皆具備 Ed25519 密碼學防篡改數位簽章，啟用前嚴格落實知情同意，個資一律留存本機。"
        )
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.5;")
        desc_lbl.setWordWrap(True)

        top_layout.addWidget(title_lbl)
        top_layout.addWidget(desc_lbl)
        layout.addWidget(top_box)

        # 功能工具列（改用兩列或精緻緊湊排版，避免小寬度切字）
        bar = QHBoxLayout()
        bar.setSpacing(8)

        btn_redeem = QPushButton("🔑 貼上兌換碼")
        btn_redeem.setObjectName("primaryBtn")
        btn_redeem.setToolTip("貼上 Ed25519 授權 Token 線上/離線解鎖 DLC")
        btn_redeem.clicked.connect(self._on_redeem_token)
        bar.addWidget(btn_redeem)

        btn_import_zip = QPushButton("📦 匯入套件包")
        btn_import_zip.setToolTip("選取 .zip 模組包或 .json 授權檔匯入")
        btn_import_zip.clicked.connect(self._on_import_zip)
        bar.addWidget(btn_import_zip)

        btn_scan_dl = QPushButton("🔍 掃描「下載」區")
        btn_scan_dl.setToolTip("自動掃描 Downloads 資料夾中的 DLC 壓縮包")
        btn_scan_dl.clicked.connect(self._on_scan_downloads)
        bar.addWidget(btn_scan_dl)

        btn_shop = QPushButton("🌐 官方 DLC 市集")
        btn_shop.setToolTip("前往官方市集瀏覽最新可選配模組")
        btn_shop.clicked.connect(lambda: webbrowser.open(DLC_REDEEM_URL))
        bar.addWidget(btn_shop)

        bar.addStretch()

        btn_refresh = QPushButton("🔄 重新整理")
        btn_refresh.clicked.connect(self.refresh_list)
        bar.addWidget(btn_refresh)

        layout.addLayout(bar)

        # 模組清單滾動區（強制禁用水平滾動條，卡片自動適應寬度換行）
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(8, 8, 8, 8)
        self.card_layout.setSpacing(10)
        self.scroll.setWidget(self.card_container)
        layout.addWidget(self.scroll, stretch=1)

        # 底部狀態列
        bottom_box = QHBoxLayout()
        self.lbl_summary = QLabel("載入中...")
        self.lbl_summary.setStyleSheet("color: #64748b; font-size: 12px;")
        bottom_box.addWidget(self.lbl_summary)
        bottom_box.addStretch()

        btn_close = QPushButton("關閉")
        btn_close.clicked.connect(self.accept)
        bottom_box.addWidget(btn_close)
        layout.addLayout(bottom_box)

    def refresh_list(self):
        """重新整理與渲染所有 DLC 卡片"""
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 1. 官方 Security Shield DLC
        self._render_security_shield_card()

        # 2. 官方 Office Flow DLC 與已安裝的其他 DLC 模組
        installed_addons = addon_module_manager.discover_modules()
        for addon in installed_addons:
            if addon.get("id") == "official_security_shield":
                continue
            self._render_addon_card(addon)

        # 3. 官方市集精選（若未安裝則顯示推薦卡片）
        self._render_store_suggestions(installed_addons)

        self.card_layout.addStretch()
        active_plugins = addon_module_manager.get_active_plugins()
        self.lbl_summary.setText(f"目前共掛載 {len(active_plugins)} 個作用中擴充模組 ｜ 儲存庫：modules/ ＆ dlc/")

    def _render_security_shield_card(self):
        """渲染官方資安盾卡片"""
        shield_dir = Path(__file__).resolve().parent.parent / "dlc" / "official_security_shield"
        installed = shield_dir.exists()
        licensed, reason = has_valid_dlc_license(self.settings_manager, "syntra.dlc.security_shield")

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #0f1c24;
                border: 1px solid #144046;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        lay = QVBoxLayout(card)
        lay.setSpacing(8)

        # 第一行：名稱與狀態標籤
        r1 = QHBoxLayout()
        r1.setSpacing(10)
        title = QLabel("<b style='font-size:14px; color:#38bdf8;'>🛡️ 官方資安盾 (Security Shield DLC)</b>")
        r1.addWidget(title)

        if installed and licensed:
            badge = QLabel("<span style='background:#064e3b; color:#34d399; padding:3px 8px; border-radius:4px; font-weight:700;'>🟢 已啟用</span>")
        elif installed:
            badge = QLabel("<span style='background:#78350f; color:#fde047; padding:3px 8px; border-radius:4px; font-weight:700;'>🟡 未授權</span>")
        else:
            badge = QLabel("<span style='background:#1f2937; color:#94a3b8; padding:3px 8px; border-radius:4px; font-weight:700;'>⚪ 未安裝</span>")
        badge.setTextFormat(Qt.RichText)
        r1.addWidget(badge)
        r1.addStretch()

        if installed and not licensed:
            btn_redeem = QPushButton("🔑 貼上授權解鎖")
            btn_redeem.setObjectName("primaryBtn")
            btn_redeem.clicked.connect(self._on_redeem_token)
            r1.addWidget(btn_redeem)

        if not installed:
            btn_get = QPushButton("🌐 前往下載/兌換")
            btn_get.setObjectName("primaryBtn")
            btn_get.clicked.connect(lambda: webbrowser.open(DLC_REDEEM_URL))
            r1.addWidget(btn_get)
        else:
            btn_del = QPushButton("🗑️ 解除安裝")
            btn_del.setObjectName("dangerBtn")
            btn_del.clicked.connect(self._on_uninstall_shield)
            r1.addWidget(btn_del)

        lay.addLayout(r1)

        # 狀態說明文字（如果是未授權，顯示在獨立換行提示中，絕不擠壓排版）
        if installed and not licensed:
            lbl_warn = QLabel(f"<span style='color:#fbbf24; font-size:11px;'>⚠️ 狀態提示：{reason}</span>")
            lbl_warn.setTextFormat(Qt.RichText)
            lay.addWidget(lbl_warn)

        # 說明
        desc = QLabel(
            "專為嚴苛資安環境打造的進階進程防護套件。內建記憶體寫入鑑識、非對稱數位簽章認證、"
            "動態惡意行為偵測與微軟 Defender 白名單防禦相容。"
        )
        desc.setStyleSheet("color:#94a3b8; font-size:12px;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.card_layout.addWidget(card)

    def _render_addon_card(self, addon: Dict[str, Any]):
        """渲染標準 Addon 模組卡片"""
        mod_id = addon.get("id", "")
        name = addon.get("name", mod_id)
        ver = addon.get("version", "1.0.0")
        desc_text = addon.get("description", "（無描述）")
        is_enabled = addon_module_manager.is_enabled(mod_id)

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        lay = QVBoxLayout(card)
        lay.setSpacing(8)

        r1 = QHBoxLayout()
        title = QLabel(f"<b style='font-size:14px; color:#f8fafc;'>🧩 {name}</b> <span style='color:#64748b; font-size:11px;'>v{ver}</span>")
        r1.addWidget(title)

        if is_enabled:
            badge = QLabel("<span style='background:#064e3b; color:#34d399; padding:3px 8px; border-radius:4px; font-weight:700;'>🟢 運作中</span>")
        else:
            badge = QLabel("<span style='background:#374151; color:#9ca3af; padding:3px 8px; border-radius:4px;'>⚪ 已停用</span>")
        badge.setTextFormat(Qt.RichText)
        r1.addWidget(badge)
        r1.addStretch()

        # 開關切換按鈕
        btn_toggle = QPushButton("停用模組" if is_enabled else "啟用模組")
        if is_enabled:
            btn_toggle.clicked.connect(lambda _, m=mod_id: self._on_toggle_addon(m, False))
        else:
            btn_toggle.setObjectName("successBtn")
            btn_toggle.clicked.connect(lambda _, m=mod_id: self._on_toggle_addon(m, True))
        r1.addWidget(btn_toggle)

        # 刪除按鈕
        btn_remove = QPushButton("🗑️ 移除")
        btn_remove.setObjectName("dangerBtn")
        btn_remove.clicked.connect(lambda _, m=mod_id, n=name: self._on_uninstall_addon(m, n))
        r1.addWidget(btn_remove)

        lay.addLayout(r1)

        desc = QLabel(desc_text)
        desc.setStyleSheet("color:#94a3b8; font-size:12px;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        # 列出提供的工具
        tools = addon.get("tools", [])
        if tools:
            tool_names = [t.get("name", "") for t in tools if isinstance(t, dict)]
            lbl_tools = QLabel(f"<span style='color:#60a5fa; font-size:11px;'>提供工具：</span> <code>{', '.join(tool_names)}</code>")
            lbl_tools.setStyleSheet("font-size:11px; color:#cbd5e1;")
            lay.addWidget(lbl_tools)

        self.card_layout.addWidget(card)

    def _render_store_suggestions(self, installed_addons):
        """如果還有官方熱門 DLC 尚未安裝，列在下方供一鍵獲取"""
        installed_ids = {a.get("id") for a in installed_addons}
        if "office_flow" not in installed_ids:
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: #18181b;
                    border: 1px dashed #3f3f46;
                    border-radius: 8px;
                    padding: 12px;
                }
            """)
            lay = QVBoxLayout(card)
            r1 = QHBoxLayout()
            title = QLabel("<b style='font-size:13.5px; color:#a1a1aa;'>📊 Office Flow DLC (辦公文檔批次自動化流水線)</b>")
            r1.addWidget(title)
            r1.addStretch()
            btn_shop = QPushButton("🛒 獲取模組 (NT$ 99)")
            btn_shop.setObjectName("primaryBtn")
            btn_shop.clicked.connect(lambda: webbrowser.open(DLC_REDEEM_URL))
            r1.addWidget(btn_shop)
            lay.addLayout(r1)

            desc = QLabel("多代理自動清洗 Excel、Word、PDF 報表並自動產生簡報與郵件發送。隨選隨裝，未安裝不佔用空間。")
            desc.setStyleSheet("color:#71717a; font-size:12px;")
            lay.addWidget(desc)
            self.card_layout.addWidget(card)

    # ================= 互動動作 =================

    def _on_redeem_token(self):
        token, ok = QInputDialog.getText(
            self,
            "兌換 DLC 授權碼",
            "請貼上官方發布之 Ed25519 授權 Token：\n（例如：eyJhbGciOi...）",
            QLineEdit.Normal,
            ""
        )
        if not ok or not token.strip():
            return
        token_str = token.strip()
        # 預設為 security_shield，若 token 內有指定其它 dlc_id 會自動解析
        ok_v, payload, msg = verify_license_token(token_str)
        if not ok_v:
            QMessageBox.warning(self, "兌換失敗", f"❌ 授權碼無效或已過期：\n{msg}")
            return

        target_dlc = payload.get("dlc_id") or "syntra.dlc.security_shield"
        ok_save, p_save, m_save = save_dlc_license_token(target_dlc, token_str, self.settings_manager)
        if ok_save:
            QMessageBox.information(
                self,
                "兌換成功",
                f"🎉 授權驗證成功！\n\n"
                f"• 授權模組：{target_dlc}\n"
                f"• 授權方案：{payload.get('plan', 'pro').upper()}\n"
                f"• 授權對象：{payload.get('to', payload.get('issued_to', 'VIP User'))}\n"
                f"• 授權類型：{payload.get('type', 'Perpetual')}\n"
                f"• 模組授權已自動寫入本機安全設定。"
            )
            self.refresh_list()
            self.sig_dlc_changed.emit()
        else:
            QMessageBox.warning(self, "儲存失敗", f"❌ 無法儲存授權：\n{m_save}")

    def _on_toggle_addon(self, mod_id: str, enable: bool):
        res = addon_module_manager.set_module_enabled(mod_id, enable)
        if not res.get("ok"):
            QMessageBox.warning(self, "操作失敗", res.get("error", "未知錯誤"))
        self.refresh_list()
        self.sig_dlc_changed.emit()

    def _on_uninstall_addon(self, mod_id: str, name: str):
        ans = QMessageBox.question(
            self,
            "確認移除模組",
            f"確定要徹底移除擴充模組「{name}」({mod_id}) 嗎？\n移除後若要重新使用需重新匯入。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            return
        mod = addon_module_manager.get_module(mod_id)
        if mod and mod.get("dir"):
            try:
                mod_path = Path(mod["dir"])
                if mod_path.exists() and mod_path != addon_module_manager.base_dir:
                    shutil.rmtree(mod_path)
                    addon_module_manager.set_module_enabled(mod_id, False)
                    QMessageBox.information(self, "移除成功", f"模組「{name}」已成功自本機移除。")
            except Exception as e:
                QMessageBox.warning(self, "移除失敗", f"無法刪除模組目錄: {e}")
        self.refresh_list()
        self.sig_dlc_changed.emit()

    def _on_uninstall_shield(self):
        ans = QMessageBox.question(
            self,
            "確認移除資安盾",
            "移除後主程式將回退至純淨無防護模式，確定要刪除 official_security_shield 嗎？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            return
        shield_dir = Path(__file__).resolve().parent.parent / "dlc" / "official_security_shield"
        try:
            if shield_dir.exists():
                shutil.rmtree(shield_dir)
            QMessageBox.information(self, "已移除", "官方資安盾套件已從本機移除。")
        except Exception as e:
            QMessageBox.warning(self, "移除失敗", f"無法刪除資料夾: {e}")
        self.refresh_list()
        self.sig_dlc_changed.emit()

    def _on_import_zip(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選取 DLC 模組包或授權檔",
            "",
            "DLC 套件與授權 (*.zip *.json);;ZIP 壓縮檔 (*.zip);;JSON 授權檔 (*.json)"
        )
        if not path:
            return
        self._process_import_file(Path(path))

    def _on_scan_downloads(self):
        dl_dir = Path.home() / "Downloads"
        if not dl_dir.exists():
            QMessageBox.information(self, "掃描完成", "找不到使用者的「下載」資料夾。")
            return
        found = []
        for p in dl_dir.glob("*.zip"):
            if "dlc" in p.name.lower() or "syntra" in p.name.lower() or "addon" in p.name.lower():
                found.append(p)
        if not found:
            QMessageBox.information(self, "掃描結果", "在「下載」資料夾中未發現帶有 syntra/dlc/addon 關鍵字的套件檔案。")
            return
        # 讓使用者選一個
        items = [f.name for f in found]
        chosen, ok = QInputDialog.getItem(self, "發現可疑 DLC 安裝包", "在下載區找到以下套件，請選擇要匯入的檔案：", items, 0, False)
        if ok and chosen:
            for f in found:
                if f.name == chosen:
                    self._process_import_file(f)
                    break

    def _process_import_file(self, file_path: Path):
        """解壓並驗證外部 DLC"""
        if file_path.suffix.lower() == ".json":
            # 可能是授權檔
            try:
                import json
                content = file_path.read_text(encoding="utf-8")
                data = json.loads(content)
                token = data.get("token") or data.get("license_token") or content.strip()
                ok_v, payload, msg = verify_license_token(token)
                if ok_v:
                    target_dlc = payload.get("dlc_id") or "syntra.dlc.security_shield"
                    save_dlc_license_token(target_dlc, token, self.settings_manager)
                    QMessageBox.information(self, "授權匯入成功", f"🎉 已成功載入授權檔：{file_path.name}")
                    self.refresh_list()
                    self.sig_dlc_changed.emit()
                    return
            except Exception:
                pass
            QMessageBox.warning(self, "無效授權", "該 JSON 檔不包含合法的 Syntra 數位授權 Token。")
            return

        if file_path.suffix.lower() == ".zip":
            # 解壓到臨時目錄檢查
            import tempfile
            import zipfile
            with tempfile.TemporaryDirectory() as tmp_dir:
                try:
                    with zipfile.ZipFile(file_path, "r") as z:
                        z.extractall(tmp_dir)
                except Exception as e:
                    QMessageBox.warning(self, "解壓縮失敗", f"無法讀取 ZIP 套件: {e}")
                    return

                # 尋找 module.json
                tmp_path = Path(tmp_dir)
                mod_json = list(tmp_path.rglob("module.json"))
                if not mod_json:
                    QMessageBox.warning(self, "無效模組包", "ZIP 檔案內找不到 module.json 模組定義檔！")
                    return

                target_module_dir = mod_json[0].parent
                res = addon_module_manager.install_external_module_folder(str(target_module_dir))
                if res.get("ok"):
                    QMessageBox.information(self, "安裝成功", f"🎉 已成功匯入模組「{res.get('id')}」！")
                    self.refresh_list()
                    self.sig_dlc_changed.emit()
                else:
                    QMessageBox.warning(self, "安裝失敗", res.get("error", "未知錯誤"))
