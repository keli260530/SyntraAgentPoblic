"""
core/ghost_desktop_worker.py
============================
幽靈虛擬桌面執行器 (Ghost Desktop Worker)
利用 Windows 底層 CreateDesktopW / SetThreadDesktop 建立完全隔離的虛擬 Win32 桌面。
Agent 可在該獨立桌面中調度有 GUI 的軟體（如瀏覽器、轉檔軟體、IDE），
絕不搶奪主螢幕焦點、滑鼠游標或鍵盤輸入。
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes
from typing import Optional, List, Dict, Any
import win32api
import win32con
import win32process
import win32service
import win32gui
import win32event

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 定義 Windows 常數
DESKTOP_CREATEWINDOW = 0x0002
DESKTOP_ENUMERATE = 0x0040
DESKTOP_WRITEOBJECTS = 0x0080
DESKTOP_SWITCHDESKTOP = 0x0100
DESKTOP_CREATEMENU = 0x0004
DESKTOP_HOOKCONTROL = 0x0020
DESKTOP_READOBJECTS = 0x0001
DESKTOP_JOURNALRECORD = 0x0008
DESKTOP_JOURNALPLAYBACK = 0x0010

GENERIC_ALL = 0x10000000
DESKTOP_ALL_ACCESS = (
    DESKTOP_READOBJECTS | DESKTOP_CREATEWINDOW | DESKTOP_CREATEMENU |
    DESKTOP_HOOKCONTROL | DESKTOP_JOURNALRECORD | DESKTOP_JOURNALPLAYBACK |
    DESKTOP_ENUMERATE | DESKTOP_WRITEOBJECTS | DESKTOP_SWITCHDESKTOP |
    win32con.STANDARD_RIGHTS_REQUIRED
)

class GhostDesktopWorker:
    def __init__(self, desktop_name: str = "SyntraGhostDesktop"):
        self.desktop_name = desktop_name
        self.h_desk = None
        self._init_desktop()

    def _init_desktop(self):
        """建立或開啟獨立的 Win32 桌面控制代碼"""
        try:
            # 嘗試開啟現有桌面
            self.h_desk = win32service.OpenDesktop(
                self.desktop_name,
                0,
                False,
                DESKTOP_ALL_ACCESS
            )
        except Exception:
            # 建立全新桌面
            self.h_desk = win32service.CreateDesktop(
                self.desktop_name,
                0,
                DESKTOP_ALL_ACCESS,
                None
            )

    def run_process(
        self,
        command_line: str,
        working_dir: Optional[str] = None,
        wait_ms: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        在幽靈桌面上啟動任何 GUI/CLI 程式。
        主桌面的物理滑鼠和螢幕完全不受干擾。
        """
        if not self.h_desk:
            self._init_desktop()

        si = win32process.STARTUPINFO()
        si.dwFlags = win32process.STARTF_USESHOWWINDOW
        si.wShowWindow = win32con.SW_SHOW
        si.lpDesktop = self.desktop_name  # 指定 Win32 桌面目標

        creation_flags = win32process.CREATE_NEW_CONSOLE | win32process.NORMAL_PRIORITY_CLASS

        try:
            h_process, h_thread, pid, tid = win32process.CreateProcess(
                None,
                command_line,
                None,
                None,
                False,
                creation_flags,
                None,
                working_dir or os.getcwd(),
                si
            )

            result = {
                "success": True,
                "pid": pid,
                "tid": tid,
                "desktop": self.desktop_name,
                "command": command_line
            }

            if wait_ms is not None:
                wait_res = win32event.WaitForSingleObject(h_process, wait_ms)
                result["finished"] = (wait_res == win32event.WAIT_OBJECT_0)
                if result["finished"]:
                    result["exit_code"] = win32process.GetExitCodeProcess(h_process)

            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def enum_windows(self) -> List[int]:
        """枚舉該幽靈桌面中的所有頂層視窗 HWND"""
        hwnds = []

        def _enum_proc(hwnd, lparam):
            if win32gui.IsWindow(hwnd):
                hwnds.append(hwnd)
            return True

        # 將當前線程臨時切換到幽靈桌面以枚舉其視窗
        orig_desk = win32service.GetThreadDesktop(win32api.GetCurrentThreadId())
        try:
            self.h_desk.SetThreadDesktop()
            win32gui.EnumWindows(_enum_proc, 0)
        finally:
            orig_desk.SetThreadDesktop()

        return hwnds

    def get_windows_info(self) -> List[Dict[str, Any]]:
        """獲取幽靈桌面中所有可視或活動視窗的標題、類名與 PID"""
        hwnds = self.enum_windows()
        info_list = []
        for hwnd in hwnds:
            title = win32gui.GetWindowText(hwnd)
            cls_name = win32gui.GetClassName(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            is_visible = win32gui.IsWindowVisible(hwnd)
            if title or is_visible:
                info_list.append({
                    "hwnd": hwnd,
                    "title": title,
                    "class": cls_name,
                    "pid": pid,
                    "visible": bool(is_visible)
                })
        return info_list

    def terminate_process(self, pid: int) -> bool:
        """強制結束幽靈桌面中的特定進程"""
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
            win32api.TerminateProcess(handle, 0)
            win32api.CloseHandle(handle)
            return True
        except Exception:
            return False

    def close(self):
        """關閉幽靈桌面控制代碼"""
        if self.h_desk:
            try:
                self.h_desk.CloseDesktop()
            except Exception:
                pass
            self.h_desk = None


# 全域單例
ghost_worker = GhostDesktopWorker()
