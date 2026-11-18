import asyncio
import base64
import ctypes
import io
import math
import os
import random
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageGrab
import psutil
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController
import win32con
import win32gui
import win32process
import win32ui

from core.accessibility_engine import accessibility_engine, AccessibilityEngine


def _kill_tree(pid: int) -> None:
    """終止行程與它開出來的所有子行程（powershell 底下跑的 python / node 等）。"""
    import psutil
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = parent.children(recursive=True) + [parent]
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=3)


class DesktopController:
    """
    背景優先 + 前景擬人雙軌桌面操控引擎：
    1. 背景不搶焦點模式：透過 Win32 PrintWindow (PW_RENDERFULLCONTENT) 擷取背景視窗畫面、執行無視窗背景指令與檢查專案檔。
    2. 前景擬人操控模式：搭配 Set-of-Mark 視覺座標格線、三次貝茲曲線平滑滑鼠軌跡、剪貼簿安全備份還原。
    3. 嚴格受 ContextGuard (防搶遊戲/影片/寫功課畫面) 與 SecurityGuard (防主動下單/敏感視窗遮罩) 管控。
    """

    PW_RENDERFULLCONTENT = 0x00000002

    def __init__(self, context_guard, security_guard):
        self.context_guard = context_guard
        self.security_guard = security_guard
        self._running_procs = set()  # 正在執行的背景指令（緊急停止時一併終止）
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.accessibility: AccessibilityEngine = accessibility_engine

    def kill_running_commands(self) -> int:
        """緊急停止：終止所有正在執行的背景指令及其子行程，回傳終止數量。"""
        killed = 0
        for p in list(self._running_procs):
            try:
                p._syntra_killed = True
                _kill_tree(p.pid)
                killed += 1
            except Exception:
                pass
        return killed

    def list_open_windows(self) -> List[Dict[str, Any]]:
        """列出目前桌面上所有可見的應用程式視窗，第一項固定為『目前桌面全螢幕畫面』"""
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        windows: List[Dict[str, Any]] = [
            {
                "hwnd": 0,
                "pid": 0,
                "title": f"🖥️ 目前桌面全螢幕 (主螢幕 {screen_w}x{screen_h} 完整畫面)",
                "process_name": "DesktopScreen",
                "is_minimized": False,
                "rect": {"left": 0, "top": 0, "right": screen_w, "bottom": screen_h, "width": screen_w, "height": screen_h},
            }
        ]

        def _enum_cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            # 排除純背景系統無用視窗
            if not title or title in ("Program Manager", "Settings", "Microsoft Text Input Application"):
                return True
            try:
                rect = win32gui.GetWindowRect(hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                if w < 50 or h < 50:
                    return True
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc_name = ""
                if pid > 0:
                    try:
                        proc_name = psutil.Process(pid).name()
                    except Exception:
                        pass
                windows.append({
                    "hwnd": hwnd,
                    "pid": pid,
                    "title": title,
                    "process_name": proc_name,
                    "is_minimized": bool(win32gui.IsIconic(hwnd)),
                    "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3], "width": w, "height": h},
                })
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception:
            pass
        return windows

    def find_window(self, keyword: str) -> Optional[Dict[str, Any]]:
        kw = keyword.lower().strip()
        for w in self.list_open_windows():
            if kw in w["title"].lower() or kw in w["process_name"].lower():
                return w
        return None

    def capture_window_background(self, hwnd: int, draw_grid: bool = False) -> Tuple[Optional[Image.Image], Dict[str, Any]]:
        """
        擷取指定視窗或整個桌面螢幕：
        若 hwnd == 0，代表擷取『目前桌面全螢幕畫面』；
        若 hwnd > 0，則使用 Win32 PrintWindow (PW_RENDERFULLCONTENT) 在背景擷取指定視窗畫面，絕不搶焦點！
        """
        if hwnd == 0:
            img, meta = self.capture_desktop(draw_grid=draw_grid)
            return img, {
                "hwnd": 0,
                "title": "🖥️ 目前桌面全螢幕 (完整畫面)",
                "rect": (0, 0, meta["width"], meta["height"]),
                "redacted_windows": meta.get("redacted_windows", []),
                "mode": "desktop_fullscreen",
            }

        if not win32gui.IsWindow(hwnd):
            return None, {"error": f"無效的視窗控制代碼 (HWND={hwnd})"}

        hwnd_dc = None
        mfc_dc = None
        save_dc = None
        save_bitmap = None
        try:
            rect = self._get_visual_window_rect(hwnd)
            w = max(1, rect[2] - rect[0])
            h = max(1, rect[3] - rect[1])

            # 1. 優先使用與 Discord / OBS 同級的 Windows Graphics Capture (WGC)，不觸發重繪與游標閃爍
            img = None
            mode_tag = "background_wgc"
            if not win32gui.IsIconic(hwnd):
                try:
                    from core.wgc_capture import capture_window_wgc
                    img = capture_window_wgc(hwnd, include_cursor=False, timeout=1.2)
                    if img is not None and self._is_blank_or_black_image(img):
                        img = None
                except Exception:
                    img = None

            # 2. 若 WGC 不可用或視窗最小化，退回 PrintWindow + 空白偵測 + ImageGrab(all_screens=True)
            if img is None:
                mode_tag = "background_printwindow"
                hwnd_dc = win32gui.GetWindowDC(hwnd)
                mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                save_dc = mfc_dc.CreateCompatibleDC()
                save_bitmap = win32ui.CreateBitmap()
                save_bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
                save_dc.SelectObject(save_bitmap)

                res = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), self.PW_RENDERFULLCONTENT)
                bmpinfo = save_bitmap.GetInfo()
                bmpstr = save_bitmap.GetBitmapBits(True)
                img = Image.frombuffer("RGB", (bmpinfo["bmWidth"], bmpinfo["bmHeight"]), bmpstr, "raw", "BGRX", 0, 1)

                if (res == 0 or self._is_blank_or_black_image(img)) and not win32gui.IsIconic(hwnd):
                    img = ImageGrab.grab(bbox=rect, all_screens=True)

            masked_img, redacted = self.security_guard.redact_screenshot(img, monitor_offset=(rect[0], rect[1]))
            if draw_grid:
                masked_img = self._overlay_coordinate_grid(masked_img, offset=(rect[0], rect[1]))

            return masked_img, {
                "hwnd": hwnd,
                "title": win32gui.GetWindowText(hwnd),
                "rect": rect,
                "redacted_windows": redacted,
                "mode": "background_printwindow",
            }
        except Exception as e:
            return None, {"error": f"背景擷取視窗失敗：{e}"}
        finally:
            # 確保 GDI 物件與 DC 必定釋放，避免 Windows 核心控制代碼洩漏
            if save_bitmap:
                try: win32gui.DeleteObject(save_bitmap.GetHandle())
                except Exception: pass
            if save_dc:
                try: save_dc.DeleteDC()
                except Exception: pass
            if mfc_dc:
                try: mfc_dc.DeleteDC()
                except Exception: pass
            if hwnd_dc:
                try: win32gui.ReleaseDC(hwnd, hwnd_dc)
                except Exception: pass

    @staticmethod
    def _get_visual_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
        """取得排除 DWM 隱形陰影邊框後的真實視覺視窗矩形，避免最大化 (-8,-8) 偏移。"""
        try:
            dwm_rect = (ctypes.c_long * 4)()
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                int(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(dwm_rect), ctypes.sizeof(dwm_rect)
            )
            if hr == 0 and dwm_rect[2] > dwm_rect[0] and dwm_rect[3] > dwm_rect[1]:
                return (int(dwm_rect[0]), int(dwm_rect[1]), int(dwm_rect[2]), int(dwm_rect[3]))
        except Exception:
            pass
        return win32gui.GetWindowRect(hwnd)

    @staticmethod
    def _is_blank_or_black_image(img: Image.Image) -> bool:
        """判斷截圖是否全黑或僅外框有像素、中心內容區完全空白（DirectX / Electron PrintWindow 常見失效）。"""
        try:
            gray = img.convert("L")
            extrema = gray.getextrema()
            if extrema == (0, 0) or extrema[0] == extrema[1]:
                return True
            w, h = gray.size
            if w > 40 and h > 40:
                center = gray.crop((w // 6, h // 6, (w * 5) // 6, (h * 5) // 6))
                ce = center.getextrema()
                if ce == (0, 0) or ce[0] == ce[1]:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _virtual_screen_origin() -> Tuple[int, int]:
        try:
            vx = int(ctypes.windll.user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
            vy = int(ctypes.windll.user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
            return (vx, vy)
        except Exception:
            return (0, 0)

    def capture_desktop(self, draw_grid: bool = True) -> Tuple[Image.Image, Dict[str, Any]]:
        """擷取完整桌面畫面（單螢幕優先 WGC 零閃爍，多螢幕退回 ImageGrab all_screens），自動處理鎖定例外"""
        vx, vy = (0, 0)
        try:
            mon_cnt = int(ctypes.windll.user32.GetSystemMetrics(80) or 1)  # SM_CMONITORS
            img = None
            if mon_cnt <= 1:
                try:
                    from core.wgc_capture import capture_monitor_wgc
                    img = capture_monitor_wgc(monitor_index=1, include_cursor=False, timeout=1.2)
                except Exception:
                    img = None
            if img is None:
                img = ImageGrab.grab(all_screens=True)
                vx, vy = self._virtual_screen_origin()
        except Exception:
            # 備援：若 ImageGrab.grab() 失敗 (如沙盒或鎖定螢幕)，以 Win32 GDI 或建立空白畫面
            try:
                screen_w = ctypes.windll.user32.GetSystemMetrics(0) or 1920
                screen_h = ctypes.windll.user32.GetSystemMetrics(1) or 1080
                img = Image.new("RGB", (screen_w, screen_h), (18, 20, 28))
                draw = ImageDraw.Draw(img)
                draw.text((screen_w // 2 - 120, screen_h // 2), "[螢幕畫面暫時受保護或鎖定中]", fill=(148, 163, 184))
            except Exception:
                img = Image.new("RGB", (1280, 720), (18, 20, 28))

        try:
            masked_img, redacted = self.security_guard.redact_screenshot(img, monitor_offset=(vx, vy))
            if draw_grid:
                masked_img = self._overlay_coordinate_grid(masked_img, offset=(vx, vy))
            return masked_img, {
                "width": masked_img.width,
                "height": masked_img.height,
                "origin": (vx, vy),
                "redacted_windows": redacted,
            }
        except Exception:
            return img, {
                "width": img.width,
                "height": img.height,
                "redacted_windows": [],
            }

    def _overlay_coordinate_grid(self, img: Image.Image, offset: Tuple[int, int] = (0, 0)) -> Image.Image:
        """繪製清晰 100px 參考座標網格與高對比標籤，確保縮圖後 VLM 仍能精準讀取絕對螢幕座標。"""
        out = img.copy()
        draw = ImageDraw.Draw(out)
        w, h = out.size
        ox, oy = offset
        try:
            font = ImageFont.truetype("arial.ttf", max(14, min(20, w // 90)))
        except Exception:
            font = ImageFont.load_default()
        step = 100
        for x in range(step, w, step):
            is_major = (x % 200 == 0)
            draw.line([(x, 0), (x, h)], fill=(56, 189, 248) if is_major else (30, 64, 100), width=2 if is_major else 1)
            if is_major:
                label = f"X:{x + ox}"
                draw.rectangle([x + 2, 4, x + 76, 26], fill=(15, 23, 42))
                draw.text((x + 6, 6), label, fill=(125, 211, 252), font=font)
        for y in range(step, h, step):
            is_major = (y % 200 == 0)
            draw.line([(0, y), (w, y)], fill=(56, 189, 248) if is_major else (30, 64, 100), width=2 if is_major else 1)
            if is_major:
                label = f"Y:{y + oy}"
                draw.rectangle([4, y + 2, 78, y + 24], fill=(15, 23, 42))
                draw.text((8, y + 4), label, fill=(125, 211, 252), font=font)
        return out

    @staticmethod
    def image_to_base64(img: Image.Image, max_width: int = 1440, quality: int = 82) -> str:
        w, h = img.size
        if w > max_width:
            ratio = max_width / float(w)
            img = img.resize((max_width, int(h * ratio)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    async def wait_for_safe_foreground_slot(self, max_wait_seconds: float = 15.0) -> Tuple[bool, str]:
        """
        等待可以安全使用前景滑鼠/鍵盤的時機：
        - 若在打遊戲或看影片：立即回傳 False（絕不搶畫面，改由背景或 Discord 通知）
        - 若正在寫功課 / 移動滑鼠：最多等待 max_wait_seconds 直到使用者停手閒置
        """
        deadline = time.time() + max_wait_seconds
        while time.time() < deadline:
            if self.security_guard.emergency_stop_triggered:
                return False, "緊急停止開關 (Kill Switch) 已啟動，已中止所有桌面操作。"
            can_use, reason, state = self.context_guard.can_take_foreground_control()
            if can_use:
                return True, "OK"
            if state["mode"] in ("GAMING", "VIDEO", "MANUAL_DND"):
                return False, reason
            await asyncio.sleep(0.8)

        _, reason, _ = self.context_guard.can_take_foreground_control()
        return False, reason

    def move_mouse_humanlike(self, target_x: int, target_y: int, duration: float = 0.35):
        """使用三次貝茲曲線平滑移動滑鼠，模擬真實人類手部軌跡"""
        start_x, start_y = self.mouse.position
        dist = math.hypot(target_x - start_x, target_y - start_y)
        steps = max(12, min(45, int(dist / 18)))

        # 控制點加入微幅自然弧度
        ctrl1_x = start_x + (target_x - start_x) * 0.3 + random.uniform(-25, 25)
        ctrl1_y = start_y + (target_y - start_y) * 0.3 + random.uniform(-25, 25)
        ctrl2_x = start_x + (target_x - start_x) * 0.7 + random.uniform(-15, 15)
        ctrl2_y = start_y + (target_y - start_y) * 0.7 + random.uniform(-15, 15)

        sleep_per_step = max(0.004, duration / steps)
        for i in range(1, steps + 1):
            if self.security_guard.emergency_stop_triggered:
                break
            t = i / float(steps)
            # Ease-in-out
            t_smooth = t * t * (3.0 - 2.0 * t)
            u = 1.0 - t_smooth
            bx = (
                (u ** 3) * start_x
                + 3 * (u ** 2) * t_smooth * ctrl1_x
                + 3 * u * (t_smooth ** 2) * ctrl2_x
                + (t_smooth ** 3) * target_x
            )
            by = (
                (u ** 3) * start_y
                + 3 * (u ** 2) * t_smooth * ctrl1_y
                + 3 * u * (t_smooth ** 2) * ctrl2_y
                + (t_smooth ** 3) * target_y
            )
            self.mouse.position = (int(bx), int(by))
            time.sleep(sleep_per_step)

    async def click_at(
        self,
        x: int,
        y: int,
        button: str = "left",
        double: bool = False,
        target_label: str = "",
    ) -> Dict[str, Any]:
        """受資安閘門與免打擾保護的擬人滑鼠點擊"""
        risk, risk_reason = self.security_guard.classify_action(
            "gui_click", target_label, {"x": x, "y": y}
        )
        if risk != "SAFE":
            snap, _ = self.capture_desktop(draw_grid=False)
            b64 = self.image_to_base64(snap)
            approved, msg = await self.security_guard.request_user_approval(
                risk_level=risk,
                title=f"點擊畫面元件：{target_label or f'({x}, {y})'}",
                reason=risk_reason,
                action_payload={"action": "click_at", "x": x, "y": y, "target_label": target_label},
                screenshot_b64=b64,
            )
            if not approved:
                return {"ok": False, "blocked_by_security": True, "message": msg}

        ok_slot, slot_reason = await self.wait_for_safe_foreground_slot()
        if not ok_slot:
            return {"ok": False, "deferred_by_dnd": True, "message": slot_reason}

        self.move_mouse_humanlike(x, y)
        btn = Button.right if button == "right" else Button.left
        self.mouse.click(btn, 2 if double else 1)
        return {"ok": True, "x": x, "y": y, "target_label": target_label}

    def hard_block_reason(self) -> str:
        """緊急停止、遊戲、影片、手動免打擾 → 回傳原因；只是「使用者剛動過滑鼠鍵盤」不算（回傳空字串）。"""
        if self.security_guard.emergency_stop_triggered:
            return "緊急停止開關 (Kill Switch) 已啟動，已中止所有桌面操作。"
        try:
            _, reason, state = self.context_guard.can_take_foreground_control()
        except Exception:
            return ""
        return reason if state.get("mode") in ("GAMING", "VIDEO", "MANUAL_DND") else ""

    async def type_text_safe(
        self,
        text: str,
        press_enter: bool = False,
        target_label: str = "",
        skip_idle_wait: bool = False,
        pre_paste=None,
    ) -> Dict[str, Any]:
        """受資安閘門與免打擾保護的文字輸入（支援中文剪貼簿無損貼上並自動還原使用者剪貼簿）"""
        risk, risk_reason = self.security_guard.classify_action(
            "gui_type", target_label, {"text": text}
        )
        if risk != "SAFE":
            snap, _ = self.capture_desktop(draw_grid=False)
            b64 = self.image_to_base64(snap)
            approved, msg = await self.security_guard.request_user_approval(
                risk_level=risk,
                title=f"於 {target_label or '視窗'} 輸入敏感文字",
                reason=risk_reason,
                action_payload={"action": "type_text", "text": text[:120], "target_label": target_label},
                screenshot_b64=b64,
            )
            if not approved:
                return {"ok": False, "blocked_by_security": True, "message": msg}

        if skip_idle_wait:
            # 呼叫端已經確認過使用者沒在操作，而且剛剛的按鍵是代理自己按的（會重設閒置秒數）：
            # 這裡只擋遊戲／影片／免打擾／緊急停止，不再空等，避免等待期間前景被換掉
            reason = self.hard_block_reason()
            if reason:
                return {"ok": False, "deferred_by_dnd": True, "message": reason}
        else:
            ok_slot, slot_reason = await self.wait_for_safe_foreground_slot()
            if not ok_slot:
                return {"ok": False, "deferred_by_dnd": True, "message": slot_reason}

        # 貼上前最後一刻的檢查（例如：前景是不是還是目標視窗）；回傳 False 就不貼
        if pre_paste is not None and not await asyncio.to_thread(pre_paste):
            return {"ok": False, "wrong_foreground": True,
                    "message": "要輸入的那一刻，前景視窗已經不是目標視窗，為避免打錯地方沒有輸入。"}

        self._paste_text_preserving_clipboard(text)
        if press_enter:
            time.sleep(0.12)
            self.keyboard.press(Key.enter)
            self.keyboard.release(Key.enter)
        return {"ok": True, "length": len(text), "press_enter": press_enter}

    def _paste_text_preserving_clipboard(self, text: str):
        """使用 Win32 剪貼簿快速貼上支援中英文長文，並在貼上後還原使用者原本的剪貼簿內容（含自動重試）"""
        import win32clipboard

        old_clip = None
        opened = False
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                opened = True
                break
            except Exception:
                time.sleep(0.02)

        if opened:
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    old_clip = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            except Exception:
                pass
            finally:
                try: win32clipboard.CloseClipboard()
                except Exception: pass

        time.sleep(0.05)
        with self.keyboard.pressed(Key.ctrl):
            self.keyboard.press("v")
            self.keyboard.release("v")
        time.sleep(0.12)

        if old_clip is not None:
            restored_opened = False
            for _ in range(5):
                try:
                    win32clipboard.OpenClipboard()
                    restored_opened = True
                    break
                except Exception:
                    time.sleep(0.02)
            if restored_opened:
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, old_clip)
                except Exception:
                    pass
                finally:
                    try: win32clipboard.CloseClipboard()
                    except Exception: pass

    async def send_feedback_to_ide_window(
        self,
        hwnd: int,
        feedback_text: str,
        input_coords: Optional[Tuple[int, int]] = None,
        press_enter: bool = True,
    ) -> Dict[str, Any]:
        """
        將檢查結果與修復指令送回被監督的 AI 寫程式視窗（如 Antigravity / Cursor / VS Code）：
        1. 先確認使用者沒有在打遊戲、看影片或正在打字（ContextGuard）
        2. 記住使用者原本的前景視窗，短暫將目標 IDE 視窗喚醒或點擊對話框座標、貼上修正指令並送出，再視需要還原焦點
        """
        ok_slot, slot_reason = await self.wait_for_safe_foreground_slot(max_wait_seconds=12.0)
        if not ok_slot:
            return {
                "ok": False,
                "deferred_by_dnd": True,
                "message": f"目前處於免打擾或忙碌狀態，暫緩自動貼回 IDE：{slot_reason}",
            }

        try:
            prev_hwnd = win32gui.GetForegroundWindow()
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.2)

            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            time.sleep(0.2)

            if input_coords:
                self.move_mouse_humanlike(input_coords[0], input_coords[1], duration=0.25)
                self.mouse.click(Button.left, 1)
                time.sleep(0.15)

            self._paste_text_preserving_clipboard(feedback_text)
            if press_enter:
                time.sleep(0.15)
                self.keyboard.press(Key.enter)
                self.keyboard.release(Key.enter)

            # 若使用者原本在其他視窗且非目標視窗，貼完後溫和切回原視窗
            if prev_hwnd and prev_hwnd != hwnd and win32gui.IsWindow(prev_hwnd):
                time.sleep(0.2)
                try:
                    win32gui.SetForegroundWindow(prev_hwnd)
                except Exception:
                    pass

            return {"ok": True, "hwnd": hwnd, "sent_chars": len(feedback_text)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def run_background_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: float = 60.0,
        shell: str = "powershell",
    ) -> Dict[str, Any]:
        """
        在背景靜默執行測試、Linter、Git 檢查或腳本（CREATE_NO_WINDOW 不彈出黑窗，絕不干擾打遊戲或看影片）
        shell="linux" 時改用 bash（Git Bash 或 WSL）執行 Linux 指令，風險審核與緊急停止機制相同。
        """
        is_linux = str(shell).lower() in ("linux", "bash")
        if is_linux:
            from core.linux_shell import build_argv
            try:
                argv = build_argv(command, cwd)
            except RuntimeError as e:
                return {"ok": False, "exit_code": -1, "output": f"❌ {e}"}
        else:
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"]
        risk, risk_reason = self.security_guard.classify_action(
            "run_command", command, {"command": command, "cwd": cwd or ""}
        )
        if risk == "CREDENTIAL_THEFT_BLOCKED":
            return {
                "ok": False,
                "blocked_by_security": True,
                "output": f"❌ [資安最高防護阻斷] {risk_reason}。系統嚴禁執行任何讀取、輸出或竊取 API Key / 機密檔案之指令！",
                "exit_code": -1,
            }

        if risk != "SAFE":
            approved, msg = await self.security_guard.request_user_approval(
                risk_level=risk,
                title=f"執行{'Linux ' if is_linux else '背景系統'}指令：{command[:60]}",
                reason=risk_reason,
                action_payload={"action": "run_background_command", "command": command, "cwd": cwd},
            )
            if not approved:
                return {"ok": False, "blocked_by_security": True, "output": msg, "exit_code": -1}

        def _exec():
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            clean_env = dict(os.environ)
            for var in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "NVIDIA_API_KEY", "DISCORD_BOT_TOKEN", "GITHUB_TOKEN"]:
                clean_env.pop(var, None)
            for k in list(clean_env.keys()):
                if any(term in k.upper() for term in ("API_KEY", "SECRET", "PRIVATE_KEY", "AUTH_TOKEN")):
                    clean_env.pop(k, None)
            if is_linux:
                # 留在指定的工作目錄（不要跳回家目錄），輸出用 UTF-8
                clean_env.update({"CHERE_INVOKING": "1", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})

            # 用 Popen 並登記在 _running_procs，緊急停止時才能真的把正在跑的指令（含子行程）砍掉
            popen = subprocess.Popen(
                argv,
                cwd=cwd or None,
                env=clean_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self._running_procs.add(popen)
            try:
                stdout, stderr = popen.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(popen.pid)
                popen.communicate()
                raise
            finally:
                self._running_procs.discard(popen)
            if getattr(popen, "_syntra_killed", False):
                return {"ok": False, "exit_code": -9, "output": "🛑 指令已被緊急停止中斷。"}
            proc = subprocess.CompletedProcess(popen.args, popen.returncode, stdout, stderr)
            out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            sanitized_out = self.security_guard.sanitize_secrets(out.strip()[:8000])
            return {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "output": sanitized_out,
            }

        try:
            return await asyncio.to_thread(_exec)
        except subprocess.TimeoutExpired:
            return {"ok": False, "exit_code": -2, "output": f"指令執行逾時 (>{timeout}s)：{command}"}
        except Exception as e:
            return {"ok": False, "exit_code": -1, "output": f"指令執行例外：{e}"}

    # ================= 作業系統無障礙功能 (UI Automation) 替代截圖 =================

    async def get_window_accessibility_tree(self, hwnd: int = 0, max_depth: int = 5, max_nodes: int = 80) -> Tuple[str, Dict[str, Any]]:
        """
        利用作業系統無障礙 (Accessibility UIA) 代替傳統畫面截圖：
        1. 0 像素縮放與模糊失真，100% 原始取得所有控制項文字與標題
        2. 自動標註元素 ID (如 #1, #2)，可直接透過 ui_invoke 或 ui_type 精準操作
        3. 大幅節省 Token 消耗與網路傳輸時間
        """
        return await asyncio.to_thread(self.accessibility.dump_window_tree, hwnd, max_depth, max_nodes)

    async def ui_invoke(self, element_id: str) -> Dict[str, Any]:
        """透過原生無障礙 Invoke/Toggle/Select 觸發控制項"""
        return await asyncio.to_thread(self.accessibility.invoke_element_by_id, element_id)

    async def ui_type(self, element_id: str, text: str) -> Dict[str, Any]:
        """透過原生無障礙 ValuePattern 直接寫入文字（極速無損）"""
        return await asyncio.to_thread(self.accessibility.set_element_value_by_id, element_id, text)

    async def ui_read_full_text(self, element_id: str) -> Dict[str, Any]:
        """無障礙深度提取長文件純文字"""
        return await asyncio.to_thread(self.accessibility.read_element_full_text, element_id)

    async def ui_click_element(self, element_id: str, button: str = "left", double: bool = False) -> Dict[str, Any]:
        """定位無障礙元素之精確物理幾何中心並執行擬人滑鼠點擊"""
        node = self.accessibility._find_node_by_id_or_name(element_id)
        if not node:
            return {"ok": False, "error": f"找不到無障礙元素：[{element_id}]"}
        cx, cy = node.center_point
        return await self.click_at(cx, cy, button=button, double=double, target_label=node.name or node.control_type)

    # ================= 多重 AI 編碼工具提示詞派送 (AI Coding Tool Dispatch) =================
    # 讓本機已安裝、使用者本人已登入/開啟的 AI 編碼工具（Antigravity、VS Code 內建 AI、
    # Codex CLI、Claude Code）可以直接被自動餵入提示詞，取代人工切視窗、手動貼上的重複勞動。
    # 僅操作「使用者本人電腦上已存在的視窗」，不涉及任何帳號登入、憑證輸入或對外連線。
    AI_CODING_TOOL_HINTS: Dict[str, List[str]] = {
        "antigravity": ["antigravity"],
        "vscode": ["visual studio code", "code.exe"],
        "codex": ["codex"],
        "claude_code": ["claude code", "claude.exe"],
        "cursor": ["cursor"],
    }

    def find_ai_coding_tool_window(self, tool_hint: str) -> Optional[Dict[str, Any]]:
        """依工具別名（antigravity / vscode / codex / claude_code / cursor，或自訂關鍵字）找出已開啟的視窗"""
        hint_key = (tool_hint or "").strip().lower()
        keywords = self.AI_CODING_TOOL_HINTS.get(hint_key, [hint_key] if hint_key else [])
        if not keywords:
            return None
        for w in self.list_open_windows():
            title_lower = w["title"].lower()
            proc_lower = (w.get("process_name") or "").lower()
            if any(kw in title_lower or kw in proc_lower for kw in keywords):
                return w
        return None

    async def dispatch_prompt_to_ai_tool(
        self,
        tool_hint: str,
        prompt_text: str,
        press_enter: bool = True,
        read_back_response: bool = False,
        response_wait_seconds: float = 2.5,
    ) -> Dict[str, Any]:
        """
        自動找到指定的 AI 編碼工具視窗並把提示詞貼入其對話輸入框送出；
        可選擇等待片刻後讀回其無障礙結構樹文字作為回覆快照。
        完全複用既有的 send_feedback_to_ide_window（含 ContextGuard 忙碌/免打擾偵測與焦點還原邏輯）。
        """
        target = self.find_ai_coding_tool_window(tool_hint)
        if not target:
            return {"ok": False, "error": f"找不到符合「{tool_hint}」的已開啟視窗，請確認該 AI 編碼工具已在本機開啟。"}

        send_res = await self.send_feedback_to_ide_window(
            hwnd=target["hwnd"],
            feedback_text=prompt_text,
            press_enter=press_enter,
        )
        result: Dict[str, Any] = {
            "ok": send_res.get("ok", False),
            "matched_window": {"hwnd": target["hwnd"], "title": target["title"], "process_name": target.get("process_name")},
            "send_result": send_res,
        }
        if send_res.get("ok") and read_back_response:
            await asyncio.sleep(max(0.0, response_wait_seconds))
            tree_text, meta = await self.get_window_accessibility_tree(target["hwnd"], max_depth=6, max_nodes=120)
            result["response_snapshot"] = tree_text
            result["response_meta"] = meta
        return result

    # ================= 軟體清冊地圖與「開啟軟體需使用者同意」 (Software Inventory & Consent-Gated Launch) =================
    # list_installed_software 純讀取登錄檔，不執行、不開啟任何程式，不需要使用者同意。
    # launch_application 只負責「真的去開啟」這個機制本身；是否要先跳出核准卡片給使用者按同意，
    # 一律由呼叫端 agent_brain.execute_tool 透過 SecurityGuard.request_user_approval 決定，
    # 確保「開啟軟體」這件事永遠不會在使用者同意之前就先發生。

    def list_installed_software(self, max_items: int = 300, query: str = "") -> List[Dict[str, Any]]:
        """本機已安裝軟體的唯讀地圖：登錄檔 Uninstall 清單＋開始功能表 App（含 Microsoft Store 版）。
        query 可用名稱篩選（例如 "claude"），結果依相符程度排序。"""
        from core import app_launcher
        items = app_launcher.merged_inventory(self._registry_software())
        if query:
            items = app_launcher.filter_inventory(items, query)
        return items[:max_items]

    def _registry_software(self) -> List[Dict[str, Any]]:
        """掃描 Windows 登錄檔 Uninstall 清單（Store 版 App 不在這裡）。"""
        import winreg

        roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        seen = set()
        software: List[Dict[str, Any]] = []
        for hive, path in roots:
            try:
                with winreg.OpenKey(hive, path) as key:
                    sub_count = winreg.QueryInfoKey(key)[0]
            except Exception:
                continue
            for i in range(sub_count):
                try:
                    with winreg.OpenKey(hive, path) as key:
                        sub_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(hive, f"{path}\\{sub_name}") as sub:
                        def _get(name: str) -> str:
                            try:
                                val = winreg.QueryValueEx(sub, name)[0]
                                return str(val) if val is not None else ""
                            except Exception:
                                return ""

                        display_name = _get("DisplayName")
                        is_system_component = _get("SystemComponent") == "1"
                        if not display_name or is_system_component or display_name in seen:
                            continue
                        seen.add(display_name)
                        software.append({
                            "name": display_name,
                            "version": _get("DisplayVersion"),
                            "publisher": _get("Publisher"),
                            "install_location": _get("InstallLocation"),
                            "launch_target": _get("DisplayIcon") or _get("InstallLocation"),
                        })
                except Exception:
                    continue

        software.sort(key=lambda s: s["name"].lower())
        return software

    def launch_application(self, target: str) -> Dict[str, Any]:
        """
        真正開啟/啟動指定的應用程式（純執行機制）。接受完整 exe 路徑或系統認得的軟體名稱。
        【重要】這個方法本身不做任何使用者同意判斷；呼叫前必須已經透過
        SecurityGuard.request_user_approval 取得使用者明確核准。
        """
        # 依序找：檔案路徑 → 開始功能表／Store App（例如 Claude 桌面版）→ 已安裝程式 → 系統指令
        from core import app_launcher
        return app_launcher.launch(target, self._registry_software())
