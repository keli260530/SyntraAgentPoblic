# -*- coding: utf-8 -*-
"""
系統層級全域熱鍵（Win32 RegisterHotKey）

不管目前在哪個視窗（遊戲、瀏覽器、IDE）都能觸發。熱鍵訊息只會送給註冊它的執行緒，
所以這裡開一條專用執行緒跑 GetMessage 迴圈；callback 會在該執行緒被呼叫，
UI 端請用 Qt signal 轉回主執行緒。

註冊失敗（例如別的程式已經佔用同一組熱鍵）時 start() 會回傳失敗清單，不會讓程式崩潰。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable, Dict, List, Tuple

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_KEYS = {"space": 0x20, "esc": 0x1B, "enter": 0x0D, "tab": 0x09}


def parse_hotkey(spec: str) -> Tuple[int, int]:
    """'ctrl+alt+q' → (modifiers, virtual-key)。"""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    mods, vk = 0, 0
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        elif p in _KEYS:
            vk = _KEYS[p]
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            vk = 0x6F + int(p[1:])  # F1 = 0x70
        else:
            raise ValueError(f"不支援的按鍵：{p}")
    if not vk:
        raise ValueError(f"熱鍵缺少主要按鍵：{spec}")
    return mods | MOD_NOREPEAT, vk


class GlobalHotkeys:
    def __init__(self):
        self._bindings: Dict[int, Tuple[str, Callable[[], None]]] = {}
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.failed: List[str] = []
        self.registered: List[str] = []

    def add(self, spec: str, callback: Callable[[], None]) -> None:
        self._bindings[len(self._bindings) + 1] = (spec, callback)

    def start(self) -> List[str]:
        """啟動監聽執行緒；回傳註冊失敗的熱鍵清單。"""
        if self._thread:
            return self.failed
        self._thread = threading.Thread(target=self._run, daemon=True, name="GlobalHotkeys")
        self._thread.start()
        self._ready.wait(timeout=3)
        return self.failed

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        for hid, (spec, _) in self._bindings.items():
            try:
                mods, vk = parse_hotkey(spec)
                if user32.RegisterHotKey(None, hid, mods, vk):
                    self.registered.append(spec)
                else:
                    self.failed.append(spec)
            except Exception:
                self.failed.append(spec)
        self._ready.set()

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    binding = self._bindings.get(int(msg.wParam))
                    if binding:
                        try:
                            binding[1]()
                        except Exception:
                            pass
        finally:
            for hid in self._bindings:
                user32.UnregisterHotKey(None, hid)
