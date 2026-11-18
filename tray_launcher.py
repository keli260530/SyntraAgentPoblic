import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser


HOST = "127.0.0.1"
PORT = 18765
APP_URL = f"http://{HOST}:{PORT}"


def is_server_running() -> bool:
    try:
        with urllib.request.urlopen(f"{APP_URL}/api/status", timeout=1.2) as resp:
            return resp.status == 200
    except Exception:
        return False


def open_gemini_app_window():
    """
    以獨立桌面應用程式視窗模式 (--app) 開啟自製 Gemini 問答介面，
    若找不到 Edge / Chrome 則退回系統預設瀏覽器。
    """
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for browser_exe in candidates:
        if os.path.exists(browser_exe):
            try:
                subprocess.Popen(
                    [
                        browser_exe,
                        f"--app={APP_URL}",
                        "--window-size=1360,860",
                    ],
                    creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0,
                )
                return
            except Exception:
                continue

    webbrowser.open(APP_URL)


def start_backend_thread():
    import uvicorn
    from server import app

    def _run():
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # 等待後端就緒
    for _ in range(30):
        if is_server_running():
            break
        time.sleep(0.25)


def run_tray_app(open_window_immediately: bool = False):
    """使用 PyQt5 系統列常駐 (System Tray)，打遊戲時 0 前景畫面佔用"""
    start_backend_thread()
    if open_window_immediately:
        open_gemini_app_window()

    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
        from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

        log_file = Path(__file__).resolve().parent / "data" / "launcher_debug.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] PyQt5 imported successfully\n")

        qt_app = QApplication.instance()
        if not qt_app:
            qt_app = QApplication(sys.argv)
        qt_app.setQuitOnLastWindowClosed(False)

        ico_path = Path(__file__).resolve().parent / "assets" / "syntra_icon.ico"
        if ico_path.exists():
            app_icon = QIcon(str(ico_path))
        else:
            # 備援動態畫圖
            pix = QPixmap(64, 64)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(99, 102, 241))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
            painter.setPen(QColor(255, 255, 255))
            font = QFont("Segoe UI", 28, QFont.Bold)
            painter.setFont(font)
            painter.drawText(pix.rect(), Qt.AlignCenter, "✦")
            painter.end()
            app_icon = QIcon(pix)

        qt_app.setWindowIcon(app_icon)
        tray = QSystemTrayIcon(app_icon, qt_app)
        tray.setToolTip("Gemini Desktop Agent (背景常駐中 · 點擊開啟介面)")

        menu = QMenu()
        act_open = QAction("✦ 開啟 Gemini 問答視窗", menu)
        act_open.triggered.connect(open_gemini_app_window)
        menu.addAction(act_open)

        def _trigger_kill():
            try:
                req = urllib.request.Request(
                    f"{APP_URL}/api/security/killswitch",
                    data=b'{"reset": false}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=2.0)
            except Exception:
                pass

        act_kill = QAction("🛑 緊急停止所有操作 (Ctrl+Alt+Q)", menu)
        act_kill.triggered.connect(_trigger_kill)
        menu.addAction(act_kill)

        menu.addSeparator()
        act_quit = QAction("✕ 結束 Agent 背景常駐", menu)
        act_quit.triggered.connect(qt_app.quit)
        menu.addAction(act_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: open_gemini_app_window()
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
            else None
        )
        tray.setVisible(True)
        tray.show()

        # 發送右下角氣泡通知提醒使用者已啟動
        tray.showMessage(
            "Gemini Desktop Agent",
            "Agent 已在系統列常駐待命！雙擊圖示或桌面捷徑隨時開啟介面。",
            app_icon,
            3000,
        )

        sys.exit(qt_app.exec_())
    except Exception:
        # 若無 GUI 環境，保持背景常駐
        while True:
            time.sleep(3600)


def main():
    base_dir = Path(__file__).resolve().parent
    os.chdir(base_dir)
    log_file = base_dir / "data" / "launcher_debug.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] main started with args: {sys.argv}\n")

        args = set(sys.argv[1:])
        open_ui = "--open-ui" in args or not ("--tray" in args)

        # 若背景已經有一個常駐實例在跑，只需直接喚醒 Gemini 視窗即可，不重複開 Server
        if is_server_running():
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] server already running, opening ui: {open_ui}\n")
            if open_ui:
                open_gemini_app_window()
            return

        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting run_tray_app (open_ui={open_ui})\n")
        run_tray_app(open_window_immediately=open_ui)
    except Exception as e:
        import traceback
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] CRASH: {e}\n{traceback.format_exc()}\n")


if __name__ == "__main__":
    main()
