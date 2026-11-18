import ctypes
from ctypes import wintypes
import os
from typing import Any, Dict, Optional, Tuple
import psutil
import win32gui
import win32process


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


class ContextGuard:
    """
    情境感知免打擾與防搶焦點引擎：
    自動偵測使用者是否正在「打遊戲」、「看影片」或「做功課/主動操作滑鼠鍵盤」。
    在這些情境下嚴格禁止搶奪畫面焦點或移動實體游標，並自動調降背景資源佔用。
    """

    GAME_KEYWORDS = {
        "valorant", "league of legends", "leagueclient", "genshin", "yuanshen",
        "starrail", "zenless", "cs2", "csgo", "dota2", "apex", "overwatch",
        "minecraft", "javaw", "eldenring", "monsterhunter", "cyberpunk",
        "palworld", "blackmyth", "wukong", "helldivers", "baldursgate",
        "fortnite", "pubg", "roblox", "steam_app", "unreal", "unity",
    }

    VIDEO_PLAYERS = {
        "potplayer", "potplayermini64", "vlc", "mpv", "mpc-hc", "mpc-be",
        "kmplayer", "wmplayer", "netflix", "disney+",
    }

    VIDEO_TITLE_KEYWORDS = {
        "youtube", "netflix", "bilibili", "巴哈姆特動畫瘋", "動畫瘋",
        "twitch", "disney+", "prime video", "iqiyi", "愛奇藝", "播放",
    }

    HOMEWORK_OR_WORK_KEYWORDS = {
        "word", "winword", "powerpnt", "excel", "onenote", "notion",
        "obsidian", "overleaf", "acrobat", "pdf", "visual studio",
        "devcpp", "codeblocks", "intellij", "pycharm", "eclipse",
    }

    def __init__(self, settings_manager):
        self.settings_manager = settings_manager
        self._current_proc = psutil.Process(os.getpid())
        self._is_throttled = False

    def get_idle_seconds(self) -> float:
        """取得使用者最後一次操作實體滑鼠或鍵盤至今的秒數（處理 32-bit unsigned TickCount 溢位）"""
        try:
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
                last_time = lii.dwTime & 0xFFFFFFFF
                millis = (tick - last_time) & 0xFFFFFFFF
                # 若在沙盒環境 dwTime 為 0，代表無權限讀取實體輸入，視為閒置
                if last_time == 0:
                    return 999.0
                return max(0.0, millis / 1000.0)
        except Exception:
            pass
        return 999.0

    def get_foreground_window_info(self) -> Dict[str, Any]:
        """取得目前前景視窗的 HWND、標題、執行檔名稱與是否全螢幕"""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return {"hwnd": 0, "title": "", "process_name": "", "is_fullscreen": False}

            title = win32gui.GetWindowText(hwnd) or ""
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = ""
            if pid > 0:
                try:
                    proc_name = psutil.Process(pid).name().lower()
                except Exception:
                    pass

            # 檢查是否全螢幕 (涵蓋整個主螢幕且非桌面 Shell)
            is_fullscreen = False
            try:
                cls_name = win32gui.GetClassName(hwnd)
                if cls_name not in ("Progman", "WorkerW", "Shell_TrayWnd"):
                    rect = win32gui.GetWindowRect(hwnd)
                    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
                    win_w = rect[2] - rect[0]
                    win_h = rect[3] - rect[1]
                    if win_w >= screen_w and win_h >= screen_h and rect[0] <= 0 and rect[1] <= 0:
                        is_fullscreen = True
            except Exception:
                pass

            return {
                "hwnd": hwnd,
                "pid": pid,
                "title": title,
                "process_name": proc_name,
                "is_fullscreen": is_fullscreen,
            }
        except Exception:
            return {"hwnd": 0, "title": "", "process_name": "", "is_fullscreen": False}

    def evaluate_state(self) -> Dict[str, Any]:
        """
        評估目前使用者的電腦狀態：
        回傳 mode: 'NORMAL' | 'GAMING' | 'VIDEO' | 'HOMEWORK_ACTIVE' | 'MANUAL_DND'
        """
        cfg = self.settings_manager.get_raw().get("dnd", {})
        idle_sec = self.get_idle_seconds()
        fg = self.get_foreground_window_info()
        title_lower = fg["title"].lower()
        proc_lower = fg["process_name"].replace(".exe", "").lower()

        if cfg.get("manual_dnd", False):
            self._apply_resource_throttle(True)
            return {
                "mode": "MANUAL_DND",
                "label": "🔕 手動免打擾模式",
                "can_use_foreground": False,
                "reason": "你已手動開啟免打擾模式：任務照常在背景實作與執行，不搶奪或佔用前端畫面",
                "idle_seconds": round(idle_sec, 1),
                "foreground": fg,
            }

        # 1. 偵測遊戲模式
        if cfg.get("auto_detect_game", True):
            is_game_proc = any(k in proc_lower or k in title_lower for k in self.GAME_KEYWORDS)
            is_fullscreen_non_browser = (
                fg["is_fullscreen"]
                and proc_lower not in ("chrome", "msedge", "firefox", "brave", "opera", "explorer", "python")
                and not any(v in proc_lower for v in self.VIDEO_PLAYERS)
            )
            if is_game_proc or is_fullscreen_non_browser:
                self._apply_resource_throttle(True)
                return {
                    "mode": "GAMING",
                    "label": f"🎮 遊戲免打擾 ({fg['process_name'] or fg['title'][:20]})",
                    "can_use_foreground": False,
                    "reason": f"偵測到正在執行遊戲或全螢幕程式 ({fg['title'][:30]})，已鎖定背景低耗能模式並改由 Discord 通知",
                    "idle_seconds": round(idle_sec, 1),
                    "foreground": fg,
                }

        # 2. 偵測看影片模式
        if cfg.get("auto_detect_video", True):
            is_video_player = any(v in proc_lower for v in self.VIDEO_PLAYERS)
            is_video_title = any(v in title_lower for v in self.VIDEO_TITLE_KEYWORDS)
            if is_video_player or (is_video_title and (fg["is_fullscreen"] or idle_sec < 120)):
                self._apply_resource_throttle(True)
                return {
                    "mode": "VIDEO",
                    "label": f"🎬 觀影免打擾 ({fg['title'][:22]})",
                    "can_use_foreground": False,
                    "reason": f"偵測到正在觀看影片 ({fg['title'][:30]})，禁止彈窗或搶奪畫面焦點",
                    "idle_seconds": round(idle_sec, 1),
                    "foreground": fg,
                }

        self._apply_resource_throttle(False)

        # 3. 偵測正在做功課 / 主動操作滑鼠鍵盤
        wait_threshold = float(cfg.get("user_idle_Wait_seconds", 4.0))
        if cfg.get("protect_homework_focus", True) and idle_sec < wait_threshold:
            return {
                "mode": "HOMEWORK_ACTIVE",
                "label": f"✍️ 使用者操作中 (閒置 {idle_sec:.1f}s)",
                "can_use_foreground": False,
                "reason": f"你正在操作滑鼠或鍵盤 ({fg['title'][:25]})，Agent 等待閒置滿 {wait_threshold:.0f} 秒後才會進行前景點擊",
                "idle_seconds": round(idle_sec, 1),
                "foreground": fg,
            }

        return {
            "mode": "NORMAL",
            "label": "🟢 待命 / 可執行前景與背景操作",
            "can_use_foreground": True,
            "reason": "桌面處於閒置且非遊戲/觀影狀態，可安全操作",
            "idle_seconds": round(idle_sec, 1),
            "foreground": fg,
        }

    def can_take_foreground_control(self) -> Tuple[bool, str, Dict[str, Any]]:
        state = self.evaluate_state()
        return state["can_use_foreground"], state["reason"], state

    def is_dnd_active(self) -> bool:
        """是否處於免打擾狀態（手動 DND / 遊戲 / 觀影）：任務照常於背景實作，但不可搶奪或佔用前端畫面。"""
        try:
            state = self.evaluate_state()
            return state.get("mode") in ("MANUAL_DND", "GAMING", "VIDEO")
        except Exception:
            return False

    def _apply_resource_throttle(self, enable: bool):
        """在打遊戲或看影片時自動降低本程序 CPU 優先權，避免搶佔遊戲幀率"""
        if enable == self._is_throttled:
            return
        try:
            if enable:
                self._current_proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                self._current_proc.nice(psutil.NORMAL_PRIORITY_CLASS)
            self._is_throttled = enable
        except Exception:
            pass
