# -*- coding: utf-8 -*-
"""安裝程式的指令列／互動介面。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, List, Optional

from . import __version__
from .environment import MIN_PYTHON, Environment, detect
from .modules import catalog
from .planner import (Plan, ResolveError, available, build_plan, full_selection,
                      recommend, resolve)
from .state import installed_modules, manifest_path, pip_install, record

PROJECT_ROOT = Path(__file__).resolve().parent.parent

STATUS_LABEL = {
    "missing": "未安裝",
    "outdated": "版本不符",
    "reinstall": "強制重裝",
}


def _setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def print_env(env: Environment) -> None:
    print("== 環境偵測 ==")
    print(f"  作業系統：{env.os_name}（{env.platform}）")
    print(f"  Python：{'.'.join(map(str, env.python_version))}  ({env.python_executable})")
    print(f"  顯示卡：{env.gpu or '未偵測到獨立顯示卡'}")
    print(f"  磁碟剩餘：{env.free_disk_mb:,} MB")
    print(f"  系統管理員：{'是' if env.is_admin else '否'}　Node.js：{'有' if env.has_node else '無'}"
          f"　開發目錄(git)：{'是' if env.in_git_checkout else '否'}")
    print()


def print_modules(env: Environment, installed: List[str]) -> None:
    print("== 可安裝模組 ==")
    for i, mod in enumerate(catalog().values(), 1):
        tags = []
        if mod.required:
            tags.append("必裝")
        if mod.manual:
            tags.append("手動")
        if mod.id in installed:
            tags.append("已安裝")
        if not available(mod, env, PROJECT_ROOT):
            tags.append("此環境不可用")
        dep = f"　需要：{', '.join(mod.depends)}" if mod.depends else ""
        tag = f"［{'、'.join(tags)}］" if tags else ""
        print(f"  {i:>2}. {mod.id:<20}{mod.name}{tag}")
        print(f"      {mod.summary}　約 {mod.size_mb} MB{dep}")
    print()


def print_plan(plan: Plan, extra_deps: List[str]) -> None:
    print("== 安裝計畫 ==")
    for item in plan.items:
        auto = "（相依自動帶入）" if item.module.id in extra_deps else ""
        if item.status == "manual":
            print(f"  ⚙ {item.module.id}：需手動處理{auto}")
        elif item.status == "satisfied":
            print(f"  ✓ {item.module.id}：已滿足，略過{auto}")
        else:
            print(f"  ↓ {item.module.id}：需安裝{auto}")
            for spec, state, ver in item.missing:
                have = f"，目前 {ver}" if ver else ""
                print(f"       - {spec}（{STATUS_LABEL.get(state, state)}{have}）")
    specs = plan.pip_specs
    print()
    if specs:
        print(f"共需安裝 {len(specs)} 個套件：{' '.join(specs)}")
    else:
        print("所有選擇的模組都已滿足，不需要安裝任何套件。")
    print()


def _ask(prompt: str, ask: Callable[[str], str]) -> str:
    try:
        return ask(prompt).strip()
    except EOFError:
        return ""


def interactive_select(env: Environment, installed: List[str],
                       ask: Callable[[str], str] = input) -> Optional[List[str]]:
    rec = recommend(env, PROJECT_ROOT, installed=installed)
    print("請選擇安裝模式：")
    print(f"  1) 推薦安裝（{', '.join(rec.modules)}）")
    print("  2) 完整安裝（所有可用模組）")
    print("  3) 自訂安裝（自己勾選）")
    print("  q) 離開")
    choice = _ask("輸入選項 [1]：", ask) or "1"
    if choice.lower() == "q":
        return None
    if choice == "2":
        return full_selection(env, PROJECT_ROOT)
    if choice != "3":
        _print_reasons(rec.reasons)
        return rec.modules

    mods = list(catalog().values())
    chosen = set(rec.modules)
    while True:
        print("\n目前勾選（輸入編號切換，可用逗號分隔；Enter 確認；q 離開）：")
        for i, mod in enumerate(mods, 1):
            ok = available(mod, env, PROJECT_ROOT) and not mod.manual
            mark = "[x]" if mod.id in chosen else ("[ ]" if ok else "[-]")
            lock = "（必裝）" if mod.required else ("" if ok else "（此環境不可用）")
            print(f"  {i:>2}. {mark} {mod.id:<20}{mod.name}{lock}")
        ans = _ask("> ", ask)
        if not ans:
            return sorted(chosen)
        if ans.lower() == "q":
            return None
        for tok in ans.replace(" ", ",").split(","):
            if not tok.isdigit() or not 1 <= int(tok) <= len(mods):
                continue
            mod = mods[int(tok) - 1]
            if mod.required or mod.manual or not available(mod, env, PROJECT_ROOT):
                continue
            chosen.symmetric_difference_update({mod.id})


def _print_reasons(reasons) -> None:
    print("\n== 推薦理由 ==")
    for mid, why in reasons.items():
        print(f"  {mid:<20}{why}")
    print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="py -m installer", description="Syntra 星樞 安裝程式")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--recommended", action="store_true", help="依環境自動選擇模組")
    mode.add_argument("--full", action="store_true", help="安裝所有可用模組")
    mode.add_argument("--modules", help="自訂模組，逗號分隔，例如 desktop-ui,google-workspace")
    p.add_argument("--exclude", default="", help="排除的模組（逗號分隔，必裝模組不可排除）")
    p.add_argument("--dry-run", action="store_true", help="只列出安裝計畫，不實際安裝")
    p.add_argument("--list", action="store_true", help="列出所有模組後結束")
    p.add_argument("--force", action="store_true", help="即使已安裝也強制重裝")
    p.add_argument("-y", "--yes", action="store_true", help="不詢問確認")
    p.add_argument("--version", action="version", version=f"Syntra installer {__version__}")
    return p


def main(argv: Optional[List[str]] = None, ask: Callable[[str], str] = input,
         env: Optional[Environment] = None) -> int:
    _setup_console()
    args = build_parser().parse_args(argv)
    print(f"Syntra 星樞 安裝程式 v{__version__}\n")
    env = env or detect(PROJECT_ROOT)
    print_env(env)
    if not env.python_ok:
        print(f"✘ 需要 Python {'.'.join(map(str, MIN_PYTHON))} 以上，請先更新 Python。")
        return 2
    installed = installed_modules(PROJECT_ROOT)

    if args.list:
        print_modules(env, installed)
        return 0

    if args.recommended:
        rec = recommend(env, PROJECT_ROOT, installed=installed)
        _print_reasons(rec.reasons)
        selected = rec.modules
    elif args.full:
        selected = full_selection(env, PROJECT_ROOT)
    elif args.modules:
        selected = [m.strip() for m in args.modules.split(",") if m.strip()]
    else:
        print_modules(env, installed)
        selected = interactive_select(env, installed, ask)
        if selected is None:
            print("已取消。")
            return 1

    exclude = {m.strip() for m in args.exclude.split(",") if m.strip()}
    try:
        order = resolve([m for m in selected if m not in exclude], platform=env.platform)
    except ResolveError as exc:
        print(f"✘ {exc}")
        return 2
    blocked = [m for m in order if m in exclude]
    if blocked:
        print(f"✘ 無法排除 {', '.join(blocked)}：它是必裝模組或其他已選模組的相依。")
        return 2

    plan = build_plan(order, force=args.force)
    print_plan(plan, extra_deps=[m for m in order if m not in selected])

    if args.dry_run:
        print("（--dry-run：只列出計畫，未做任何變更）")
        return 0

    if plan.pip_specs and not args.yes:
        if _ask("確定要開始安裝嗎？[Y/n]：", ask).lower() in ("n", "no"):
            print("已取消。")
            return 1

    rc = pip_install(env.python_executable, plan.pip_specs, force=args.force)
    if rc != 0:
        print(f"✘ pip 安裝失敗（代碼 {rc}），已安裝紀錄未更新，修正後重跑即可續裝。")
        return rc

    final = build_plan(order)
    if not final.nothing_to_do:
        print("✘ 安裝後仍有套件未滿足：" + " ".join(final.pip_specs))
        return 3
    changed = record(PROJECT_ROOT, final)
    print(f"✔ 安裝完成。紀錄檔：{manifest_path(PROJECT_ROOT)}{'（已更新）' if changed else '（無變更）'}")
    for item in final.items:
        for note in item.module.notes:
            print(f"  • {item.module.name}：{note}")
    return 0
