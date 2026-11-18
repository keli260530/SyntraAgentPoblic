# -*- coding: utf-8 -*-
"""
共用行程事件中樞 (Process Event Hub)

取代過去 5 條各自用 psutil.process_iter() 全掃的輪詢執行緒：
- 只用一條執行緒，每 0.5 秒呼叫一次 psutil.pids()（單一 EnumProcesses 系統呼叫，約 1ms），
  比對出「新出現的行程」後才去讀名稱 / 路徑 / 命令列，並以事件方式推給各哨兵。
- 週期性工作（金絲雀檢查、管理員稽核…）統一由這條執行緒排程，不再各開一條。
- 遊戲模式：偵測到全螢幕遊戲時，新行程偵測照常（防護不中斷），
  但標記為 heavy 的重工作（全行程記憶體掃描）會延後執行，避免搶遊戲幀率。
- 保護清單：遊戲中的前景行程及其子行程一律不准被任何哨兵終止，只能記錄告警。
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

import psutil

try:
    import win32gui
    import win32process
except Exception:  # 非 Windows 或缺 pywin32 時仍可匯入（測試用）
    win32gui = None
    win32process = None


GAME_KEYWORDS = {
    "valorant", "league of legends", "leagueclient", "genshin", "yuanshen",
    "starrail", "zenless", "cs2", "csgo", "dota2", "apex", "overwatch",
    "minecraft", "javaw", "eldenring", "monsterhunter", "cyberpunk",
    "palworld", "blackmyth", "wukong", "helldivers", "baldursgate",
    "fortnite", "pubg", "roblox", "steam_app", "unreal", "unity",
}
NON_GAME_FULLSCREEN = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "explorer.exe", "python.exe", "pythonw.exe", "potplayermini64.exe",
    "potplayer.exe", "vlc.exe", "mpv.exe", "powerpnt.exe",
}


@dataclass
class ProcInfo:
    pid: int
    name: str = ""
    exe: str = ""
    cmdline: str = ""
    ppid: int = 0
    seen_at: float = field(default_factory=time.time)


@dataclass
class _PeriodicTask:
    name: str
    interval: float
    fn: Callable[[], None]
    heavy: bool
    max_defer: float
    next_run: float = 0.0
    last_run: float = 0.0


class ProcessEventHub:
    TICK_SECONDS = 0.5
    GAME_CHECK_SECONDS = 2.0

    def __init__(self):
        self._lock = threading.RLock()
        self._known: Set[int] = set()
        self._recent: Dict[int, ProcInfo] = {}  # 最近 5 分鐘內新生的行程
        self._spawn_subs: List[Callable[[List[ProcInfo]], None]] = []
        self._tasks: List[_PeriodicTask] = []
        self._thread: Optional[threading.Thread] = None
        self._active = False
        self._gaming = False
        self._game_pid = 0
        self._protected: Set[int] = set()
        self._self_ancestors: Optional[Set[int]] = None
        self._next_game_check = 0.0
        self.stats = {"ticks": 0, "spawns": 0, "deferred_heavy": 0, "blocked_kills": 0}

    # ------------------------------------------------------------------ 訂閱
    def on_spawn(self, callback: Callable[[List[ProcInfo]], None]) -> None:
        """訂閱「新行程出現」事件；callback 收到這一輪所有新行程的 ProcInfo 清單。"""
        with self._lock:
            self._spawn_subs.append(callback)
        self.start()

    def every(self, name: str, interval: float, fn: Callable[[], None],
              heavy: bool = False, max_defer: float = 600.0) -> None:
        """登記週期性工作。heavy=True 的工作在遊戲中會延後，但最多延後 max_defer 秒。"""
        with self._lock:
            self._tasks = [t for t in self._tasks if t.name != name]
            self._tasks.append(_PeriodicTask(name, interval, fn, heavy, max_defer,
                                             next_run=time.time() + min(interval, 5.0),
                                             last_run=time.time()))
        self.start()

    # ------------------------------------------------------------------ 查詢
    def is_gaming(self) -> bool:
        return self._gaming

    def is_protected(self, pid: int) -> bool:
        """遊戲行程（含子行程）與 Syntra 自己的行程家族不得被自動終止。"""
        return pid in self._protected or self.is_self_family(pid)

    def is_self_family(self, pid: int) -> bool:
        """Syntra 自己、啟動它的上層行程、以及它開的子行程（看門狗等）。
        執行檔改名成 Syntra.exe 後，各哨兵的「pythonw.exe 白名單」不再適用，這裡用行程關係保護自己。"""
        if not pid:
            return False
        me = os.getpid()
        if pid == me:
            return True
        try:
            if self._self_ancestors is None:
                self._self_ancestors = {p.pid for p in psutil.Process(me).parents()}
            if pid in self._self_ancestors:
                return True
            return pid in {c.pid for c in psutil.Process(me).children(recursive=True)}
        except Exception:
            return False

    def guard_kill(self, pid: int) -> bool:
        """各哨兵終止行程前呼叫：回傳 True 才可以動手。"""
        if self.is_protected(pid):
            self.stats["blocked_kills"] += 1
            return False
        return True

    def recent_spawns(self, within_seconds: float = 120.0) -> List[ProcInfo]:
        cutoff = time.time() - within_seconds
        with self._lock:
            return [p for p in self._recent.values() if p.seen_at >= cutoff]

    # ------------------------------------------------------------------ 生命週期
    def start(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
            self._known = set(psutil.pids())  # 開機當下既有行程不視為「新生」
            self._thread = threading.Thread(target=self._run, daemon=True, name="ProcessEventHub")
            self._thread.start()

    def stop(self) -> None:
        self._active = False

    # ------------------------------------------------------------------ 內部
    def _run(self) -> None:
        while self._active:
            started = time.time()
            try:
                self._tick(started)
            except Exception:
                pass
            elapsed = time.time() - started
            time.sleep(max(0.05, self.TICK_SECONDS - elapsed))

    def _tick(self, now: float) -> None:
        self.stats["ticks"] += 1
        if now >= self._next_game_check:
            self._next_game_check = now + self.GAME_CHECK_SECONDS
            self._refresh_game_state()

        current = set(psutil.pids())
        new_pids = current - self._known
        dead = self._known - current
        self._known = current

        if dead:
            with self._lock:
                for pid in dead:
                    self._recent.pop(pid, None)
                self._protected -= dead

        if new_pids:
            infos = [i for i in (self._describe(pid) for pid in new_pids) if i]
            if infos:
                self.stats["spawns"] += len(infos)
                with self._lock:
                    for info in infos:
                        self._recent[info.pid] = info
                        if self._gaming and info.ppid in self._protected:
                            self._protected.add(info.pid)  # 遊戲自己開的子行程也保護
                    subs = list(self._spawn_subs)
                for cb in subs:
                    try:
                        cb(infos)
                    except Exception:
                        pass

        self._prune_recent(now)
        self._run_due_tasks(now)

    def _describe(self, pid: int) -> Optional[ProcInfo]:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                info = ProcInfo(pid=pid, name=(p.name() or "").lower(), ppid=p.ppid())
                try:
                    info.exe = (p.exe() or "").lower()
                except (psutil.AccessDenied, OSError):
                    pass
                try:
                    info.cmdline = " ".join(p.cmdline() or []).lower()
                except (psutil.AccessDenied, OSError):
                    pass
            return info
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return None

    def _prune_recent(self, now: float) -> None:
        if self.stats["ticks"] % 60:
            return
        cutoff = now - 300
        with self._lock:
            for pid in [p for p, i in self._recent.items() if i.seen_at < cutoff]:
                self._recent.pop(pid, None)

    def _run_due_tasks(self, now: float) -> None:
        with self._lock:
            tasks = list(self._tasks)
        for t in tasks:
            if now < t.next_run:
                continue
            if t.heavy and self._gaming and (now - t.last_run) < t.max_defer:
                t.next_run = now + 15.0  # 遊戲中：稍後再看
                self.stats["deferred_heavy"] += 1
                continue
            t.last_run = now
            t.next_run = now + t.interval
            try:
                t.fn()
            except Exception:
                pass

    def _refresh_game_state(self) -> None:
        pid, name, title, fullscreen = self._foreground()
        is_game = bool(pid) and name not in NON_GAME_FULLSCREEN and (
            fullscreen or any(k in name or k in title for k in GAME_KEYWORDS)
        )
        with self._lock:
            if is_game:
                if pid != self._game_pid:
                    self._game_pid = pid
                    self._protected = {pid} | self._descendants(pid)
                else:
                    self._protected.add(pid)
                self._gaming = True
            else:
                self._gaming = False
                self._game_pid = 0
                self._protected = set()

    @staticmethod
    def _descendants(pid: int) -> Set[int]:
        try:
            return {c.pid for c in psutil.Process(pid).children(recursive=True)}
        except Exception:
            return set()

    @staticmethod
    def _foreground():
        if not win32gui:
            return 0, "", "", False
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return 0, "", "", False
            if win32gui.GetClassName(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return 0, "", "", False
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            title = (win32gui.GetWindowText(hwnd) or "").lower()
            try:
                name = psutil.Process(pid).name().lower()
            except Exception:
                name = ""
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            fullscreen = (r - l) >= sw and (b - t) >= sh and l <= 0 and t <= 0
            return pid, name, title, fullscreen
        except Exception:
            return 0, "", "", False


# 全域單例
process_hub = ProcessEventHub()
