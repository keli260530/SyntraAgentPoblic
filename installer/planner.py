# -*- coding: utf-8 -*-
"""相依解析、推薦邏輯、已安裝偵測與安裝計畫。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .environment import Environment
from .modules import Module, catalog

try:  # packaging 通常隨 pip 一起安裝
    from packaging.requirements import Requirement
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover
    from pip._vendor.packaging.requirements import Requirement  # type: ignore
    from pip._vendor.packaging.version import InvalidVersion, Version  # type: ignore


class ResolveError(ValueError):
    pass


# ---------------------------------------------------------------- 相依解析

def resolve(selected: Iterable[str], modules: Optional[Dict[str, Module]] = None,
            platform: Optional[str] = None) -> List[str]:
    """回傳依安裝順序排列（相依在前）的模組 id，並自動帶入相依與必裝模組。"""
    mods = modules if modules is not None else catalog()
    order: List[str] = []
    visiting: set = set()

    def visit(mid: str, chain: Tuple[str, ...]) -> None:
        if mid in order:
            return
        if mid not in mods:
            raise ResolveError(f"未知的模組：{mid}（可用：{', '.join(mods)}）")
        if mid in visiting:
            raise ResolveError("模組相依形成循環：" + " -> ".join(chain + (mid,)))
        mod = mods[mid]
        if platform and not mod.supports(platform):
            raise ResolveError(f"模組 {mid}（{mod.name}）不支援此作業系統（{platform}）")
        visiting.add(mid)
        for dep in mod.depends:
            visit(dep, chain + (mid,))
        visiting.discard(mid)
        order.append(mid)

    wanted = [m.id for m in mods.values() if m.required] + list(selected)
    for mid in wanted:
        visit(mid, ())
    return order


# ---------------------------------------------------------------- 推薦

@dataclass
class Recommendation:
    modules: List[str]
    reasons: Dict[str, str]  # 模組 id -> 推薦或不推薦的原因


def available(mod: Module, env: Environment, project_root: Path) -> bool:
    return mod.supports(env.platform) and all((project_root / p).exists() for p in mod.paths)


def recommend(env: Environment, project_root: Path,
              modules: Optional[Dict[str, Module]] = None,
              installed: Iterable[str] = ()) -> Recommendation:
    mods = modules if modules is not None else catalog()
    installed = set(installed)
    picks: List[str] = []
    why: Dict[str, str] = {}

    def pick(mid: str, reason: str) -> None:
        if mid in mods and available(mods[mid], env, project_root):
            picks.append(mid)
            why[mid] = "✔ " + reason

    def skip(mid: str, reason: str) -> None:
        if mid in mods:
            why[mid] = "✘ " + reason

    pick("core", "必裝的核心引擎")
    low_disk = env.free_disk_mb and env.free_disk_mb < 1024

    for mid, mod in mods.items():
        if mid == "core":
            continue
        if not mod.supports(env.platform):
            skip(mid, f"不支援目前的作業系統（{env.os_name}）")
            continue
        if not available(mod, env, project_root):
            skip(mid, "此發行版沒有附這個模組的檔案")
            continue
        if mod.manual:
            skip(mid, "需要手動編譯／簽章，不自動安裝")
            continue
        if mid in installed:
            pick(mid, "先前已安裝，保留")
            continue
        if low_disk:
            skip(mid, f"磁碟剩餘空間不足 1 GB（{env.free_disk_mb} MB），只裝核心")
            continue

        if mid in ("desktop-ui", "desktop-automation", "security-suite"):
            pick(mid, "Windows 桌面環境的標準功能")
        elif mid == "remote-streaming":
            if env.gpu:
                pick(mid, f"偵測到顯示卡 {env.gpu}，適合畫面串流")
            else:
                skip(mid, "未偵測到獨立顯示卡，串流效能可能不佳（需要時可自訂加裝）")
        elif mid == "mcp-skills":
            if env.has_node:
                pick(mid, "偵測到 Node.js，可直接使用 MCP 伺服器")
            else:
                skip(mid, "未偵測到 Node.js，多數 MCP 伺服器無法執行")
        elif mid == "guardian":
            if env.is_admin:
                pick(mid, "目前為系統管理員，可註冊防毒服務")
            else:
                skip(mid, "需要系統管理員權限才能發揮作用（可用管理員身分重跑）")
        elif mid == "dev-tools":
            if env.in_git_checkout:
                pick(mid, "偵測到 git 原始碼目錄，看起來是開發環境")
            else:
                skip(mid, "一般使用者不需要測試工具")
        elif mid == "cli":
            pick(mid, "不需額外套件，佔用空間極小")
        elif mid == "google-workspace":
            skip(mid, "需要 Google 帳號授權，有需要再自訂加裝")
        else:
            skip(mid, "選用功能")

    return Recommendation(modules=resolve(picks, mods, env.platform), reasons=why)


def full_selection(env: Environment, project_root: Path,
                   modules: Optional[Dict[str, Module]] = None) -> List[str]:
    mods = modules if modules is not None else catalog()
    return [m.id for m in mods.values() if not m.manual and available(m, env, project_root)]


# ---------------------------------------------------------------- 已安裝偵測

VersionLookup = Callable[[str], Optional[str]]


def installed_version(dist: str) -> Optional[str]:
    from importlib import metadata

    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def requirement_status(spec: str, lookup: VersionLookup = installed_version) -> Tuple[str, Optional[str]]:
    """回傳 (狀態, 已安裝版本)。狀態：ok / missing / outdated / not-applicable。"""
    req = Requirement(spec)
    if req.marker is not None and not req.marker.evaluate():
        return "not-applicable", None
    ver = lookup(req.name)
    if ver is None:
        return "missing", None
    try:
        if req.specifier and not req.specifier.contains(Version(ver), prereleases=True):
            return "outdated", ver
    except InvalidVersion:
        return "outdated", ver
    return "ok", ver


def pip_spec(spec: str) -> str:
    """去掉平台標記，只留 名稱+版本條件 傳給 pip。"""
    req = Requirement(spec)
    return f"{req.name}{req.specifier}"


# ---------------------------------------------------------------- 安裝計畫

@dataclass
class ModulePlan:
    module: Module
    status: str  # install / satisfied / manual
    missing: List[Tuple[str, str, Optional[str]]] = field(default_factory=list)  # (spec, 狀態, 版本)
    satisfied: List[Tuple[str, Optional[str]]] = field(default_factory=list)


@dataclass
class Plan:
    items: List[ModulePlan]

    @property
    def pip_specs(self) -> List[str]:
        seen: Dict[str, str] = {}
        for item in self.items:
            for spec, _state, _ver in item.missing:
                name = Requirement(spec).name.lower()
                seen.setdefault(name, pip_spec(spec))
        return list(seen.values())

    @property
    def nothing_to_do(self) -> bool:
        return not self.pip_specs


def build_plan(order: Iterable[str], modules: Optional[Dict[str, Module]] = None,
               lookup: VersionLookup = installed_version, force: bool = False) -> Plan:
    mods = modules if modules is not None else catalog()
    items: List[ModulePlan] = []
    for mid in order:
        mod = mods[mid]
        if mod.manual:
            items.append(ModulePlan(mod, "manual"))
            continue
        plan = ModulePlan(mod, "satisfied")
        for spec in mod.packages:
            state, ver = requirement_status(spec, lookup)
            if state == "not-applicable":
                continue
            if state == "ok" and not force:
                plan.satisfied.append((spec, ver))
            else:
                plan.missing.append((spec, state if state != "ok" else "reinstall", ver))
        if plan.missing:
            plan.status = "install"
        items.append(plan)
    return Plan(items)
