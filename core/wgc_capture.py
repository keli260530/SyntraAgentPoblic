# -*- coding: utf-8 -*-
"""
Windows Graphics Capture (WGC) 零閃爍擷取模組。

與 Discord / OBS 相同底層：直接從 Windows DWM GPU 合成器讀取畫面，
不強迫目標視窗重繪（無 WM_PRINT）、不鎖定 GDI DC、不觸發滑鼠游標閃爍，
且支援 DirectX / Electron / 自繪視窗而不會抓到黑畫面。
"""
from __future__ import annotations

import threading
from typing import Optional

from PIL import Image


def is_available() -> bool:
    try:
        import windows_capture  # noqa: F401
        return True
    except Exception:
        return False


def _grab_once(
    *,
    hwnd: Optional[int] = None,
    monitor_index: Optional[int] = None,
    include_cursor: bool = False,
    timeout: float = 1.5,
) -> Optional[Image.Image]:
    try:
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture
    except Exception:
        return None

    box: dict = {}
    done = threading.Event()
    try:
        cap = WindowsCapture(
            cursor_capture=include_cursor,
            draw_border=False,
            window_hwnd=int(hwnd) if hwnd else None,
            monitor_index=int(monitor_index) if monitor_index else None,
        )
    except Exception:
        return None

    @cap.event
    def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
        try:
            buf = frame.frame_buffer
            if buf is not None and buf.ndim == 3 and buf.shape[2] >= 3:
                # windows_capture 回傳 BGRA numpy array，轉為 RGB PIL Image
                rgb = buf[:, :, [2, 1, 0]]
                box["img"] = Image.fromarray(rgb, "RGB")
        except Exception:
            pass
        finally:
            try:
                control.stop()
            except Exception:
                pass
            done.set()

    @cap.event
    def on_closed():
        done.set()

    ctrl = None
    try:
        ctrl = cap.start_free_threaded()
        done.wait(timeout)
    except Exception:
        return None
    finally:
        if ctrl is not None:
            try:
                ctrl.stop()
            except Exception:
                pass

    return box.get("img")


def capture_window_wgc(hwnd: int, include_cursor: bool = False, timeout: float = 1.5) -> Optional[Image.Image]:
    """使用 Windows Graphics Capture 擷取指定視窗（不搶焦點、不閃爍、不黑屏）。"""
    if not hwnd or int(hwnd) <= 0:
        return None
    return _grab_once(hwnd=int(hwnd), include_cursor=include_cursor, timeout=timeout)


def capture_monitor_wgc(monitor_index: int = 1, include_cursor: bool = False, timeout: float = 1.5) -> Optional[Image.Image]:
    """使用 Windows Graphics Capture 擷取指定螢幕（預設主螢幕 monitor_index=1）。"""
    return _grab_once(monitor_index=monitor_index, include_cursor=include_cursor, timeout=timeout)
