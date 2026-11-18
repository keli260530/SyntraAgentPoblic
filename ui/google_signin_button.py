# -*- coding: utf-8 -*-
"""標準樣式的「使用 Google 帳戶登入」按鈕（依 Google 品牌規範：白底、灰框、四色 G 標誌）。"""
from __future__ import annotations

import os

from PyQt5.QtCore import QByteArray, QSize, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QPushButton

# Google 官方四色 "G" 標誌
_G_LOGO_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
</svg>"""


def google_logo_icon(px: int = 20) -> QIcon:
    try:
        from PyQt5.QtSvg import QSvgRenderer
    except Exception:
        return QIcon()
    icon = QIcon()
    renderer = QSvgRenderer(QByteArray(_G_LOGO_SVG))
    for scale in (1, 2):  # 高 DPI 螢幕也清晰
        pm = QPixmap(px * scale, px * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p)
        p.end()
        icon.addPixmap(pm)
    return icon


class GoogleSignInButton(QPushButton):
    """白底膠囊形按鈕；已登入時顯示「已連結 Google 帳戶」並改為次要樣式。"""

    _STYLE = """
        QPushButton {
            background-color: #FFFFFF;
            color: #1F1F1F;
            border: 1px solid #747775;
            border-radius: 20px;
            padding: 0 16px 0 12px;
            font-family: "Roboto", "Segoe UI", "Microsoft JhengHei UI", sans-serif;
            font-size: 14px;
            font-weight: 500;
            min-height: 40px;
            max-height: 40px;
            text-align: center;
        }
        QPushButton:hover { background-color: #F7F8F8; border-color: #5F6368; }
        QPushButton:pressed { background-color: #E8EAED; }
        QPushButton:focus { border: 2px solid #1A73E8; }
        QPushButton:disabled { background-color: #F1F3F4; color: #80868B; border-color: #DADCE0; }
    """

    def __init__(self, text: str = "使用 Google 帳戶登入", parent=None):
        super().__init__(text, parent)
        self.setIcon(google_logo_icon(20))
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self._STYLE)
        self.setFixedHeight(40)
        self.setMinimumWidth(220)

    def set_signed_in(self, signed_in: bool):
        self.setText("已連結 Google 帳戶（重新登入）" if signed_in else "使用 Google 帳戶登入")

    def set_waiting(self, waiting: bool):
        self.setEnabled(not waiting)
        if waiting:
            self.setText("請在瀏覽器完成登入…")


# ---------------------------------------------------------------- 登入流程
CONSOLE_URL = "https://console.cloud.google.com/apis/credentials"
LOGIN_TIMEOUT = 300  # 秒：使用者沒在瀏覽器完成就放棄，避免背景一直等

SETUP_GUIDE_HTML = """
<p><b>要跳出 Google 登入畫面，需要先有一組「OAuth 用戶端憑證」（credentials.json）。</b><br>
這是 Google 的規定：每個要讀取 Gmail / 雲端硬碟的程式都必須先向 Google 註冊。只需設定一次，免費。</p>
<ol>
<li>開啟 <a href="https://console.cloud.google.com/">Google Cloud Console</a>，建立一個新專案（名稱隨意，例如 Syntra）。</li>
<li>左側選單「API 和服務 → 程式庫」，啟用 <b>Gmail API、Google Drive API、Google Calendar API、Google Docs API、Google Sheets API</b>。</li>
<li>「OAuth 同意畫面」：使用者類型選 <b>外部</b>，應用程式名稱填 <b>Syntra</b>；在「目標對象 / 測試使用者」加入<b>你自己的 Gmail</b>。</li>
<li>「憑證 → 建立憑證 → OAuth 用戶端 ID」，應用程式類型選 <b>電腦版應用程式</b>，建立後按「下載 JSON」。</li>
<li>回到這裡按「匯入 credentials.json」選擇剛下載的檔案，就會自動跳出 Google 登入畫面。</li>
</ol>
<p style="color:#94a3b8">登入時若看到「Google 尚未驗證這個應用程式」，因為這是你自己建立的 App，點「繼續」即可。<br>
登入後的授權金鑰只存在本機 <code>data/google_token.json</code>，並以 Windows 加密保存，只有你的 Windows 帳號解得開。</p>
"""


def check_client_secrets(path: str) -> str:
    """回傳空字串代表格式正確，否則回傳中文錯誤說明。"""
    import json
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return f"無法讀取這個檔案：{e}"
    if "installed" in data:
        return ""
    if "web" in data:
        return ("這是「網頁應用程式」類型的憑證，桌面程式無法使用。\n"
                "請在 Google Cloud Console 重新建立 OAuth 用戶端 ID，類型選「電腦版應用程式」。")
    return "這不是 Google OAuth 用戶端憑證檔（找不到 installed 欄位）。"


def describe_import_error(e: BaseException) -> str:
    """把套件匯入錯誤連同根本原因（__cause__ 鏈）與目前的 Python 一起列出，方便判斷真正缺的是什麼。"""
    import sys
    lines = [str(e) or type(e).__name__]
    seen = {id(e)}
    cause = e.__cause__ or e.__context__
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        lines.append(f"  → 原因：{type(cause).__name__}: {cause}")
        cause = cause.__cause__ or cause.__context__
    lines.append(f"\nPython：{sys.executable}")
    lines.append(f"可嘗試修復：\"{sys.executable}\" -m pip install --upgrade requests google-auth google-auth-oauthlib")
    return "\n".join(lines)


def revoke_google_access(suite) -> "tuple[bool, str]":
    """通知 Google 撤銷授權並刪除本機 token。回傳 (成功與否, 中文訊息)。"""
    import json
    token = ""
    creds = getattr(suite, "creds", None)
    if creds is not None:
        token = getattr(creds, "refresh_token", None) or getattr(creds, "token", None) or ""
    if not token and os.path.exists(suite.token_path):
        try:
            from core.secure_store import read_text
            data = json.loads(read_text(suite.token_path, migrate=False) or "{}")
            token = data.get("refresh_token") or data.get("token") or ""
        except Exception:
            pass

    remote_note = ""
    if token:
        try:
            import requests
            resp = requests.post("https://oauth2.googleapis.com/revoke", data={"token": token},
                                 headers={"content-type": "application/x-www-form-urlencoded"}, timeout=15)
            # 400 代表 token 早已失效，視同已撤銷
            if resp.status_code not in (200, 400):
                remote_note = f"\n（Google 回應 HTTP {resp.status_code}，可到 https://myaccount.google.com/permissions 手動移除。）"
        except Exception as e:
            remote_note = f"\n（無法連線到 Google：{e}；可到 https://myaccount.google.com/permissions 手動移除。）"

    try:
        if os.path.exists(suite.token_path):
            os.remove(suite.token_path)
    except Exception as e:
        return False, f"無法刪除本機登入憑證 {suite.token_path}：{e}"
    suite.creds = None
    getattr(suite, "_services", {}).clear()
    if not token:
        return True, "目前沒有登入 Google，已清除本機狀態。"
    return True, "已登出 Google 並撤銷 Syntra 的存取權。" + remote_note


class GoogleLoginWorker(QThread):
    """在背景執行緒跑 OAuth：開啟系統瀏覽器的 Google 登入頁，本機接收回呼，不會讓視窗卡住。"""
    done = pyqtSignal(bool, str)

    def __init__(self, suite, scopes, parent=None):
        super().__init__(parent)
        self.suite = suite
        self.scopes = scopes

    def run(self):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(self.suite.creds_path, self.scopes)
            creds = flow.run_local_server(
                port=0, open_browser=True, timeout_seconds=LOGIN_TIMEOUT,
                authorization_prompt_message="",
                success_message="Syntra: Google sign-in completed. You can close this tab.",
            )
            if not creds or not creds.valid:
                self.done.emit(False, "沒有取得有效的授權（可能在瀏覽器按了取消或逾時）。")
                return
            from core.secure_store import write_text
            write_text(self.suite.token_path, creds.to_json())  # Windows DPAPI 加密保存
            self.suite.creds = creds
            self.suite._services.clear()
            self.done.emit(True, "")
        except Exception as e:
            msg = describe_import_error(e) if isinstance(e, ImportError) else (str(e) or type(e).__name__)
            if "timed out" in msg.lower() or "timeout" in msg.lower():
                msg = f"等待超過 {LOGIN_TIMEOUT // 60} 分鐘沒有完成瀏覽器登入，已取消。"
            elif "access_denied" in msg:
                msg = "你在 Google 頁面拒絕了授權；若出現「存取遭封鎖」，請確認已把自己的 Gmail 加入測試使用者。"
            self.done.emit(False, msg)


def prompt_cloud_profile_after_login(parent, suite, settings_manager=None) -> None:
    """
    登入 Google 成功後，自動檢查使用者雲端硬碟是否已有 `Syntra_User_Profile` 個人化資料備份，
    並彈出視窗詢問使用者是否要將雲端個人化資料連回本機（或將本機資料備份至雲端）。
    """
    from PyQt5.QtWidgets import QMessageBox
    from core.user_profile_manager import user_profile_manager

    info = user_profile_manager.get_personal_info()
    if not info.get("cloud_auto_prompt_on_login", True):
        return

    check_res = user_profile_manager.check_cloud_profile(suite)
    if check_res.get("found"):
        summary = check_res.get("summary") or {}
        exported_at = check_res.get("exported_at") or check_res.get("modified_time") or "未知時間"
        device_name = check_res.get("device_name") or "雲端裝置"
        nickname = summary.get("nickname") or "（未設定稱呼）"
        mem_cnt = summary.get("memory_count", 0)
        has_habits = "已包含" if summary.get("has_habits") else "無"
        sched_cnt = summary.get("schedules_count", 0)

        box = QMessageBox(parent)
        box.setWindowTitle("☁️ 偵測到雲端個人化資料 — 是否連回？")
        box.setIcon(QMessageBox.Question)
        box.setText(
            f"<b>在您的 Google 雲端硬碟找到先前的個人化資料備份！</b><br><br>"
            f"• <b>備份時間：</b>{exported_at}<br>"
            f"• <b>來源裝置：</b>{device_name}<br>"
            f"• <b>使用者稱呼：</b>{nickname}<br>"
            f"• <b>長期記憶：</b>{mem_cnt} 筆 ｜ <b>習慣畫像：</b>{has_habits} ｜ <b>排程：</b>{sched_cnt} 項<br><br>"
            f"請問是否要將雲端上的個人化資料連回本機獨立資料夾 (<code>user_profile/</code>)？"
        )
        btn_merge = box.addButton("📥 連回並與本機合併（推薦）", QMessageBox.AcceptRole)
        btn_overwrite = box.addButton("📥 連回並完整覆蓋本機", QMessageBox.ActionRole)
        btn_upload = box.addButton("☁️ 改以本機資料覆蓋雲端", QMessageBox.ActionRole)
        box.addButton("稍後再說", QMessageBox.RejectRole)
        box.exec_()

        clicked = box.clickedButton()
        if clicked in (btn_merge, btn_overwrite):
            merge_mode = clicked is btn_merge
            res = user_profile_manager.restore_from_cloud(
                suite, merge=merge_mode, settings_manager=settings_manager
            )
            if res.get("success"):
                r = res.get("restored", {})
                QMessageBox.information(
                    parent,
                    "個人化資料已連回",
                    f"✅ 已成功從雲端連回您的個人化資料！\n"
                    f"• 長期記憶：{r.get('memories', 0)} 筆\n"
                    f"• 習慣畫像：{'已同步' if r.get('habits') else '未變更'}\n"
                    f"• 排程設定：{r.get('schedules', 0)} 項\n"
                    f"存放位置：{user_profile_manager.profile_dir}",
                )
            else:
                QMessageBox.warning(parent, "連回未完成", str(res.get("error", "未知錯誤")))
        elif clicked is btn_upload:
            res = user_profile_manager.sync_to_cloud(suite, settings_manager=settings_manager)
            if res.get("success"):
                QMessageBox.information(
                    parent, "雲端備份完成", "☁️ 已將本機個人化資料（已剔除敏感金鑰）更新至您的 Google 雲端硬碟！"
                )
            else:
                QMessageBox.warning(parent, "雲端備份失敗", str(res.get("error", "未知錯誤")))
    else:
        box = QMessageBox(parent)
        box.setWindowTitle("☁️ 建立個人雲端資料備份")
        box.setIcon(QMessageBox.Information)
        box.setText(
            "<b>Google 帳號已連結！</b><br><br>"
            "目前您的 Google 雲端硬碟尚未建立個人化設定與記憶備份。<br>"
            "是否要將 <code>user_profile/</code> 內的個人化偏好、長期記憶與習慣畫像"
            "（不含任何 API Key 與密碼）備份至您的雲端硬碟？<br>"
            "未來換電腦或重新安裝時，登入即可詢問您並一鍵連回！"
        )
        btn_backup = box.addButton("☁️ 立即備份至我的雲端", QMessageBox.AcceptRole)
        box.addButton("暫不需要", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is btn_backup:
            res = user_profile_manager.sync_to_cloud(suite, settings_manager=settings_manager)
            if res.get("success"):
                QMessageBox.information(
                    parent,
                    "雲端備份成功",
                    "🎉 已在您的 Google 雲端硬碟建立「Syntra_User_Profile」專屬資料夾並完成備份！\n"
                    "下次登入時將自動詢問您連回。",
                )
            else:
                QMessageBox.warning(parent, "雲端備份未完成", str(res.get("error", "未知錯誤")))

