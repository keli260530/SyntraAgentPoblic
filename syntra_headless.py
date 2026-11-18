# -*- coding: utf-8 -*-
"""
syntra_headless.py — 不開視窗執行 Syntra 代理（給伺服器／排程／遠端桌面以外的環境用）

    python syntra_headless.py serve                 常駐服務：開遙控 API，讓 syntra CLI 下指令
    python syntra_headless.py serve --host 0.0.0.0  允許區域網路其他電腦連線（需 token）
    python syntra_headless.py chat                  在命令列跟代理對話（可用 ps / new / !ls 等指令）
    python syntra_headless.py run "整理下載資料夾"   執行一個任務，印出結果後結束（適合排程）

共用選項：--model <模型 ID>（預設依設定自動路由）

需要批准的操作：
- chat / run 在終端機直接詢問 y/N（run 若不是互動終端機，一律拒絕）
- serve 會印出待批准項目，用 syntra approvals、approve <id>、deny <id> 處理（CLI 在 cli/ 資料夾）
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


# ───────────────────────── 建立核心元件（與桌面版／server.py 相同） ─────────────────────────
class Runtime:
    def __init__(self, model_id=None, on_event=None, discord=True):
        log("⏳ 正在啟動 Syntra 核心（無介面模式）…")
        from core.agent_brain import AgentBrain
        from core.agent_host import AgentHost
        from core.api_manager import ApiManager
        from core.context_guard import ContextGuard
        from core.desktop_controller import DesktopController
        from core.security_guard import SecurityGuard
        from core.settings_manager import SettingsManager
        from core.web_auditor import WebAuditor

        self.settings_manager = SettingsManager()
        self.api_manager = ApiManager()
        self.context_guard = ContextGuard(self.settings_manager)
        self.security_guard = SecurityGuard(self.settings_manager, api_manager=self.api_manager)
        self.api_manager.set_security_guard(self.security_guard)
        self.desktop_controller = DesktopController(self.context_guard, self.security_guard)
        self.web_auditor = WebAuditor(self.settings_manager, self.security_guard)
        self.agent_brain = AgentBrain(
            settings_manager=self.settings_manager,
            api_manager=self.api_manager,
            context_guard=self.context_guard,
            security_guard=self.security_guard,
            desktop_controller=self.desktop_controller,
            web_auditor=self.web_auditor,
        )

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_loop, name="SyntraLoop", daemon=True).start()

        self.discord_bridge = None
        if discord:
            try:
                from core.discord_bot import DiscordBotBridge
                from core.supervisor import AICodingSupervisor
                supervisor = AICodingSupervisor(
                    settings_manager=self.settings_manager, context_guard=self.context_guard,
                    desktop_controller=self.desktop_controller, agent_brain=self.agent_brain)
                self.discord_bridge = DiscordBotBridge(
                    settings_manager=self.settings_manager, security_guard=self.security_guard,
                    supervisor=supervisor, agent_brain=self.agent_brain)
                self.agent_brain.set_discord_notifier(self.discord_bridge.send_notification)
                self.discord_bridge.start()
            except Exception as e:  # noqa: BLE001
                log(f"（Discord 通知未啟用：{e}）")

        self.host = AgentHost(self.agent_brain, self.loop, security_guard=self.security_guard,
                              desktop_controller=self.desktop_controller, model_id=model_id,
                              on_event=on_event)
        log("✅ 核心已就緒")

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown(self):
        try:
            if self.discord_bridge:
                self.discord_bridge.stop()
        except Exception:
            pass
        try:
            self.desktop_controller.kill_running_commands()
        except Exception:
            pass


# ───────────────────────── 批准 ─────────────────────────
class ApprovalPrompter:
    """在終端機詢問待批准的操作；interactive=False 時一律拒絕"""

    def __init__(self, host, interactive: bool):
        self.host = host
        self.interactive = interactive
        self.seen = set()

    def check(self):
        for ap in self.host.list_approvals():
            if ap["id"] in self.seen:
                continue
            self.seen.add(ap["id"])
            log(f"\n⚠️  需要你批准：{ap['title']}\n    原因：{ap['reason']}")
            if not self.interactive:
                self.host.resolve_approval(ap["id"], False)
                log("    → 非互動模式，已自動拒絕")
                continue
            try:
                ans = input("    要放行嗎？[y/N] ").strip().lower()
            except EOFError:
                ans = ""
            pin = None
            if ans in ("y", "yes") and ap.get("requires_pin"):
                pin = getpass.getpass("    這是交易類操作，請輸入安全 PIN 碼：")
            res = self.host.resolve_approval(ap["id"], ans in ("y", "yes"), pin)
            log(f"    → {res.get('message') or res.get('error')}")


def wait_with_approvals(future, prompter: ApprovalPrompter, timeout=None):
    t_end = time.time() + timeout if timeout else None
    while not future.done():
        prompter.check()
        if t_end and time.time() > t_end:
            return False
        time.sleep(0.3)
    return True


def print_event(kind, data):
    if kind == "step":
        log(f"  · {data['text']}")


# ───────────────────────── run：單次任務 ─────────────────────────
def cmd_run(a):
    rt = Runtime(model_id=a.model, on_event=print_event, discord=False)
    text = " ".join(a.text)
    if text == "-":
        text = sys.stdin.read()
    res = rt.host.ask_agent(1, text)
    if not res.get("ok"):
        log(f"❌ {res.get('error')}")
        return 1
    agent = rt.host._by_no(1)
    prompter = ApprovalPrompter(rt.host, interactive=sys.stdin.isatty() and not a.deny_all)
    if not wait_with_approvals(agent.future, prompter, timeout=a.timeout):
        rt.host.stop_agent(1)
        log(f"⏰ 超過 {a.timeout} 秒，已停止")
        rt.shutdown()
        return 2
    print(agent.messages[-1]["text"])
    rt.shutdown()
    return 0 if agent.status == "DONE" else 1


# ───────────────────────── chat：互動模式 ─────────────────────────
def cmd_chat(a):
    from core.agent_commands import HELP_TEXT, parse_agent_command
    from core.linux_shell import describe_linux_shell

    rt = Runtime(model_id=a.model, on_event=print_event, discord=not a.no_discord)
    host = rt.host
    prompter = ApprovalPrompter(host, interactive=True)
    current = 1
    remote = None
    if a.remote:
        remote = start_remote(rt, a.host, a.port)
    workdir = str(Path(a.cwd).resolve()) if a.cwd else str(Path.cwd())
    log(f"\n💬 無介面對話模式。輸入 help 看指令，exit 離開。工作目錄：{workdir}\n")

    while True:
        agent = host._by_no(current)
        if agent is None:
            current = 1
            agent = host._by_no(1)
        try:
            line = input(f"[{current}:{agent.name}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("exit", "quit", "q"):
            break
        parsed = parse_agent_command(line)
        if parsed:
            cmd, args = parsed
            no = args.get("no")
            if cmd == "help":
                print(HELP_TEXT)
            elif cmd == "ps":
                for ag in host.list_agents():
                    mark = "*" if ag["no"] == current else " "
                    status = {"IDLE": "待命", "RUNNING": "執行中", "DONE": "完成", "ERROR": "錯誤"}.get(ag["status"], ag["status"])
                    print(f"{mark}{ag['no']:<3} {status:<6} {ag['name']}")
            elif cmd == "new":
                r = host.new_agent(args.get("name"))
                current = r["no"]
                print(f"已新增並切換到 #{r['no']} {r['name']}")
            elif cmd == "cd":
                if host._by_no(no):
                    current = no
                else:
                    print(f"找不到編號 {no}")
            elif cmd == "kill":
                r = host.kill_agent(no)
                print(f"已關閉 {r['closed']}" if r["ok"] else r["error"])
                if r["ok"] and current == no:
                    current = 1
            elif cmd == "rename":
                r = host.rename_agent(no, args["name"])
                print("已改名" if r["ok"] else r["error"])
            elif cmd == "stop":
                r = host.stop_agent(no or current)
                print("已停止" if r.get("stopped") else "目前沒有在執行")
            elif cmd == "remote":
                if remote is None:
                    remote = start_remote(rt, a.host, a.port)
                else:
                    print_remote_info(remote)
            elif cmd == "sh":
                log(f"（{describe_linux_shell()}）")
                fut = rt.submit(rt.desktop_controller.run_background_command(
                    command=args["command"], cwd=workdir, timeout=300.0, shell="linux"))
                wait_with_approvals(fut, prompter)
                r = fut.result()
                print(r.get("output") or "（沒有輸出）")
                if r.get("exit_code") not in (0, None):
                    print(f"（結束代碼 {r.get('exit_code')}）")
            continue

        r = host.ask_agent(current, line)
        if not r.get("ok"):
            print(r.get("error"))
            continue
        try:
            wait_with_approvals(agent.future, prompter)
        except KeyboardInterrupt:
            host.stop_agent(current)
            log("\n⏹ 已停止這一輪")
            continue
        print("\n" + agent.messages[-1]["text"] + "\n")

    if remote:
        remote.stop()
    rt.shutdown()
    return 0


# ───────────────────────── serve：常駐服務 ─────────────────────────
def print_remote_info(server):
    log(f"🌐 遙控 API：{server.address}")
    log(f"🔑 token 檔案：{server.cfg['token_path']}")
    if server.cfg["host"] not in ("127.0.0.1", "localhost"):
        log("⚠️  已開放其他電腦連線；連線沒有加密，請只在信任的網路使用，或放在 VPN／反向代理（HTTPS）後面")


def start_remote(rt, host=None, port=None):
    from core.remote_control import DirectInvoker, RemoteControlServer
    server = RemoteControlServer(rt.host, BASE_DIR / "data", invoker=DirectInvoker(), host=host, port=port)
    if not server.start():
        log(f"❌ 遙控 API 未啟動：{server.error}")
        return None
    print_remote_info(server)
    return server


def cmd_serve(a):
    def on_event(kind, data):
        stamp = time.strftime("%H:%M:%S")
        if kind == "step":
            log(f"[{stamp}] #{data['no']} {data['name']} · {data['text']}")
        elif kind == "reply":
            first = (data["text"] or "").strip().splitlines()[:1]
            log(f"[{stamp}] #{data['no']} {data['name']} ✓ 回覆：{first[0][:80] if first else ''}")

    rt = Runtime(model_id=a.model, on_event=on_event, discord=not a.no_discord)
    server = start_remote(rt, a.host, a.port)
    if server is None:
        rt.shutdown()
        return 1
    log(f"\nCLI 用戶端在 {BASE_DIR / 'cli'}（Windows：syntra-windows.py，Linux：syntra-linux）")
    log(f"  syntra config --url {server.address}")
    log("  syntra config --token        （貼上 token 檔案內容）")
    log("  syntra ask \"你的任務\"")
    log("按 Ctrl+C 停止服務。\n")

    seen = set()
    try:
        while True:
            for ap in rt.host.list_approvals():
                if ap["id"] not in seen:
                    seen.add(ap["id"])
                    log(f"[{time.strftime('%H:%M:%S')}] ⚠️ 待批准 {ap['id']}：{ap['title']}"
                        f"\n    用 syntra approve {ap['id']} 或 syntra deny {ap['id']} 處理（10 分鐘內未處理會自動拒絕）")
            time.sleep(1.0)
    except KeyboardInterrupt:
        log("\n正在停止…")
    server.stop()
    rt.shutdown()
    return 0


def main():
    p = argparse.ArgumentParser(prog="syntra_headless", description="不開視窗執行 Syntra 代理")
    p.add_argument("--model", help="指定模型 ID（預設自動路由）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="常駐服務，開遙控 API")
    s.add_argument("--host", help="監聽位址（預設依 data/remote/config.json，通常是 127.0.0.1）")
    s.add_argument("--port", type=int, help="連接埠（預設 8765）")
    s.add_argument("--no-discord", action="store_true", help="不啟動 Discord 通知")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("chat", help="命令列互動對話")
    s.add_argument("--cwd", help="!指令 的工作目錄（預設目前目錄）")
    s.add_argument("--remote", action="store_true", help="同時開遙控 API")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--no-discord", action="store_true")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("run", help="執行單一任務後結束")
    s.add_argument("text", nargs="+", help="任務內容；- 代表從標準輸入讀")
    s.add_argument("--timeout", type=int, default=900, help="最多執行幾秒（預設 900）")
    s.add_argument("--deny-all", action="store_true", help="所有需要批准的操作一律拒絕")
    s.set_defaults(fn=cmd_run)

    a = p.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
