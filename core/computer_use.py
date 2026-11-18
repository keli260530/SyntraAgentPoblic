# -*- coding: utf-8 -*-
"""
電腦操控補齊工具（像 Claude computer use 一樣模仿使用者操作滑鼠鍵盤）。

原本已有：capture_desktop_screen（截圖 + 視覺定位）、click_screen（點擊）、type_text（打字）。
這裡補上真人操作電腦還缺的動作：
- computer_key    ：按鍵 / 快捷鍵（enter、esc、tab、ctrl+l、alt+tab、win+r …）
- computer_scroll ：在某個位置滾動滑鼠滾輪
- computer_drag   ：按住拖曳（拖檔案、拉捲軸、選取文字）
- computer_wait   ：等畫面載入

座標一律使用截圖上的格線座標（實體像素）。所有動作都受緊急停止開關與免打擾（遊戲 / 影片）保護。
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import time
from typing import Any, Dict, List, Optional, Tuple

TOOL_SPECS: List[Dict[str, Any]] = [
    {"name": "computer_key",
     "description": "像使用者一樣按鍵盤按鍵或快捷鍵。例如 enter、esc、tab、backspace、ctrl+l、ctrl+c、alt+tab、win+r、win+d。"
                    "多個按鍵依序按可用空白分隔，例如 \"ctrl+a delete\"。",
     "parameters": {"type": "object", "properties": {
         "keys": {"type": "string", "description": "要按的鍵或組合鍵"},
         "repeat": {"type": "integer", "description": "重複次數，預設 1，最多 20"}},
         "required": ["keys"]}},
    {"name": "computer_scroll",
     "description": "把滑鼠移到 (x, y) 後滾動滾輪。座標用截圖格線上的數字。",
     "parameters": {"type": "object", "properties": {
         "x": {"type": "integer"}, "y": {"type": "integer"},
         "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
         "amount": {"type": "integer", "description": "滾動格數，預設 3，最多 15"}},
         "required": ["x", "y", "direction"]}},
    {"name": "computer_drag",
     "description": "從 (from_x, from_y) 按住滑鼠左鍵拖曳到 (to_x, to_y) 再放開。",
     "parameters": {"type": "object", "properties": {
         "from_x": {"type": "integer"}, "from_y": {"type": "integer"},
         "to_x": {"type": "integer"}, "to_y": {"type": "integer"}},
         "required": ["from_x", "from_y", "to_x", "to_y"]}},
    {"name": "computer_wait",
     "description": "等待幾秒讓程式或網頁載入完成（最多 10 秒），之後通常要再截圖確認。",
     "parameters": {"type": "object", "properties": {
         "seconds": {"type": "number", "description": "秒數，預設 1"}}}},
]
TOOL_NAMES = {t["name"] for t in TOOL_SPECS}
READ_ONLY = {"computer_wait"}

PROMPT_GUIDE = """### 模仿使用者操作電腦（computer use）
當使用者要你「操作電腦 / 操控 / 像人一樣用滑鼠鍵盤」時，先看下方「🧰 軟體操作知識庫」或呼叫 `app_howto`：
能用專用工具一步完成的（例如在 VS Code／記事本新增檔案並寫內容 → `write_text_file` 加 open_in）就直接做，不要截圖摸索。
真的需要操作畫面時，照這個循環做，一次只做一個動作：
1. 先看：有結構的視窗優先用 `list_windows` + `inspect_accessibility_tree`；看不懂或是自繪畫面時用 `capture_desktop_screen`（附座標格線）。
2. 再動：`ui_invoke` / `ui_type`（無障礙）或 `click_screen`、`type_text`、`computer_key`、`computer_scroll`、`computer_drag`。座標用截圖格線上的數字。
3. 確認：每個動作後重新截圖或讀結構樹，確認畫面真的變了再做下一步；沒反應就換方法，不要重複同一個動作超過 2 次。
4. 要開啟軟體時一律用 `launch_application`（系統會先請使用者核准），不要用 win+r、開始選單或 shell 繞過核准。
5. 如果使用者只說要「測試操控」、沒有指定目標：做一個無害示範——用 `launch_application` 開啟記事本（notepad），點進編輯區，輸入一行「Syntra 操控測試成功」，截圖確認，最後回報每一步做了什麼（不要存檔、不要關閉別的視窗）。
6. 絕不自己付款、下單、刪除檔案或送出表單；遇到這類按鈕先停下來問使用者。
"""

# ---------------------------------------------------------------- 按鍵解析
_ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "return": "enter", "escape": "esc", "del": "delete",
    "windows": "win", "super": "win", "cmd": "win", "meta": "win", "option": "alt",
    "pgup": "page_up", "pageup": "page_up", "pgdn": "page_down", "pagedown": "page_down",
    "ins": "insert", "spacebar": "space", "arrowup": "up", "arrowdown": "down",
    "arrowleft": "left", "arrowright": "right", "bksp": "backspace",
}
_SPECIAL = {
    "ctrl": "ctrl", "shift": "shift", "alt": "alt", "win": "cmd",
    "enter": "enter", "esc": "esc", "tab": "tab", "space": "space", "backspace": "backspace",
    "delete": "delete", "insert": "insert", "home": "home", "end": "end",
    "page_up": "page_up", "page_down": "page_down", "up": "up", "down": "down", "left": "left", "right": "right",
    "caps_lock": "caps_lock", "print_screen": "print_screen", "menu": "menu",
    **{f"f{i}": f"f{i}" for i in range(1, 25)},
}
_MODIFIERS = {"ctrl", "shift", "alt", "win"}
# 會讓 agent 失去控制或鎖住電腦的組合：不允許
_BLOCKED = {frozenset({"ctrl", "alt", "delete"}), frozenset({"win", "l"})}
# 會繞過「開啟軟體需使用者核准」的組合：請改用 launch_application
_LAUNCHERS = {frozenset({"win", "r"}), frozenset({"win"}), frozenset({"ctrl", "esc"}), frozenset({"win", "x"})}


def parse_keys(spec: str) -> List[List[str]]:
    """'ctrl+a delete' → [['ctrl','a'], ['delete']]；不認得的鍵丟 ValueError。"""
    chords = []
    for chord in (spec or "").strip().lower().split():
        parts = [p.strip() for p in chord.replace("-", "+").split("+") if p.strip()] if chord != "+" else ["+"]
        if not parts:
            continue
        keys = []
        for p in parts:
            p = _ALIASES.get(p, p)
            if p not in _SPECIAL and len(p) != 1:
                raise ValueError(f"不認得的按鍵：{p}")
            keys.append(p)
        if frozenset(keys) in _BLOCKED:
            raise ValueError(f"為了安全，不允許按 {chord}（會鎖定電腦或叫出安全畫面）")
        if frozenset(keys) in _LAUNCHERS:
            raise ValueError(f"不允許用 {chord} 開啟程式；要開軟體請呼叫 launch_application（會先請使用者核准）")
        chords.append(keys)
    if not chords:
        raise ValueError("沒有指定要按的鍵")
    return chords


def _to_pynput(name: str):
    from pynput.keyboard import Key, KeyCode
    if name in _SPECIAL:
        return getattr(Key, _SPECIAL[name])
    return KeyCode.from_char(name)


# ---------------------------------------------------------------- 中文輸入法
# 注音等中文輸入法在「中文模式」會把字母鍵吃掉變成注音，而且單按 Shift 會切換中英模式。
# 按鍵前先把前景視窗的輸入法切成英數模式，按完再還原，快捷鍵才會照字面送出。
_WM_IME_CONTROL = 0x283
_IMC_GETCONVERSIONMODE, _IMC_SETCONVERSIONMODE = 0x1, 0x2
_IME_CMODE_NATIVE = 0x1


def _ime_window() -> int:
    try:
        imm = ctypes.windll.imm32
        imm.ImmGetDefaultIMEWnd.restype = ctypes.c_void_p
        imm.ImmGetDefaultIMEWnd.argtypes = [ctypes.c_void_p]
        return imm.ImmGetDefaultIMEWnd(ctypes.windll.user32.GetForegroundWindow()) or 0
    except Exception:
        return 0


def _ime_send(hwnd: int, cmd: int, value: int = 0) -> int:
    u = ctypes.windll.user32
    u.SendMessageW.restype = ctypes.c_ssize_t
    u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    return int(u.SendMessageW(hwnd, _WM_IME_CONTROL, cmd, value))


def force_alphanumeric_ime() -> Optional[Tuple[int, int]]:
    """把前景視窗輸入法切到英數模式；回傳 (ime 視窗, 原本模式) 供還原，沒有輸入法時回傳 None。"""
    hwnd = _ime_window()
    if not hwnd:
        return None
    try:
        mode = _ime_send(hwnd, _IMC_GETCONVERSIONMODE)
        _ime_send(hwnd, _IMC_SETCONVERSIONMODE, mode & ~_IME_CMODE_NATIVE)
        return hwnd, mode
    except Exception:
        return None


def restore_ime(saved: Optional[Tuple[int, int]]):
    if saved:
        try:
            _ime_send(saved[0], _IMC_SETCONVERSIONMODE, saved[1])
        except Exception:
            pass


def press_chords(chords: List[List[str]], repeat: int = 1, stop=lambda: False) -> int:
    saved = force_alphanumeric_ime()
    try:
        return _press_chords(chords, repeat, stop)
    finally:
        time.sleep(0.05)
        restore_ime(saved)


def _press_chords(chords: List[List[str]], repeat: int = 1, stop=lambda: False) -> int:
    from pynput.keyboard import Controller
    kb = Controller()
    done = 0
    for _ in range(max(1, min(int(repeat or 1), 20))):
        for keys in chords:
            if stop():
                return done
            if "shift" in keys:  # Shift 可能把注音切回中文模式，每個組合鍵前都重設一次
                force_alphanumeric_ime()
            mods = [_to_pynput(k) for k in keys if k in _MODIFIERS]
            main = [_to_pynput(k) for k in keys if k not in _MODIFIERS] or []
            for m in mods:
                kb.press(m)
            try:
                if main:
                    for k in main:
                        kb.press(k)
                        kb.release(k)
                else:  # 只按修飾鍵本身，例如單按 win
                    pass
            finally:
                for m in reversed(mods):
                    kb.release(m)
            if "shift" in keys:  # 放開 Shift 會讓注音切回中文模式，按完再切回英數
                time.sleep(0.03)
                force_alphanumeric_ime()
            done += 1
            time.sleep(0.06)
    return done


# ---------------------------------------------------------------- 座標
def input_scale() -> Tuple[float, float]:
    """截圖是實體像素；若行程不是 DPI aware，滑鼠用的是邏輯像素，要換算。Qt 程式內通常為 1.0。"""
    try:
        from PIL import ImageGrab
        u = ctypes.windll.user32
        lw, lh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        pw, ph = ImageGrab.grab().size
        if lw and lh and pw and ph:
            return lw / pw, lh / ph
    except Exception:
        pass
    return 1.0, 1.0


def _scaled(x: int, y: int, scale: Tuple[float, float]) -> Tuple[int, int]:
    return int(round(x * scale[0])), int(round(y * scale[1]))


# ---------------------------------------------------------------- 給 agent 迴圈用
async def run_tool(name: str, args: Dict[str, Any], brain=None) -> Tuple[str, Optional[str]]:
    sec = getattr(brain, "security_guard", None)
    desk = getattr(brain, "desktop", None)

    def stopped() -> bool:
        return bool(sec is not None and sec.emergency_stop_triggered)

    def result(**kw) -> Tuple[str, Optional[str]]:
        return json.dumps(kw, ensure_ascii=False), None

    try:
        if name == "computer_wait":
            await asyncio.sleep(max(0.1, min(float(args.get("seconds") or 1), 10.0)))
            return result(ok=True, waited=args.get("seconds") or 1)

        if stopped():
            return result(ok=False, message="緊急停止開關已啟動，已中止所有桌面操作。")
        if desk is not None:
            ok_slot, reason = await desk.wait_for_safe_foreground_slot()
            if not ok_slot:
                return result(ok=False, deferred_by_dnd=True, message=reason)

        if name == "computer_key":
            keys = str(args.get("keys", ""))
            chords = parse_keys(keys)
            n = await asyncio.to_thread(press_chords, chords, int(args.get("repeat") or 1), stopped)
            return result(ok=True, keys=keys, pressed=n, hint="按完後請截圖或讀結構樹確認畫面變化")

        from pynput.mouse import Button, Controller
        mouse = getattr(desk, "mouse", None) or Controller()
        scale = input_scale()

        if name == "computer_scroll":
            x, y = _scaled(int(args.get("x", 0)), int(args.get("y", 0)), scale)
            amount = max(1, min(int(args.get("amount") or 3), 15))
            direction = str(args.get("direction", "down")).lower()
            dx, dy = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}.get(direction, (0, -1))
            if desk is not None:
                await asyncio.to_thread(desk.move_mouse_humanlike, x, y)
            else:
                mouse.position = (x, y)
            for _ in range(amount):
                if stopped():
                    break
                mouse.scroll(dx, dy)
                await asyncio.sleep(0.04)
            return result(ok=True, x=args.get("x"), y=args.get("y"), direction=direction, amount=amount)

        if name == "computer_drag":
            fx, fy = _scaled(int(args["from_x"]), int(args["from_y"]), scale)
            tx, ty = _scaled(int(args["to_x"]), int(args["to_y"]), scale)

            def _drag():
                if desk is not None:
                    desk.move_mouse_humanlike(fx, fy)
                else:
                    mouse.position = (fx, fy)
                mouse.press(Button.left)
                try:
                    time.sleep(0.08)
                    if desk is not None:
                        desk.move_mouse_humanlike(tx, ty, duration=0.5)
                    else:
                        mouse.position = (tx, ty)
                    time.sleep(0.08)
                finally:
                    mouse.release(Button.left)

            await asyncio.to_thread(_drag)
            return result(ok=True, dragged_from=[args["from_x"], args["from_y"]], dragged_to=[args["to_x"], args["to_y"]])
    except (ValueError, KeyError) as e:
        return result(ok=False, error=str(e))
    except Exception as e:
        return result(ok=False, error=f"{type(e).__name__}: {e}")
    return result(ok=False, error=f"未知的操控工具：{name}")
