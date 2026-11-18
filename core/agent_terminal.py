# -*- coding: utf-8 -*-
"""
每個代理一個「持續存在」的 PowerShell 終端機（記得目前目錄、變數、匯入的模組）。

- 互不干擾：每個代理各自一個 PowerShell 行程；同一個終端一次只跑一個指令（排隊）。
- 串起來共用：TerminalManager.link(a, b) 之後，a、b（以及跟它們串在一起的所有代理）共用同一個終端；
  斷開後各自回到自己原本的終端（狀態都還在）。
- 指令一律寫成 UTF-8 暫存腳本再 dot-source 執行：中文不會亂碼、多行指令也能跑，
  命令列上只有 `-Command -`，不會觸發防毒哨兵攔截的字樣。
- 環境變數會先移除各種 API Key / Token，與背景指令相同。
- 不依賴 Qt：UI 用 add_listener 收到輸出，再自行轉回 UI 執行緒。
"""
from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

Listener = Callable[[str, str, str], None]  # (event, text, by)；event = cmd | out | done | info

_SECRET_ENV = ("API_KEY", "SECRET", "PRIVATE_KEY", "AUTH_TOKEN")
_SECRET_NAMES = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "NVIDIA_API_KEY",
                 "DISCORD_BOT_TOKEN", "GITHUB_TOKEN"}
MAX_OUTPUT = 12_000
HISTORY_LINES = 2_000


def _clean_env() -> Dict[str, str]:
    env = dict(os.environ)
    for k in list(env):
        if k in _SECRET_NAMES or any(t in k.upper() for t in _SECRET_ENV):
            env.pop(k, None)
    return env


class TerminalSession:
    """一個持續存在的 PowerShell 行程。"""

    def __init__(self, session_id: str, cwd: Optional[str] = None, shell: str = "powershell"):
        self.session_id = session_id
        self.shell = shell
        self.cwd = str(Path(cwd or Path.home()))
        self.proc: Optional[subprocess.Popen] = None
        self.history: Deque[Tuple[str, str, str]] = deque(maxlen=HISTORY_LINES)
        self._listeners: List[Listener] = []
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self.busy_by = ""

    # ---------------------------------------------------------------- 監聽
    def add_listener(self, fn: Listener):
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_listener(self, fn: Listener):
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _emit(self, event: str, text: str, by: str = ""):
        self.history.append((event, text, by))
        for fn in list(self._listeners):
            try:
                fn(event, text, by)
            except Exception:
                pass

    # ---------------------------------------------------------------- 行程
    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _start(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=self.cwd if Path(self.cwd).is_dir() else None, env=_clean_env(), creationflags=flags,
        )
        self._lines = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, args=(self.proc, self._lines), daemon=True,
                                        name=f"term-{self.session_id}")
        self._reader.start()
        self._exec_raw("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'",
                       timeout=20, echo=False)

    @staticmethod
    def _read_loop(proc: subprocess.Popen, out: "queue.Queue[Optional[str]]"):
        stream = proc.stdout
        try:
            for raw in iter(stream.readline, b""):
                out.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        except Exception:
            pass
        out.put(None)

    def ensure(self):
        with self._state_lock:
            if not self.alive:
                self._start()

    def kill(self):
        p = self.proc
        self.proc = None
        if p is not None and p.poll() is None:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def interrupt(self):
        """中斷正在跑的指令：PowerShell 不能從外部 Ctrl+C，只能重開（目前目錄會保留）。"""
        self.kill()
        self._emit("info", "⏹ 已中斷，終端已重新啟動（目前目錄保留，變數已清空）")

    # ---------------------------------------------------------------- 執行
    def _exec_raw(self, script: str, timeout: float, echo: bool = True, by: str = "") -> Dict[str, object]:
        fd, path = tempfile.mkstemp(prefix="syntra_term_", suffix=".ps1")
        os.close(fd)
        Path(path).write_text(script, encoding="utf-8")
        token = uuid.uuid4().hex[:12]
        marker = f"__SYNTRA_DONE_{token}__"
        safe = path.replace("'", "''")
        # 錯誤判斷用 $Error 筆數（經過 Out-String 管線後 $? 永遠是 True）；先把上一個指令留下的結束碼歸零
        line = (f"$__e = $Error.Count; $global:LASTEXITCODE = 0; "
                f". ([ScriptBlock]::Create([IO.File]::ReadAllText('{safe}', [Text.Encoding]::UTF8))) 2>&1 "
                f"| Out-String -Stream -Width 220; "
                f"$__ok = ($Error.Count -eq $__e); "
                f"Write-Output ('{marker}|' + $__ok + '|' + $LASTEXITCODE + '|' + (Get-Location).Path)\n")
        out_lines: List[str] = []
        result: Dict[str, object] = {"ok": False, "exit_code": -1, "output": "", "cwd": self.cwd}
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            self.proc.stdin.flush()
            deadline = time.time() + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    self.kill()
                    result.update(exit_code=-2, output="\n".join(out_lines)[-MAX_OUTPUT:] +
                                  f"\n⏱ 指令超過 {int(timeout)} 秒，已中斷並重新啟動終端")
                    self._emit("info", f"⏱ 超過 {int(timeout)} 秒，已中斷")
                    return result
                try:
                    item = self._lines.get(timeout=min(remaining, 0.5))
                except queue.Empty:
                    continue
                if item is None:
                    result.update(exit_code=-9, output="\n".join(out_lines)[-MAX_OUTPUT:] + "\n🛑 終端已關閉或被中斷")
                    return result
                if item.startswith(marker):
                    _, ok, code, cwd = (item.split("|", 3) + ["", "", ""])[:4]
                    self.cwd = cwd or self.cwd
                    exit_code = int(code) if code.strip().lstrip("-").isdigit() else (0 if ok == "True" else 1)
                    result.update(ok=(ok == "True" and exit_code == 0), exit_code=exit_code, cwd=self.cwd,
                                  output="\n".join(out_lines)[-MAX_OUTPUT:])
                    return result
                out_lines.append(item)
                if echo:
                    self._emit("out", item, by)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def run(self, command: str, by: str = "", timeout: float = 120.0) -> Dict[str, object]:
        """執行一個指令（同一終端排隊執行）。回傳 {ok, exit_code, output, cwd}。"""
        with self._run_lock:
            self.ensure()
            self.busy_by = by
            self._emit("cmd", command, by)
            try:
                res = self._exec_raw(command, timeout=timeout, by=by)
            except Exception as e:
                self.kill()
                res = {"ok": False, "exit_code": -1, "output": f"終端錯誤：{type(e).__name__}: {e}", "cwd": self.cwd}
            finally:
                self.busy_by = ""
            self._emit("done", f"{res['exit_code']}|{res['cwd']}", by)
            return res

    def tail(self, n: int = 200) -> List[Tuple[str, str, str]]:
        return list(self.history)[-n:]


class TerminalManager:
    """管理每個代理的終端，以及代理之間「串起來共用」的關係。"""

    def __init__(self, default_cwd: Optional[str] = None):
        self.default_cwd = default_cwd
        self._own: Dict[str, TerminalSession] = {}
        self._links: Set[frozenset] = set()
        self._order: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._listeners: List[Callable[[], None]] = []

    def on_change(self, fn: Callable[[], None]):
        self._listeners.append(fn)

    def off_change(self, fn: Callable[[], None]):
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _changed(self):
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                pass

    def register(self, agent_id: str):
        with self._lock:
            self._order.setdefault(agent_id, len(self._order))

    def _own_session(self, agent_id: str) -> TerminalSession:
        with self._lock:
            self.register(agent_id)
            s = self._own.get(agent_id)
            if s is None:
                s = self._own[agent_id] = TerminalSession(f"t_{agent_id}", cwd=self.default_cwd)
            return s

    # ------------------------------------------------ 群組（連線的代理共用一個終端）
    def group_of(self, agent_id: str) -> List[str]:
        with self._lock:
            seen, stack = {agent_id}, [agent_id]
            while stack:
                cur = stack.pop()
                for pair in self._links:
                    if cur in pair:
                        for other in pair:
                            if other not in seen:
                                seen.add(other)
                                stack.append(other)
            return sorted(seen, key=lambda a: self._order.get(a, 1 << 30))

    def session_for(self, agent_id: str) -> TerminalSession:
        """代理目前使用的終端：群組裡最早建立的那個代理的終端。"""
        return self._own_session(self.group_of(agent_id)[0])

    def link(self, a: str, b: str) -> bool:
        if a == b:
            return False
        with self._lock:
            self.register(a)
            self.register(b)
            pair = frozenset((a, b))
            if pair in self._links:
                return False
            self._links.add(pair)
        self.session_for(a)._emit("info", "🔗 已和其他代理串接，現在共用這個終端")
        self._changed()
        return True

    def unlink(self, a: str, b: str) -> bool:
        with self._lock:
            pair = frozenset((a, b))
            if pair not in self._links:
                return False
            self._links.discard(pair)
        self._changed()
        return True

    def links(self) -> List[Tuple[str, str]]:
        with self._lock:
            return [tuple(sorted(p, key=lambda x: self._order.get(x, 0))) for p in self._links]

    def is_linked(self, a: str, b: str) -> bool:
        return b in self.group_of(a)

    def remove_agent(self, agent_id: str):
        with self._lock:
            self._links = {p for p in self._links if agent_id not in p}
            s = self._own.pop(agent_id, None)
            self._order.pop(agent_id, None)
        if s is not None:
            s.kill()
        self._changed()

    def run(self, agent_id: str, command: str, by: str = "", timeout: float = 120.0) -> Dict[str, object]:
        return self.session_for(agent_id).run(command, by=by or agent_id, timeout=timeout)

    def interrupt_all(self):
        with self._lock:
            sessions = list(self._own.values())
        for s in sessions:
            if s.busy_by:
                s.interrupt()

    def shutdown(self):
        with self._lock:
            sessions = list(self._own.values())
            self._own.clear()
        for s in sessions:
            s.kill()


terminal_manager = TerminalManager()
