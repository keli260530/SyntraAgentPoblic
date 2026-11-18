# -*- coding: utf-8 -*-
"""可安裝的模組目錄（catalog）。

欄位說明：
    id            模組代號（指令列用）
    name          中文名稱
    summary       一句話說明
    packages      pip 需求字串（可含 PEP 508 平台標記）
    depends       需要先安裝的其他模組 id
    paths         專案內必須存在的檔案／資料夾（不存在代表這份發行版沒有此模組）
    platforms     支援的 sys.platform 前綴；空 tuple 代表全平台
    required      必裝（核心）
    manual        需要手動步驟，安裝程式只顯示說明、不自動處理
    size_mb       預估下載／安裝空間（MB），供推薦邏輯判斷磁碟空間
    notes         安裝後要提醒使用者的事
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    summary: str
    packages: Tuple[str, ...] = ()
    depends: Tuple[str, ...] = ()
    paths: Tuple[str, ...] = ()
    platforms: Tuple[str, ...] = ()
    required: bool = False
    manual: bool = False
    size_mb: int = 0
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def supports(self, platform: str) -> bool:
        return not self.platforms or any(platform.startswith(p) for p in self.platforms)


WIN = ("win32",)

MODULES: Tuple[Module, ...] = (
    Module(
        id="core",
        name="核心引擎",
        summary="AI 代理大腦、模型路由、API 伺服器（server.py / 無介面模式）",
        packages=(
            "fastapi>=0.110.0",
            "uvicorn>=0.29.0",
            "websockets>=12.0",
            "httpx>=0.27.0",
            "pydantic>=2.6.0",
            "beautifulsoup4>=4.12.0",
            "pillow>=10.0.0",
            "numpy>=1.26.0",
            "psutil>=5.9.0",
            "pywin32>=306; sys_platform == 'win32'",
        ),
        paths=("core", "server.py", "syntra_headless.py"),
        required=True,
        size_mb=120,
    ),
    Module(
        id="desktop-ui",
        name="桌面介面",
        summary="PyQt5 桌面視窗、系統匣、快速輸入列、全域熱鍵",
        packages=("PyQt5>=5.15.0", "pynput>=1.7.6"),
        depends=("core",),
        paths=("desktop_app.py", "tray_launcher.py", "ui"),
        platforms=WIN,
        size_mb=200,
    ),
    Module(
        id="desktop-automation",
        name="桌面自動化",
        summary="UI Automation 元素樹操控、背景虛擬桌面、滑鼠鍵盤控制",
        packages=("uiautomation>=2.0.18", "pynput>=1.7.6"),
        depends=("core",),
        paths=("core/ui_automation_driver.py", "core/accessibility_engine.py"),
        platforms=WIN,
        size_mb=20,
    ),
    Module(
        id="security-suite",
        name="進階資安",
        summary="TOTP 雙重驗證、加密資料保管庫、CDR 內容無害化",
        packages=("cryptography>=42.0.0",),
        depends=("core",),
        paths=("core/totp_authenticator_guard.py", "core/cdr_engine.py"),
        size_mb=15,
    ),
    Module(
        id="remote-streaming",
        name="遠端畫面串流",
        summary="遠端控制與螢幕串流（OpenCV 影像編碼）",
        packages=("opencv-python>=4.8.0",),
        depends=("desktop-ui",),
        paths=("core/screen_streamer.py", "core/remote_control.py"),
        platforms=WIN,
        size_mb=150,
    ),
    Module(
        id="google-workspace",
        name="Google Workspace 整合",
        summary="Gmail、Drive、Calendar、Docs、Sheets",
        packages=(
            "google-api-python-client>=2.100.0",
            "google-auth>=2.23.0",
            "google-auth-oauthlib>=1.1.0",
            "requests>=2.31.0",
        ),
        depends=("core",),
        paths=("core/google_workspace_suite.py", "skills/google-workspace"),
        size_mb=60,
        notes=("需要在設定面板登入 Google 帳號才會啟用。",),
    ),
    Module(
        id="mcp-skills",
        name="MCP 工具與技能",
        summary="MCP 伺服器連接與 skills/ 技能包（部分 MCP 伺服器需要 Node.js）",
        packages=("pyyaml>=6.0",),
        depends=("core",),
        paths=("core/mcp_client.py", "core/mcp_skill_manager.py", "skills"),
        size_mb=5,
    ),
    Module(
        id="guardian",
        name="Guardian 行為式防毒",
        summary="獨立的行為式惡意程式看門狗（可不裝核心單獨使用）",
        packages=(
            "watchdog>=3.0.0",
            "wmi>=1.5.1",
            "pywin32>=306",
            "cryptography>=42.0.0",
        ),
        paths=("guardian",),
        platforms=WIN,
        size_mb=20,
        notes=(
            "本安裝程式只安裝 Python 套件；要註冊為常駐服務，請以系統管理員身分執行 guardian\\setup.ps1。",
        ),
    ),
    Module(
        id="cli",
        name="命令列遙控工具",
        summary="從其他終端機或電腦遙控 Syntra（不需額外套件）",
        paths=("cli",),
        size_mb=1,
        notes=("用法：py cli\\syntra-windows.py ps（說明見檔案開頭）。",),
    ),
    Module(
        id="dev-tools",
        name="開發與測試工具",
        summary="pytest 測試框架（給開發者）",
        packages=("pytest>=8.0.0",),
        paths=("tests",),
        size_mb=15,
    ),
    Module(
        id="drivers",
        name="核心驅動原始碼（進階）",
        summary="Minifilter 防篡改驅動 C 原始碼，需 WDK 編譯與驅動簽章",
        paths=("drivers",),
        platforms=WIN,
        manual=True,
        notes=("需安裝 Windows Driver Kit (WDK) 並自行編譯、簽章；安裝程式不會自動載入驅動。",),
    ),
)


def catalog() -> Dict[str, Module]:
    return {m.id: m for m in MODULES}
