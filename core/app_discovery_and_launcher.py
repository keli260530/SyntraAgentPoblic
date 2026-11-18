# -*- coding: utf-8 -*-
"""
本機應用程式自動探索、Google 預設權限判定、智慧啟動器與無障礙互動強化引擎
(Local App Discovery, Google-Default Permission Policy, Smart Launcher & UIA Enhancer)

解決兩大核心需求：
1. 自動掃描電腦中所有已安裝應用程式（桌面捷徑、開始選單、Windows 登錄檔 Uninstall 清單），
   提供給「設定 → 🔐 權限與功能 → 📱 AI 可使用的應用程式」以開關 (Switch/Checkbox) 方式呈現，
   且預設「全部關閉，除了 Google 相關應用程式預設開啟」。
2. 強化本機軟體啟動 (`launch_application`) 與視窗無障礙互動 (`inspect_accessibility_tree` / `ui_invoke` / `ui_type`)：
   - 支援直接以軟體名稱（如 `Gemini`）、桌面 `.lnk` 捷徑或含 `,0` 圖示索引的登錄檔路徑啟動本機軟體，不再誤退回網頁搜尋。
   - 針對 Electron / Chromium 桌面應用（如 Google Gemini 桌面版 `Gemini.exe`）自動喚醒無障礙樹、過濾空白 Group/Pane 容器節點，
     並支援點擊「新對話 / 發起新對話」、在輸入框貼上提示詞並按 Enter 送出、或點擊「建立筆記本 / Gem」等功能。
"""
from __future__ import annotations

import ctypes
import difflib
import logging
import os
import re
import struct
import subprocess
import time
import winreg
from typing import Any, Dict, List, Optional, Tuple

import psutil
import win32con
import win32gui
import win32process

from core.permissions import KNOWN_APPS

_ICON_INDEX_RE = re.compile(r',\s*-?\d+\s*$')

# 排除非使用者主動操作的系統底層元件、更新修補包或卸載器
_NOISE_NAME_PATTERNS = (
    "microsoft visual c++",
    "microsoft .net",
    "windows software development kit",
    "windows sdk",
    "msvc ",
    "redistributable",
    "click-to-run",
    "update for windows",
    "security update",
    "hotfix",
    "uninstall ",
    "解除安裝",
    "卸載",
    "crashpad",
    "auto updater",
    "webview2 runtime",
)

_GOOGLE_KEYWORDS = (
    "google",
    "chrome",
    "gemini",
)

# 快取本機掃描結果，避免頻繁重讀登錄檔
_SCAN_CACHE: List[Dict[str, Any]] = []
_SCAN_CACHE_TS: float = 0.0
_SCAN_CACHE_TTL: float = 45.0


def clean_executable_path(raw_path: str) -> str:
    """
    清理登錄檔 DisplayIcon 或指令列字串（例如 '"C:\\...\\Gemini.exe",0'），
    還原為真實存在的檔案路徑。
    """
    if not raw_path:
        return ""
    s = str(raw_path).strip()
    # 先移除尾端 ,0 或 ,-101 圖示索引
    s = _ICON_INDEX_RE.sub("", s).strip()
    s = s.strip('"').strip("'").strip()
    s = _ICON_INDEX_RE.sub("", s).strip().strip('"').strip("'")

    # 若包含參數（例如 "C:\path\app.exe" --arg），嘗試拆出 .exe/.lnk/.url
    if not os.path.exists(s):
        m = re.match(r'^([A-Za-z]:\\[^"]*?\.(?:exe|lnk|url|bat|cmd))\b', s, re.IGNORECASE)
        if m:
            s = m.group(1)

    return s


def resolve_lnk_target(lnk_path: str) -> str:
    """
    快速解析 Windows .lnk 捷徑指向的真實目標路徑（純二進位解析 + WScript 備援），
    避免在大量掃描時因 COM 初始化卡頓。
    """
    if not lnk_path or not os.path.isfile(lnk_path):
        return ""
    try:
        with open(lnk_path, "rb") as f:
            data = f.read(4096)
        # 尋找常見的本機磁碟路徑樣式 (ASCII 或 UTF-16LE)
        # 1. UTF-16LE
        utf16_matches = re.findall(
            rb'(?:[A-Za-z]\x00:\x00\\\x00)(?:[^\x00-\x1f]\x00){3,200}?\.(?:e\x00x\x00e\x00|l\x00n\x00k\x00)',
            data,
            flags=re.IGNORECASE,
        )
        for raw_m in utf16_matches:
            try:
                cand = raw_m.decode("utf-16le", errors="ignore").strip("\x00")
                if os.path.exists(cand):
                    return cand
            except Exception:
                pass
        # 2. ANSI / ASCII
        ascii_matches = re.findall(
            rb'[A-Za-z]:\\[^\x00-\x1f"<>|]{3,240}?\.(?:exe|lnk|bat|cmd)',
            data,
            flags=re.IGNORECASE,
        )
        for raw_m in ascii_matches:
            for enc in ("utf-8", "cp950", "mbcs"):
                try:
                    cand = raw_m.decode(enc, errors="ignore").strip()
                    if os.path.exists(cand):
                        return cand
                except Exception:
                    pass
    except Exception:
        pass
    return ""


def normalize_app_key(name: str, exe_path: str = "") -> str:
    """將軟體名稱或路徑正規化為唯一識別 key。"""
    raw_exe = (exe_path or "").strip()
    is_apps_folder = raw_exe.lower().startswith("shell:appsfolder\\")
    cleaned_path = "" if is_apps_folder else clean_executable_path(raw_exe or name)
    raw_name = (name or "").strip()
    if not raw_name.lower().startswith("shell:appsfolder\\") and (
        _ICON_INDEX_RE.search(raw_name) or raw_name.lower().endswith((".exe", ".lnk", ".url"))
    ):
        raw_name = clean_executable_path(raw_name)

    base = os.path.basename(cleaned_path) if cleaned_path else ""
    stem = os.path.splitext(base)[0].lower().strip() if base else ""
    name_low = os.path.splitext(os.path.basename(raw_name))[0].lower().strip()

    # 優先比對 KNOWN_APPS
    for k, (_disp, words) in KNOWN_APPS.items():
        if stem == k or name_low == k:
            return k
        for w in words:
            if len(w) <= 4:
                if stem == w or name_low == w:
                    return k
            else:
                if w in stem or w in name_low:
                    return k

    # Google Gemini 桌面應用程式特判
    if "gemini" in stem or "gemini" in name_low:
        return "gemini"
    if "chrome" in stem or "google chrome" in name_low:
        return "chrome"

    candidate = stem if (stem and stem not in ("app", "launcher", "update", "main", "start")) else name_low
    candidate = re.sub(r"\s+", "_", candidate).strip("_")
    return candidate or "unknown_app"


def is_google_application(
    key: str,
    name: str = "",
    publisher: str = "",
    exe_path: str = "",
) -> bool:
    """
    判斷是否為 Google 應用程式（如 Google Chrome、Google Gemini 桌面版、Google 雲端硬碟等）。
    依據使用者規範：所有掃描到的應用程式預設皆為關閉，唯獨 Google 相關應用程式預設開啟。
    """
    k_low = (key or "").lower().strip()
    n_low = (name or "").lower().strip()
    p_low = (publisher or "").lower().strip()
    e_low = (exe_path or "").lower().replace("/", "\\")

    if k_low in ("chrome", "google_chrome", "gemini", "google_gemini", "google_drive", "antigravity"):
        return True
    if any(kw in n_low for kw in ("google", "chrome", "gemini", "antigravity")):
        return True
    # 排除第三方網站透過 Chrome 安裝的 PWA (其 Publisher 會是 Google\Chrome，但名稱非 Google 服務)
    if p_low in ("google llc", "google inc.", "google") and not e_low.endswith(".ico"):
        return True
    if "\\google\\chrome\\application" in e_low or "\\google\\gemini\\" in e_low or "\\google\\drive" in e_low:
        return True
    return False


def _find_main_exe_in_dir(folder: str, app_name: str = "") -> str:
    """當登錄檔只有 InstallLocation 資料夾時，找出該資料夾內對應的主執行檔。"""
    if not folder or not os.path.isdir(folder):
        return ""
    try:
        exes = [
            f for f in os.listdir(folder)
            if f.lower().endswith(".exe")
            and not any(bad in f.lower() for bad in ("unins", "crashpad", "update", "setup", "helper"))
        ]
        if not exes:
            return ""
        app_low = (app_name or "").lower().replace(" ", "")
        for f in exes:
            f_stem = os.path.splitext(f)[0].lower().replace(" ", "")
            if app_low and (f_stem in app_low or app_low in f_stem):
                return os.path.join(folder, f)
        return os.path.join(folder, exes[0])
    except Exception:
        return ""


def scan_all_local_apps(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    全面掃描本機已安裝與桌面/開始選單應用程式，回傳結構化清單：
    [
        {
            "key": "gemini",
            "name": "Gemini",
            "publisher": "Google LLC",
            "version": "1.18.0",
            "source": "桌面捷徑 / 已安裝程式",
            "launch_target": "C:\\Users\\Tim\\AppData\\Local\\Google\\Gemini\\Gemini.exe",
            "shortcut_path": "C:\\Users\\Tim\\Desktop\\Gemini.lnk",
            "is_google": True,
        },
        ...
    ]
    """
    global _SCAN_CACHE, _SCAN_CACHE_TS
    now = time.time()
    if not force_refresh and _SCAN_CACHE and (now - _SCAN_CACHE_TS) < _SCAN_CACHE_TTL:
        return [dict(item) for item in _SCAN_CACHE]

    by_key: Dict[str, Dict[str, Any]] = {}

    def _upsert(
        name: str,
        raw_target: str,
        source: str,
        publisher: str = "",
        version: str = "",
        shortcut_path: str = "",
    ):
        clean_name = (name or "").strip()
        if not clean_name:
            return
        low_name = clean_name.lower()
        if any(pat in low_name for pat in _NOISE_NAME_PATTERNS):
            return
        if re.match(r"^kb\d{5,}", low_name):
            return

        cleaned_target = clean_executable_path(raw_target)
        if cleaned_target and os.path.isdir(cleaned_target):
            cleaned_target = _find_main_exe_in_dir(cleaned_target, clean_name) or cleaned_target

        # 排除純 .ico 檔作為啟動目標（除非有捷徑）
        if cleaned_target.lower().endswith(".ico") and not shortcut_path:
            cleaned_target = ""

        key = normalize_app_key(clean_name, cleaned_target or shortcut_path)
        if not key or key in ("python", "pythonw", "syntra"):
            return

        is_g = is_google_application(key, clean_name, publisher, cleaned_target or shortcut_path)

        existing = by_key.get(key)
        if not existing:
            by_key[key] = {
                "key": key,
                "name": clean_name,
                "publisher": publisher.strip(),
                "version": version.strip(),
                "source": source,
                "launch_target": cleaned_target or shortcut_path,
                "shortcut_path": shortcut_path,
                "is_google": is_g,
            }
        else:
            if is_g:
                existing["is_google"] = True
            if publisher and not existing.get("publisher"):
                existing["publisher"] = publisher.strip()
            if version and not existing.get("version"):
                existing["version"] = version.strip()
            if shortcut_path and not existing.get("shortcut_path"):
                existing["shortcut_path"] = shortcut_path
            if cleaned_target and (
                not existing.get("launch_target")
                or not os.path.exists(str(existing.get("launch_target", "")))
                or str(existing.get("launch_target", "")).lower().endswith(".ico")
            ):
                existing["launch_target"] = cleaned_target
            if source not in existing["source"]:
                existing["source"] = f"{existing['source']} / {source}"

    # 1. 掃描桌面圖示與工作列/開始釘選捷徑（含綠色免安裝軟體）
    desktop_dirs = [
        (os.path.expanduser("~/Desktop"), "桌面捷徑"),
        (os.path.expandvars(r"%PUBLIC%\Desktop"), "桌面捷徑"),
        (os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"), "工作列釘選"),
        (os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\StartMenu"), "開始釘選"),
        (os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch"), "快速啟動"),
    ]
    for d_dir, src_label in desktop_dirs:
        if not os.path.isdir(d_dir):
            continue
        try:
            for fname in os.listdir(d_dir):
                fpath = os.path.join(d_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                stem = os.path.splitext(fname)[0].strip()
                if ext == ".lnk":
                    resolved = resolve_lnk_target(fpath)
                    _upsert(
                        name=stem,
                        raw_target=resolved or fpath,
                        source=src_label,
                        shortcut_path=fpath,
                    )
                elif ext in (".exe", ".url"):
                    _upsert(
                        name=stem,
                        raw_target=fpath,
                        source=src_label,
                        shortcut_path=fpath,
                    )
        except Exception:
            pass

    # 2. 掃描開始選單捷徑（最多 2 層深度，速度快且涵蓋所有常用軟體）
    start_menu_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
    ]
    for sm_root in start_menu_dirs:
        if not os.path.isdir(sm_root):
            continue
        root_depth = sm_root.rstrip("\\/").count(os.sep)
        for r, dirs, files in os.walk(sm_root):
            if r.count(os.sep) - root_depth >= 2:
                dirs[:] = []
            for fname in files:
                if not fname.lower().endswith(".lnk"):
                    continue
                stem = os.path.splitext(fname)[0].strip()
                if any(bad in stem.lower() for bad in ("uninstall", "解除安裝", "readme", "help", "manual", "website")):
                    continue
                fpath = os.path.join(r, fname)
                resolved = resolve_lnk_target(fpath)
                _upsert(
                    name=stem,
                    raw_target=resolved or fpath,
                    source="開始選單",
                    shortcut_path=fpath,
                )

    # 3. 掃描 Windows 登錄檔 Uninstall 清單（如同 Windows 設定 → 應用程式 → 已安裝的應用程式）
    reg_roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, reg_path in reg_roots:
        try:
            with winreg.OpenKey(hive, reg_path) as k_root:
                sub_count = winreg.QueryInfoKey(k_root)[0]
        except Exception:
            continue
        for i in range(sub_count):
            try:
                with winreg.OpenKey(hive, reg_path) as k_root:
                    sub_name = winreg.EnumKey(k_root, i)
                with winreg.OpenKey(hive, f"{reg_path}\\{sub_name}") as sub:
                    def _q(val_name: str) -> str:
                        try:
                            v = winreg.QueryValueEx(sub, val_name)[0]
                            return str(v) if v is not None else ""
                        except Exception:
                            return ""

                    display_name = _q("DisplayName").strip()
                    if not display_name or _q("SystemComponent") == "1":
                        continue
                    publisher = _q("Publisher").strip()
                    version = _q("DisplayVersion").strip()
                    install_loc = _q("InstallLocation").strip()
                    display_icon = _q("DisplayIcon").strip()
                    raw_target = display_icon or install_loc
                    _upsert(
                        name=display_name,
                        raw_target=raw_target,
                        source="已安裝程式",
                        publisher=publisher,
                        version=version,
                    )
            except Exception:
                continue

    # 4. 掃描 Windows 開始功能表與 Microsoft Store / MSIX 應用程式 (Get-StartApps / shell:AppsFolder)
    #    優先於 App Paths，確保 Store App 正式入口不會被套件內的輔助工具覆蓋
    try:
        from core import app_launcher
        for sa in app_launcher.start_apps(refresh=force_refresh):
            sa_name = str(sa.get("name") or "").strip()
            sa_id = str(sa.get("app_id") or "").strip()
            if not sa_name or not sa_id:
                continue
            apps_folder_target = f"shell:AppsFolder\\{sa_id}"
            sa_source = "Microsoft Store" if ("!" in sa_id and "\\" not in sa_id) else "開始功能表 App"
            _upsert(name=sa_name, raw_target=apps_folder_target, source=sa_source)
    except Exception:
        pass

    # 5. 掃描 Windows 登錄檔 App Paths（許多桌面軟體只在此註冊 exe 路徑）
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        app_paths_root = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        try:
            with winreg.OpenKey(hive, app_paths_root) as k_root:
                sub_count = winreg.QueryInfoKey(k_root)[0]
        except Exception:
            continue
        for i in range(sub_count):
            try:
                with winreg.OpenKey(hive, app_paths_root) as k_root:
                    sub_name = winreg.EnumKey(k_root, i)
                with winreg.OpenKey(hive, f"{app_paths_root}\\{sub_name}") as sub:
                    exe_val = str(winreg.QueryValueEx(sub, "")[0] or "").strip()
                cleaned_exe = clean_executable_path(exe_val)
                if cleaned_exe and os.path.isfile(cleaned_exe):
                    low_exe = cleaned_exe.lower()
                    if "\\resources\\" in low_exe or any(
                        tok in os.path.basename(low_exe) for tok in ("helper", "updater", "crash", "make-")
                    ):
                        continue
                    stem = os.path.splitext(sub_name)[0].strip()
                    _upsert(name=stem, raw_target=cleaned_exe, source="App Paths")
            except Exception:
                continue

    # 5.5 掃描環境變數 PATH：只用來定位獨立桌面 GUI 軟體（Subsystem=2），不把整包 CLI/編譯器子工具拉進清單
    def _is_gui_pe(exe_fp: str) -> bool:
        try:
            with open(exe_fp, "rb") as f:
                if f.read(2) != b"MZ":
                    return False
                f.seek(0x3C)
                pe_off = int.from_bytes(f.read(4), "little")
                f.seek(pe_off)
                if f.read(4) != b"PE\x00\x00":
                    return False
                f.seek(pe_off + 24)
                magic = int.from_bytes(f.read(2), "little")
                if magic not in (0x10B, 0x20B):
                    return False
                f.seek(pe_off + 24 + 68)
                subsys = int.from_bytes(f.read(2), "little")
                return subsys == 2  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        except Exception:
            return False

    try:
        sys_win = os.path.expandvars(r"%WINDIR%").lower()
        cli_dir_hints = ("\\scripts", "\\mingw", "\\usr\\bin", "\\.cargo\\", "\\node_modules", "\\venv", "\\.venv", "\\python")
        for p_dir in (os.environ.get("PATH") or "").split(os.pathsep):
            p_clean = p_dir.strip().strip('"')
            if not p_clean or not os.path.isdir(p_clean):
                continue
            low_dir = p_clean.lower()
            if low_dir.startswith(sys_win) or any(h in low_dir for h in cli_dir_hints):
                continue
            try:
                gui_hits = []
                for fname in os.listdir(p_clean)[:60]:
                    if not fname.lower().endswith(".exe"):
                        continue
                    stem = os.path.splitext(fname)[0].strip()
                    if any(tok in stem.lower() for tok in ("unins", "setup", "install", "update", "crash", "helper", "daemon", "server", "cli")):
                        continue
                    full_exe = os.path.join(p_clean, fname)
                    if _is_gui_pe(full_exe):
                        gui_hits.append((stem, full_exe))
                for stem, full_exe in gui_hits[:2]:
                    _upsert(name=stem, raw_target=full_exe, source="環境變數 PATH")
            except Exception:
                continue
    except Exception:
        pass

    # 6. 補齊 Windows 內建核心工具（記事本、檔案總管、終端機）
    builtin_candidates = [
        ("notepad", "記事本 (Notepad)", "Microsoft Corporation", r"C:\Windows\System32\notepad.exe"),
        ("explorer", "檔案總管 (Explorer)", "Microsoft Corporation", r"C:\Windows\explorer.exe"),
        ("windowsterminal", "Windows 終端機 (PowerShell / CMD)", "Microsoft Corporation", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
    ]
    for b_key, b_name, b_pub, b_path in builtin_candidates:
        if b_key not in by_key and os.path.exists(b_path):
            by_key[b_key] = {
                "key": b_key,
                "name": b_name,
                "publisher": b_pub,
                "version": "",
                "source": "系統內建",
                "launch_target": b_path,
                "shortcut_path": "",
                "is_google": False,
            }

    # 排序：Google 應用優先排最上方，其餘依桌面捷徑優先、再依名稱排序
    def _sort_key(item: Dict[str, Any]):
        is_g = 0 if item.get("is_google") else 1
        has_desktop = 0 if "桌面" in str(item.get("source", "")) else 1
        return (is_g, has_desktop, str(item.get("name", "")).lower())

    results = sorted(by_key.values(), key=_sort_key)
    _SCAN_CACHE = [dict(r) for r in results]
    _SCAN_CACHE_TS = now
    return results


def default_google_allowed_apps() -> List[Dict[str, str]]:
    """
    回傳預設開啟的應用程式清單（僅限 Google 相關應用，其餘一律預設關閉）。
    """
    apps = scan_all_local_apps()
    allowed: List[Dict[str, str]] = []
    seen = set()
    for a in apps:
        if a.get("is_google"):
            k = a["key"]
            if k not in seen:
                seen.add(k)
                allowed.append({"key": k, "name": a["name"]})
    if "chrome" not in seen:
        allowed.append({"key": "chrome", "name": KNOWN_APPS["chrome"][0]})
    if "gemini" not in seen:
        allowed.append({"key": "gemini", "name": "Google Gemini"})
    return allowed


def compute_effective_allowed_apps(settings: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    計算目前生效的允許應用程式清單：
    - 若使用者尚未手動排除 Google 應用（不在 `denied` 清單中），則所有本機掃描到的 Google 應用（如 Chrome、Gemini）預設允許。
    - 非 Google 應用預設一律關閉，除非在使用者勾選開啟的 `allowed` 清單中。
    """
    perms = (settings or {}).get("permissions") or {}
    apps_sec = perms.get("apps") if isinstance(perms.get("apps"), dict) else {}
    saved_allowed = apps_sec.get("allowed")
    denied_keys = set(apps_sec.get("denied") or [])

    by_key: Dict[str, Dict[str, str]] = {}
    if isinstance(saved_allowed, list):
        for item in saved_allowed:
            if isinstance(item, dict) and item.get("key"):
                k = str(item["key"]).strip()
                if k and k not in denied_keys:
                    by_key[k] = {"key": k, "name": str(item.get("name") or k)}

    # 自動納入未曾被使用者手動關閉的 Google 應用程式（如 Google Chrome, Google Gemini）
    for g_app in default_google_allowed_apps():
        gk = g_app["key"]
        if gk not in denied_keys and gk not in by_key:
            by_key[gk] = dict(g_app)

    return list(by_key.values())


_QUERY_NOISE_RE = re.compile(
    r"(?:在電腦上|在本機上|在本機|電腦上|電腦裡|本機版|電腦版|桌面版|應用程式|軟體|程式|\bdesktop\b|\bapp\b|\bon my computer\b|\bon computer\b|\bon pc\b|\blocally\b)",
    re.IGNORECASE,
)


def _norm_search_text(s: str) -> str:
    return re.sub(r"[\s_\-\.()（）]+", "", (s or "").lower())


def _clean_app_query(query: str) -> str:
    q = (query or "").strip(" 「」『』\"'`")
    cleaned = _QUERY_NOISE_RE.sub(" ", q)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or q


def match_local_apps(query: str, max_items: int = 300, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    通用本機軟體搜尋引擎（不依賴寫死指南）：
    - 自動剝除「在電腦上 / 桌面版 / app」等修飾詞
    - 正規化空白與符號比對（如 'chat gpt' 命中 'ChatGPT'）
    - 多欄位搜尋（name / key / publisher / launch_target）與詞彙交集 + 模糊相似度排序
    """
    apps = scan_all_local_apps(force_refresh=force_refresh)
    raw_q = (query or "").strip()
    if not raw_q:
        return apps[: max(1, int(max_items or 300))]

    cleaned_q = _clean_app_query(raw_q)
    candidates = [cleaned_q] + ([raw_q] if raw_q.lower() != cleaned_q.lower() else [])

    def _score_app(app: Dict[str, Any]) -> Optional[Tuple[int, int, str]]:
        name = str(app.get("name") or "")
        key = str(app.get("key") or "")
        pub = str(app.get("publisher") or "")
        target = str(app.get("launch_target") or "")
        n_low = name.lower().strip()
        n_norm = _norm_search_text(name)
        k_norm = _norm_search_text(key)
        p_norm = _norm_search_text(pub)
        t_norm = _norm_search_text(os.path.basename(target))
        words = [w for w in re.split(r"[\s_\-\.()（）/\\]+", n_low) if w]

        best: Optional[Tuple[int, int, str]] = None
        for q_str in candidates:
            q_low = q_str.lower().strip()
            q_norm = _norm_search_text(q_str)
            q_tokens = [t for t in re.split(r"[\s_\-\.()（）/\\]+", q_low) if len(t) >= 2]
            if not q_norm:
                continue

            tier: Optional[int] = None
            if n_norm == q_norm or k_norm == q_norm:
                tier = 0
            elif q_low in words or any(w == q_norm for w in words):
                tier = 1
            elif n_norm.startswith(q_norm) or k_norm.startswith(q_norm):
                tier = 2
            elif q_norm in n_norm or q_norm in k_norm:
                tier = 3
            elif len(q_norm) >= 3 and (q_norm in t_norm or q_norm in p_norm):
                tier = 4
            elif q_tokens and any(tok in words or (len(tok) >= 3 and tok in n_norm) for tok in q_tokens):
                tier = 5
            elif len(q_norm) >= 3 and len(n_norm) >= 3:
                ratio = difflib.SequenceMatcher(None, q_norm, n_norm).ratio()
                if ratio >= 0.72:
                    tier = 6

            if tier is not None:
                cand_score = (tier, len(name), n_low)
                if best is None or cand_score < best:
                    best = cand_score
        return best

    ranked: List[Tuple[Tuple[int, int, str], Dict[str, Any]]] = []
    for app in apps:
        sc = _score_app(app)
        if sc is not None:
            ranked.append((sc, app))

    if not ranked and not force_refresh:
        return match_local_apps(query, max_items=max_items, force_refresh=True)

    ranked.sort(key=lambda pair: pair[0])
    return [app for _, app in ranked[: max(1, int(max_items or 300))]]


def resolve_app_launch_target(target: str) -> Optional[Dict[str, Any]]:
    """
    將 AI 傳入的軟體名稱（如 'Gemini', 'Google Gemini', 'VS Code', 'chat gpt'）、捷徑或帶 `,0` 的路徑，
    精準解析為本機可啟動的應用程式資訊字典。
    """
    raw = (target or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("shell:appsfolder\\"):
        return {
            "key": normalize_app_key(raw, raw),
            "name": raw,
            "launch_target": raw,
            "shortcut_path": "",
            "is_google": False,
        }

    cleaned = clean_executable_path(raw)
    if cleaned and os.path.isfile(cleaned):
        key = normalize_app_key(os.path.basename(cleaned), cleaned)
        return {
            "key": key,
            "name": os.path.splitext(os.path.basename(cleaned))[0],
            "launch_target": cleaned,
            "shortcut_path": cleaned if cleaned.lower().endswith(".lnk") else "",
            "is_google": is_google_application(key, cleaned, "", cleaned),
        }

    # 查桌面是否有同名 .lnk
    cleaned_name = _clean_app_query(raw)
    for cand_name in ([raw] if raw == cleaned_name else [cleaned_name, raw]):
        for d_dir in (os.path.expanduser("~/Desktop"), os.path.expandvars(r"%PUBLIC%\Desktop")):
            if os.path.isdir(d_dir):
                cand_lnk = os.path.join(d_dir, f"{cand_name}.lnk")
                if os.path.isfile(cand_lnk):
                    resolved = resolve_lnk_target(cand_lnk)
                    key = normalize_app_key(cand_name, resolved or cand_lnk)
                    return {
                        "key": key,
                        "name": cand_name,
                        "launch_target": resolved or cand_lnk,
                        "shortcut_path": cand_lnk,
                        "is_google": is_google_application(key, cand_name, "", resolved or cand_lnk),
                    }

    # 從本機完整掃描清單做通用模糊比對
    matched = match_local_apps(raw, max_items=1)
    if matched:
        return matched[0]
    return None


def wake_up_chromium_accessibility(hwnd: int) -> None:
    """
    針對 Electron / Chromium / WebView2 視窗（如 Gemini.exe、VS Code、Chrome），
    發送 WM_GETOBJECT 喚醒 Renderer 的無障礙樹 (AXTree)，確保 inspect_accessibility_tree
    第一次呼叫就能拿到完整的按鈕、對話框與連結節點。
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        return
    WM_GETOBJECT = 0x003D
    OBJID_CLIENT = -4
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            int(hwnd), WM_GETOBJECT, 0, OBJID_CLIENT, 0x0002, 150, ctypes.byref(ctypes.c_ulong(0))
        )
        # 同時喚醒內層 Chrome_RenderWidgetHostHWND 子視窗
        def _child_cb(child_hwnd, _):
            try:
                cls_name = win32gui.GetClassName(child_hwnd) or ""
                if "Chrome_RenderWidgetHostHWND" in cls_name or "Chrome_WidgetWin" in cls_name or "Intermediate" in cls_name:
                    ctypes.windll.user32.SendMessageTimeoutW(
                        int(child_hwnd), WM_GETOBJECT, 0, OBJID_CLIENT, 0x0002, 150, ctypes.byref(ctypes.c_ulong(0))
                    )
            except Exception:
                pass
            return True

        try:
            win32gui.EnumChildWindows(int(hwnd), _child_cb, None)
        except Exception:
            pass
    except Exception:
        pass


def _is_dnd_background_only(desktop_ctrl: Any) -> bool:
    """免打擾（手動 DND / 遊戲 / 觀影）啟動時，任務照常執行但禁止搶奪或佔用前端畫面。"""
    cg = getattr(desktop_ctrl, "context_guard", None) if desktop_ctrl is not None else None
    if cg is None:
        return False
    fn = getattr(cg, "is_dnd_active", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    try:
        state = cg.evaluate_state()
        return state.get("mode") in ("MANUAL_DND", "GAMING", "VIDEO")
    except Exception:
        return False


def bring_window_to_front(hwnd: int) -> bool:
    """安全地將指定視窗還原（若最小化）並帶到前景。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.15)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # 藉由 AttachThreadInput 或 Alt 鍵解除 Windows ForegroundLockTimeout 限制
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd:
                fg_tid, _ = win32process.GetWindowThreadProcessId(fg_hwnd)
                target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
                if fg_tid != target_tid:
                    ctypes.windll.user32.AttachThreadInput(fg_tid, target_tid, True)
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                        win32gui.BringWindowToTop(hwnd)
                    finally:
                        ctypes.windll.user32.AttachThreadInput(fg_tid, target_tid, False)
        return True
    except Exception:
        return False


def find_matching_open_window(desktop_ctrl: Any, app_info: Dict[str, Any], raw_target: str) -> Optional[Dict[str, Any]]:
    """在目前開啟的桌面視窗中尋找屬於該應用程式的主視窗。"""
    key = (app_info.get("key") or "").lower()
    name_low = (app_info.get("name") or raw_target or "").lower()
    exe_path = str(app_info.get("launch_target") or "")
    exe_base = os.path.basename(exe_path).lower() if exe_path else ""
    exe_stem = os.path.splitext(exe_base)[0].lower() if exe_base else ""

    for w in desktop_ctrl.list_open_windows():
        if w.get("hwnd", 0) == 0:
            continue
        t_low = (w.get("title") or "").lower()
        p_low = (w.get("process_name") or "").lower()
        # 排除 Syntra 自身視窗
        if "syntra" in t_low or p_low in ("python.exe", "pythonw.exe"):
            continue
        if exe_base and p_low == exe_base:
            return w
        if exe_stem and len(exe_stem) >= 3 and (exe_stem in p_low or exe_stem in t_low):
            return w
        if key and len(key) >= 3 and (key in p_low or key in t_low):
            return w
        if name_low and len(name_low) >= 3 and name_low in t_low:
            return w
    return None


def smart_launch_application(desktop_ctrl: Any, target: str) -> Dict[str, Any]:
    """
    強化版 `DesktopController.launch_application`：
    1. 自動解析軟體名稱（如 `Gemini`）、桌面捷徑 (`C:\\Users\\Tim\\Desktop\\Gemini.lnk`) 或含 `,0` 的登錄檔路徑。
    2. 對於 Electron / Chromium 應用（如 `Gemini.exe`），自動附加 `--force-renderer-accessibility` 啟動，
       確保無障礙元件樹 100% 暴露。
    3. 啟動後自動等待視窗出現（最長 3.5 秒）、喚醒並置於前景，直接回傳 `hwnd` 與視窗標題，
       讓 AI 下一步能直接對該 `hwnd` 執行 `inspect_accessibility_tree`、`ui_invoke`（點新對話/建筆記本）或 `ui_type`（輸入提示詞）！
    """
    raw = (target or "").strip()
    if not raw:
        return {"ok": False, "error": "未指定要開啟的軟體名稱或路徑。"}

    app_info = resolve_app_launch_target(raw)
    launch_path = ""
    shortcut_path = ""
    if app_info:
        launch_path = str(app_info.get("launch_target") or "").strip()
        shortcut_path = str(app_info.get("shortcut_path") or "").strip()
    else:
        launch_path = clean_executable_path(raw)
        app_info = {"key": normalize_app_key(raw, launch_path), "name": raw, "launch_target": launch_path}

    # 選擇實際要執行的路徑（優先使用真實 .exe 以便傳入 --force-renderer-accessibility，否則使用 .lnk 或 shell:AppsFolder）
    actual_exec = ""
    is_apps_folder = launch_path.lower().startswith("shell:appsfolder\\")
    if is_apps_folder:
        actual_exec = launch_path
    elif launch_path and os.path.exists(launch_path):
        actual_exec = launch_path
    elif shortcut_path and os.path.exists(shortcut_path):
        actual_exec = shortcut_path
    else:
        actual_exec = clean_executable_path(raw)

    # 解析不到實際檔案（Microsoft Store 版軟體如 ChatGPT、Claude 沒有可直接執行的 exe 路徑）
    # → 直接透過 explorer.exe shell:AppsFolder\<AppID> 或 app_launcher 啟動
    via_start_menu = False
    if is_apps_folder:
        try:
            subprocess.Popen(
                ["explorer.exe", actual_exec],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            via_start_menu = True
        except Exception as e:
            return {"ok": False, "error": f"無法開啟「{raw}」（{actual_exec}）：{e}"}
    elif not (actual_exec and os.path.exists(actual_exec)):
        try:
            from core import app_launcher
            reg_fn = getattr(desktop_ctrl, "_registry_software", None)
            res = app_launcher.launch(_clean_app_query(raw), reg_fn() if callable(reg_fn) else [])
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": f"無法開啟「{raw}」：{e}"}
        if not res.get("ok"):
            return res
        via_start_menu = True
        app_info = dict(app_info, name=str(res.get("launched") or app_info.get("name") or raw))

    try:
        if via_start_menu:
            pass
        elif actual_exec.lower().endswith(".exe") and os.path.isfile(actual_exec):
            # 附加 --force-renderer-accessibility 讓 Electron/Chromium 應用程式完整開放 UIA 節點樹（對一般原生程式亦無副作用或自動忽略）
            exe_dir = os.path.dirname(actual_exec) or None
            is_chromium_like = False
            if exe_dir and os.path.isdir(exe_dir):
                try:
                    dir_files = [f.lower() for f in os.listdir(exe_dir)]
                    if any("chrome" in f or "resources" in f or f.startswith("app-") for f in dir_files):
                        is_chromium_like = True
                except Exception:
                    pass
            if is_chromium_like or app_info.get("key") in ("gemini", "chrome", "msedge", "code", "cursor", "antigravity", "discord"):
                subprocess.Popen(
                    [actual_exec, "--force-renderer-accessibility"],
                    cwd=exe_dir,
                    close_fds=True,
                )
            else:
                os.startfile(actual_exec)
        else:
            os.startfile(actual_exec)
    except Exception as e:
        # 若直接開啟 .exe 失敗但有桌面捷徑，退回開啟 .lnk
        if shortcut_path and os.path.exists(shortcut_path) and shortcut_path != actual_exec:
            try:
                os.startfile(shortcut_path)
                actual_exec = shortcut_path
            except Exception as e2:
                return {"ok": False, "error": f"無法開啟「{raw}」（解析路徑：{actual_exec}）：{e2}"}
        else:
            return {"ok": False, "error": f"無法開啟「{raw}」（解析路徑：{actual_exec}）：{e}"}

    # 等待視窗出現並置於前景（最長輪詢 3.5 秒）
    matched_win = None
    deadline = time.time() + (8.0 if via_start_menu else 3.5)  # Store App 啟動比較慢
    while time.time() < deadline:
        matched_win = find_matching_open_window(desktop_ctrl, app_info, raw)
        if matched_win and matched_win.get("hwnd"):
            break
        time.sleep(0.25)

    result: Dict[str, Any] = {
        "ok": True,
        "launched": raw,
        "resolved_name": app_info.get("name", raw),
        "resolved_path": actual_exec,
        "app_key": app_info.get("key", ""),
    }

    dnd_bg = _is_dnd_background_only(desktop_ctrl)
    if matched_win and matched_win.get("hwnd"):
        hwnd = int(matched_win["hwnd"])
        if dnd_bg:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWMINNOACTIVE)
            except Exception:
                pass
            result["background_mode"] = True
        else:
            bring_window_to_front(hwnd)
        wake_up_chromium_accessibility(hwnd)
        result["hwnd"] = hwnd
        result["window_title"] = matched_win.get("title", "")
        result["process_name"] = matched_win.get("process_name", "")
        if dnd_bg:
            result["next_step_hint"] = (
                f"已在背景開啟「{matched_win.get('title')}」(hwnd={hwnd})，未佔用前端畫面。"
                f"請用 inspect_accessibility_tree(hwnd={hwnd}) 與支援背景的 UIA（ui_invoke / ui_type）或背景工具繼續處理，切勿搶奪前景焦點。"
            )
        else:
            result["next_step_hint"] = (
                f"已成功開啟並聚焦視窗「{matched_win.get('title')}」(hwnd={hwnd})。"
                f"請直接呼叫 inspect_accessibility_tree(hwnd={hwnd}) 取得畫面上的「新對話 / 輸入框 / 建立筆記本」等元件 ID，"
                f"接著用 ui_invoke 點擊按鈕或用 ui_type 輸入提示詞（可設 press_enter=True 直接送出），切勿改用 web_search！"
                f"如果是要在文件／試算表裡輸入內容（Word、Excel、記事本…），直接呼叫 type_in_app 即可，不必先讀結構樹；"
                f"使用者的要求還沒做完就繼續做，不要停下來叫使用者再說一次。"
            )
    else:
        result["next_step_hint"] = (
            "應用程式已啟動中，請呼叫 list_windows 取得其 hwnd，再透過 inspect_accessibility_tree、ui_invoke 與 ui_type 操作。"
        )

    return result


# ===========================================================================
# 無障礙樹與本機視窗互動強化（針對 Electron / Chromium / Gemini.exe 等現代應用）
# ===========================================================================
_SYNONYM_GROUPS = [
    ("新對話", "新的對話", "發起新對話", "開啟新對話", "新增對話", "new chat", "new conversation", "start new chat"),
    ("筆記本", "建立筆記本", "新增筆記本", "notebook", "create notebook", "gem", "gems", "建立 gem", "探索 gem", "explore gems"),
    ("輸入", "輸入提示", "在這裡輸入提示", "詢問 gemini", "輸入訊息", "搜尋", "ask gemini", "enter a prompt", "prompt", "message"),
    ("傳送", "送出", "提交", "send", "submit"),
]


def _expand_query_synonyms(query: str) -> List[str]:
    q_low = (query or "").strip().lower()
    if not q_low:
        return []
    expanded = [q_low]
    for grp in _SYNONYM_GROUPS:
        if any(term in q_low or q_low in term for term in grp):
            for term in grp:
                if term not in expanded:
                    expanded.append(term)
    return expanded


def find_best_node(cached_nodes: Dict[str, Any], query: str, prefer_input: bool = False) -> Optional[Any]:
    """支援以 #id、名稱或語意同義詞（如『新的對話』<->『發起新對話』/『New chat』）查找無障礙節點。"""
    clean = (query or "").strip()
    if not clean and not prefer_input:
        return None

    if clean:
        norm_id = f"#{clean}" if clean.isdigit() else clean
        if norm_id in cached_nodes:
            return cached_nodes[norm_id]

    candidates = _expand_query_synonyms(clean)
    # 1. 完全相等比對
    for cand in candidates:
        for n in cached_nodes.values():
            if n.name.lower() == cand or n.automation_id.lower() == cand:
                return n

    # 2. 包含比對（優先挑選 Button / Edit / Hyperlink / MenuItem 等互動控制項）
    interactive_types = {"Button", "Edit", "Document", "Hyperlink", "MenuItem", "TabItem", "ListItem", "CheckBox", "ComboBox"}
    for cand in candidates:
        for n in cached_nodes.values():
            if n.control_type in interactive_types and (cand in n.name.lower() or cand in n.automation_id.lower()):
                return n
        for n in cached_nodes.values():
            if cand in n.name.lower() or cand in n.automation_id.lower():
                return n

    # 3. 若為輸入動作 (prefer_input=True)，自動尋找畫面上的主要 Edit / Document 輸入框
    if prefer_input:
        for n in cached_nodes.values():
            if n.control_type == "Edit" and n.is_enabled:
                return n
        for n in cached_nodes.values():
            if n.control_type in ("Document", "Edit", "Group", "Pane") and (
                "Value" in (n.supported_patterns or [])
                or any(k in n.name.lower() for k in ("輸入", "提示", "詢問", "搜尋", "ask", "prompt", "search", "message"))
            ):
                return n
        for n in cached_nodes.values():
            if n.control_type == "Document" and n.is_enabled:
                return n

    return None


def enhanced_dump_window_tree(
    engine: Any,
    hwnd: int = 0,
    max_depth: int = 12,
    max_nodes: int = 120,
) -> Tuple[str, Dict[str, Any]]:
    """
    強化版無障礙結構樹掃描：
    1. 針對 Electron/Chromium 視窗先發送 WM_GETOBJECT 喚醒無障礙樹。
    2. 過濾無名稱的空白 Group / Pane 容器，且空白容器不消耗邏輯深度 (depth)，
       確保能穿透 10+ 層 DOM 容器抓到內層的「發起新對話」、「輸入提示詞」、「建立 Gem / 筆記本」等真實按鈕。
    3. 於樹狀圖頂部附上「🔥 可互動元件快速索引」，讓 AI 一眼看到按鈕與輸入框 ID。
    """
    from core.accessibility_engine import UIA_AVAILABLE, AccessibilityNode
    if not UIA_AVAILABLE:
        return "系統未就緒：缺少 uiautomation 函式庫支援。", {}

    import uiautomation as auto

    eff_depth = max(int(max_depth or 12), 12)
    eff_max_nodes = max(int(max_nodes or 120), 120)

    engine._cached_nodes.clear()
    engine._last_hwnd = hwnd

    with engine.com_initialized():
        try:
            target_hwnd = int(hwnd or 0)
            if target_hwnd != 0 and win32gui.IsWindow(target_hwnd):
                wake_up_chromium_accessibility(target_hwnd)
                win_title = (win32gui.GetWindowText(target_hwnd) or "視窗").strip()
                root_ctrl = auto.ControlFromHandle(target_hwnd)
            else:
                fg_hwnd = win32gui.GetForegroundWindow()
                if fg_hwnd and win32gui.IsWindow(fg_hwnd):
                    target_hwnd = int(fg_hwnd)
                    engine._last_hwnd = target_hwnd
                    wake_up_chromium_accessibility(target_hwnd)
                    root_ctrl = auto.ControlFromHandle(target_hwnd)
                    win_title = (win32gui.GetWindowText(target_hwnd) or "前景視窗").strip()
                else:
                    win_title = "目前焦點視窗 / 全螢幕"
                    root_ctrl = auto.GetFocusedControl() or auto.GetRootControl()

            if not root_ctrl:
                return f"無法取得視窗 (HWND: {target_hwnd}) 的無障礙控制項物件。", {}

            node_counter = [0]
            nodes_dict: Dict[str, AccessibilityNode] = {}
            tree_lines: List[str] = []

            # 核心互動控制項（不含空白 Group/Pane，避免淹沒真實按鈕）
            core_interactive_types = {
                "Button", "Edit", "Document", "Text", "CheckBox", "RadioButton",
                "ComboBox", "MenuItem", "TabItem", "TreeItem", "ListItem",
                "Hyperlink", "Slider", "ToolBar",
            }

            def _traverse(ctrl: Any, logical_depth: int, raw_depth: int):
                if node_counter[0] >= eff_max_nodes or logical_depth > eff_depth or raw_depth > 28:
                    return
                try:
                    c_type = ctrl.ControlTypeName or "Unknown"
                    if c_type.endswith("Control"):
                        c_type = c_type[:-7]
                    name = (ctrl.Name or "").strip()
                    rect = ctrl.BoundingRectangle
                    w = rect.width() if hasattr(rect, "width") else (rect[2] - rect[0] if len(rect) >= 4 else 0)
                    h = rect.height() if hasattr(rect, "height") else (rect[3] - rect[1] if len(rect) >= 4 else 0)
                    if w <= 0 or h <= 0:
                        return

                    patterns = []
                    val = ""
                    try:
                        if hasattr(ctrl, "GetValuePattern") and ctrl.GetValuePattern():
                            val = (ctrl.GetValuePattern().Value or "").strip()
                            patterns.append("Value")
                    except Exception:
                        pass
                    if not val:
                        try:
                            if hasattr(ctrl, "GetLegacyIAccessiblePattern") and ctrl.GetLegacyIAccessiblePattern():
                                val = (ctrl.GetLegacyIAccessiblePattern().Value or "").strip()
                        except Exception:
                            pass
                    try:
                        if hasattr(ctrl, "GetInvokePattern") and ctrl.GetInvokePattern():
                            patterns.append("Invoke")
                    except Exception:
                        pass
                    try:
                        if hasattr(ctrl, "GetTogglePattern") and ctrl.GetTogglePattern():
                            patterns.append("Toggle")
                    except Exception:
                        pass

                    auto_id = ""
                    try:
                        auto_id = (ctrl.AutomationId or "").strip()
                    except Exception:
                        pass

                    is_focused = False
                    try:
                        is_focused = bool(ctrl.HasKeyboardFocus)
                    except Exception:
                        pass

                    is_enabled = True
                    try:
                        is_enabled = bool(ctrl.IsEnabled)
                    except Exception:
                        pass

                    rect_tuple = (
                        (rect.left, rect.top, rect.right, rect.bottom)
                        if hasattr(rect, "left")
                        else (rect[0], rect[1], rect[2], rect[3])
                    )

                    # 判斷是否為有意義的控制項（排除無名無值的空白 Group/Pane/Custom 容器）
                    is_empty_container = c_type in ("Group", "Pane", "Custom", "Window") and not name and not val and not patterns and not is_focused
                    is_significant = (
                        not is_empty_container
                        and (
                            c_type in core_interactive_types
                            or bool(name)
                            or bool(val)
                            or bool(patterns)
                            or is_focused
                        )
                    )

                    if is_significant or raw_depth == 0:
                        node_counter[0] += 1
                        node_id = f"#{node_counter[0]}"
                        node = AccessibilityNode(
                            node_id=node_id,
                            name=name,
                            control_type=c_type,
                            automation_id=auto_id,
                            rect=rect_tuple,
                            value=val,
                            is_enabled=is_enabled,
                            is_visible=True,
                            is_focused=is_focused,
                            supported_patterns=patterns,
                            raw_control=ctrl,
                        )
                        nodes_dict[node_id] = node
                        tree_lines.append(node.format_line(indent=min(logical_depth, 8)))

                    next_logical = logical_depth if is_empty_container else (logical_depth + 1)
                    for child in ctrl.GetChildren():
                        if node_counter[0] >= eff_max_nodes:
                            break
                        _traverse(child, next_logical, raw_depth + 1)
                except Exception:
                    pass

            _traverse(root_ctrl, 0, 0)
            engine._cached_nodes = nodes_dict

            header_lines: List[str] = [
                "=== 視窗無障礙語意樹 (Accessibility UI Tree) ===",
                f"目標視窗: {win_title} (HWND: {target_hwnd})",
                "說明: 括號前標籤如 [#1], [#2] 為元素 ID，可直接調用 ui_invoke 點擊或 ui_type 輸入文字（支援 press_enter=True 直接送出）。",
            ]

            # 整理關鍵互動元件快速摘要（按鈕、輸入框、連結）
            highlights = [
                n for n in nodes_dict.values()
                if n.control_type in ("Button", "Edit", "Document", "Hyperlink", "MenuItem", "TabItem")
                and (n.name or n.control_type in ("Edit", "Document"))
            ]
            if highlights:
                header_lines.append("🔥 關鍵可互動元件快速索引:")
                for hn in highlights[:25]:
                    header_lines.append(f"  * [{hn.node_id}] {hn.control_type}: '{hn.name or '(輸入區域)'}' pos={hn.center_point}")

            header_lines.append("--------------------------------------------------")
            if len(nodes_dict) <= 1:
                tree_lines.append(
                    "(提示：若此視窗為 Electron/Chromium 應用且僅顯示頂層視窗，請直接呼叫 ui_type(element_id='input', text='...', press_enter=True) "
                    "或使用 inspect_window_background / capture_desktop_screen 輔助定位)"
                )

            full_text = "\n".join(header_lines + tree_lines)
            return full_text, {k: v.to_dict() for k, v in nodes_dict.items()}
        except Exception as e:
            return f"讀取無障礙結構樹失敗：{str(e)}", {}


def enhanced_invoke_element_by_id(engine: Any, element_id: str, desktop_ctrl: Any = None) -> Dict[str, Any]:
    """
    強化版 `ui_invoke`：
    1. 支援 `#id` 或按鈕文字/同義詞（例如 `"新的對話"`、`"發起新對話"`、`"New chat"`、`"建立 Gem"`、`"筆記本"`）。
    2. 優先嘗試原生 InvokePattern / TogglePattern / SelectionItemPattern / LegacyIAccessible.DoDefaultAction。
    3. 若為 Electron/Web 自訂元件無原生 Pattern，自動喚醒目標視窗並精準點擊該元件幾何中心 `(cx, cy)`。
    4. 若在 Gemini 等應用中指定 `"新的對話"` / `"New chat"` 但無對應無障礙節點，支援自動發送 `Ctrl+Shift+O` 快捷鍵開啟新對話。
    """
    node = find_best_node(engine._cached_nodes, element_id, prefer_input=False)
    target_hwnd = getattr(engine, "_last_hwnd", 0)

    if not node:
        # 針對「新對話 / New chat」提供智慧快捷鍵備援（Gemini / ChatGPT / Claude 桌面版通用 Ctrl+Shift+O 或 Ctrl+N）
        q_low = (element_id or "").strip().lower()
        if any(k in q_low for k in ("新對話", "新的對話", "new chat", "new conversation")) and target_hwnd and desktop_ctrl:
            bring_window_to_front(target_hwnd)
            time.sleep(0.15)
            try:
                from pynput.keyboard import Key
                with desktop_ctrl.keyboard.pressed(Key.ctrl):
                    with desktop_ctrl.keyboard.pressed(Key.shift):
                        desktop_ctrl.keyboard.press("o")
                        desktop_ctrl.keyboard.release("o")
                return {
                    "ok": True,
                    "action": "hotkey_new_chat",
                    "hwnd": target_hwnd,
                    "message": "已喚醒視窗並透過快捷鍵 (Ctrl+Shift+O) 觸發「開啟新對話」！",
                }
            except Exception:
                pass
        return {
            "ok": False,
            "error": f"找不到無障礙元素：[{element_id}]，請先執行 inspect_accessibility_tree 更新元件清單，或改傳入樹狀圖上的 #ID / 按鈕名稱。",
        }

    ctrl = node.raw_control
    with engine.com_initialized():
        if ctrl:
            try:
                invoke_pat = ctrl.GetInvokePattern()
                if invoke_pat:
                    invoke_pat.Invoke()
                    return {
                        "ok": True,
                        "action": "native_invoke",
                        "element_id": node.node_id,
                        "name": node.name,
                        "type": node.control_type,
                        "message": f"已成功觸發 [{node.name or node.control_type}]！",
                    }
            except Exception:
                pass

            try:
                toggle_pat = ctrl.GetTogglePattern()
                if toggle_pat:
                    toggle_pat.Toggle()
                    return {
                        "ok": True,
                        "action": "native_toggle",
                        "element_id": node.node_id,
                        "name": node.name,
                        "type": node.control_type,
                        "message": f"已成功切換 [{node.name or node.control_type}] 狀態！",
                    }
            except Exception:
                pass

            try:
                sel_pat = ctrl.GetSelectionItemPattern()
                if sel_pat:
                    sel_pat.Select()
                    return {
                        "ok": True,
                        "action": "native_select",
                        "element_id": node.node_id,
                        "name": node.name,
                        "type": node.control_type,
                        "message": f"已成功選中 [{node.name or node.control_type}]！",
                    }
            except Exception:
                pass

            try:
                if hasattr(ctrl, "GetLegacyIAccessiblePattern"):
                    leg = ctrl.GetLegacyIAccessiblePattern()
                    if leg:
                        leg.DoDefaultAction()
                        return {
                            "ok": True,
                            "action": "legacy_default_action",
                            "element_id": node.node_id,
                            "name": node.name,
                            "type": node.control_type,
                            "message": f"已成功透過 LegacyIAccessible 觸發 [{node.name or node.control_type}]！",
                        }
            except Exception:
                pass

        # 座標點擊備援：免打擾模式下不搶奪前景
        if _is_dnd_background_only(desktop_ctrl):
            return {
                "ok": False,
                "deferred_by_dnd": True,
                "message": "目前處於免打擾背景模式，該元件沒有支援背景觸發的 UIA Pattern，已避免搶奪前端畫面。",
            }
        cx, cy = node.center_point
        if target_hwnd:
            bring_window_to_front(target_hwnd)
            time.sleep(0.1)
        try:
            if ctrl:
                ctrl.Click(simulateMove=False)
            elif desktop_ctrl:
                from pynput.mouse import Button
                desktop_ctrl.move_mouse_humanlike(cx, cy, duration=0.15)
                desktop_ctrl.mouse.click(Button.left, 1)
            return {
                "ok": True,
                "action": "uia_center_click",
                "element_id": node.node_id,
                "name": node.name,
                "coords": (cx, cy),
                "message": f"已聚焦視窗並精準點擊 [{node.name or node.control_type}] 中心座標 ({cx}, {cy})。",
            }
        except Exception as e:
            return {"ok": False, "error": f"觸發元件失敗：{str(e)}"}


def enhanced_set_element_value_by_id(
    engine: Any,
    element_id: str,
    value: str,
    press_enter: bool = False,
    desktop_ctrl: Any = None,
) -> Dict[str, Any]:
    """
    強化版 `ui_type`：
    1. 支援 `#id`、輸入框名稱，或當傳入通用名稱（如 `'input'`、`'提示詞'`）時自動定位畫面上的主輸入框。
    2. 針對 Electron / Chromium 富文本輸入框（如 Gemini 的 contenteditable 提示詞輸入區）：
       若原生 ValuePattern 不支援或為現代網頁容器，自動將視窗帶到前景、點擊輸入框中心聚焦、
       透過剪貼簿無損貼上中英文提示詞（保留原剪貼簿），並支援 `press_enter=True` 直接送出查詢！
    """
    node = find_best_node(engine._cached_nodes, element_id, prefer_input=True)
    target_hwnd = getattr(engine, "_last_hwnd", 0)

    if not node:
        if _is_dnd_background_only(desktop_ctrl):
            return {
                "ok": False,
                "deferred_by_dnd": True,
                "message": "目前處於免打擾背景模式，找不到可背景寫入的 UIA 輸入框，已避免搶奪前端畫面。",
            }
        # 若無障礙樹尚未快取到節點，但有目標視窗與 desktop_ctrl，針對視窗底部中央輸入區聚焦並貼上（適用於 Gemini 等現代對話視窗）
        if target_hwnd and win32gui.IsWindow(target_hwnd) and desktop_ctrl:
            bring_window_to_front(target_hwnd)
            time.sleep(0.15)
            try:
                rect = win32gui.GetWindowRect(target_hwnd)
                w = rect[2] - rect[0]
                h = rect[3] - rect[1]
                # 對話型應用輸入框通常位於視窗水平中央、垂直約 82% 處
                cx = rect[0] + int(w * 0.52)
                cy = rect[1] + int(h * 0.82)
                from pynput.mouse import Button
                from pynput.keyboard import Key
                desktop_ctrl.move_mouse_humanlike(cx, cy, duration=0.15)
                desktop_ctrl.mouse.click(Button.left, 1)
                time.sleep(0.12)
                desktop_ctrl._paste_text_preserving_clipboard(value)
                if press_enter:
                    time.sleep(0.15)
                    desktop_ctrl.keyboard.press(Key.enter)
                    desktop_ctrl.keyboard.release(Key.enter)
                return {
                    "ok": True,
                    "action": "window_input_paste_fallback",
                    "hwnd": target_hwnd,
                    "coords": (cx, cy),
                    "value_set": value,
                    "press_enter": press_enter,
                    "message": f"已聚焦視窗輸入區 ({cx}, {cy}) 並貼上文字" + ("且按 Enter 送出！" if press_enter else "！"),
                }
            except Exception as e:
                return {"ok": False, "error": f"找不到無障礙元素 [{element_id}] 且視窗貼上備援失敗：{e}"}
        return {"ok": False, "error": f"找不到無障礙元素：[{element_id}]，請先執行 inspect_accessibility_tree。"}

    ctrl = node.raw_control
    is_web_or_doc = node.control_type in ("Document", "Group", "Pane", "Custom")
    if target_hwnd and win32gui.IsWindow(target_hwnd):
        try:
            cls_name = win32gui.GetClassName(target_hwnd) or ""
            if "Chrome_WidgetWin" in cls_name:
                is_web_or_doc = True
        except Exception:
            pass

    with engine.com_initialized():
        # 1. 對原生標準 Edit 控制項（非 Chromium 富文本），優先嘗試 ValuePattern
        if ctrl and not is_web_or_doc:
            try:
                val_pat = ctrl.GetValuePattern()
                if val_pat:
                    val_pat.SetValue(value)
                    if press_enter:
                        try:
                            ctrl.SetFocus()
                            time.sleep(0.05)
                            ctrl.SendKeys("{Enter}")
                        except Exception:
                            pass
                    return {
                        "ok": True,
                        "action": "native_set_value",
                        "element_id": node.node_id,
                        "name": node.name,
                        "value_set": value,
                        "press_enter": press_enter,
                        "message": f"已透過原生 ValuePattern 寫入文字至 [{node.name or node.control_type}]" + ("並送出！" if press_enter else "！"),
                    }
            except Exception:
                pass

        # 2. 針對 Electron / Chromium (如 Gemini.exe) 或無 ValuePattern 的輸入框：
        #    喚醒視窗 -> 點擊該元素座標聚焦 -> 剪貼簿無損貼上 -> (可選) 按 Enter 送出
        if desktop_ctrl is not None:
            if _is_dnd_background_only(desktop_ctrl):
                return {
                    "ok": False,
                    "deferred_by_dnd": True,
                    "message": "目前處於免打擾背景模式，該輸入框需前景點擊貼上，已避免搶奪前端畫面。",
                }
            try:
                if target_hwnd:
                    bring_window_to_front(target_hwnd)
                    time.sleep(0.12)
                cx, cy = node.center_point
                if ctrl:
                    try:
                        ctrl.SetFocus()
                    except Exception:
                        pass
                    try:
                        ctrl.Click(simulateMove=False)
                    except Exception:
                        from pynput.mouse import Button
                        desktop_ctrl.move_mouse_humanlike(cx, cy, duration=0.15)
                        desktop_ctrl.mouse.click(Button.left, 1)
                else:
                    from pynput.mouse import Button
                    desktop_ctrl.move_mouse_humanlike(cx, cy, duration=0.15)
                    desktop_ctrl.mouse.click(Button.left, 1)

                time.sleep(0.1)
                desktop_ctrl._paste_text_preserving_clipboard(value)
                if press_enter:
                    from pynput.keyboard import Key
                    time.sleep(0.15)
                    desktop_ctrl.keyboard.press(Key.enter)
                    desktop_ctrl.keyboard.release(Key.enter)

                return {
                    "ok": True,
                    "action": "clipboard_focus_paste",
                    "element_id": node.node_id,
                    "name": node.name,
                    "coords": (cx, cy),
                    "value_set": value,
                    "press_enter": press_enter,
                    "message": f"已聚焦 [{node.name or node.control_type}] 並完整填入提示詞" + ("且按 Enter 送出！" if press_enter else "！"),
                }
            except Exception as e:
                logging.debug(f"clipboard_focus_paste 失敗: {e}")

        # 3. 最後備援：ctrl.SendKeys
        if ctrl:
            try:
                ctrl.SetFocus()
                time.sleep(0.05)
                ctrl.SendKeys(value + ("{Enter}" if press_enter else ""))
                return {
                    "ok": True,
                    "action": "uia_sendkeys",
                    "element_id": node.node_id,
                    "name": node.name,
                    "value_set": value,
                    "press_enter": press_enter,
                    "message": f"已聚焦該元件並寫入文字：{value}",
                }
            except Exception as e:
                return {"ok": False, "error": f"寫入文字失敗：{str(e)}"}

    return {"ok": False, "error": f"無法對元素 [{element_id}] 寫入文字。"}


def install_app_and_uia_hooks() -> None:
    """
    將本機應用程式自動掃描、Google 預設權限規則、智慧啟動器與 UIA 強化邏輯
    動態掛載至 `core.permissions`、`core.desktop_controller`、`core.accessibility_engine` 與 `core.agent_brain`。
    """
    import asyncio
    import json
    import core.permissions as perms_mod
    import core.agent_brain as brain_mod
    from core.desktop_controller import DesktopController
    from core.accessibility_engine import AccessibilityEngine, accessibility_engine
    from core.tool_ecc import ToolCallECC

    if getattr(DesktopController, "_app_launcher_hooked", False):
        return

    # 1. 擴充 KNOWN_APPS 加入 Gemini 桌面版
    perms_mod.KNOWN_APPS["gemini"] = ("Google Gemini（桌面應用程式）", ("gemini", "google gemini"))

    # 2. 強化 identify_app（支援清理 `,0` 圖示索引並識別本機掃描到的所有應用程式）
    _orig_identify_app = perms_mod.identify_app

    def _patched_identify_app(name: str) -> Tuple[str, str]:
        cleaned = clean_executable_path(name)
        raw_check = cleaned or (name or "").strip().strip('"')
        if not raw_check:
            return "", ""
        key = normalize_app_key(name, cleaned)
        if key in perms_mod.KNOWN_APPS:
            return key, perms_mod.KNOWN_APPS[key][0]
        for app in scan_all_local_apps():
            if app["key"] == key:
                return key, app["name"]
        return _orig_identify_app(raw_check)

    perms_mod.identify_app = _patched_identify_app
    brain_mod.identify_app = _patched_identify_app

    # 3. 強化 allowed_apps 與 is_app_allowed：預設僅開啟 Google 相關應用，其餘預設關閉（除非使用者開啟）
    def _patched_allowed_apps(settings: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
        return compute_effective_allowed_apps(settings)

    def _patched_is_app_allowed(settings: Optional[Dict[str, Any]], key: str) -> bool:
        if not key or key in perms_mod._SELF_APPS:
            return True
        eff = compute_effective_allowed_apps(settings)
        return any(a.get("key") == key for a in eff)

    perms_mod.allowed_apps = _patched_allowed_apps
    perms_mod.is_app_allowed = _patched_is_app_allowed
    brain_mod.is_app_allowed = _patched_is_app_allowed

    # 4. 掛載 DesktopController.list_installed_software 與 launch_application
    def _patched_list_installed_software(self, max_items: int = 300, query: str = "") -> List[Dict[str, Any]]:
        return match_local_apps(query, max_items=max_items)

    def _patched_launch_application(self, target: str) -> Dict[str, Any]:
        return smart_launch_application(self, target)

    DesktopController.list_installed_software = _patched_list_installed_software
    DesktopController.launch_application = _patched_launch_application

    # 5. 掛載 AccessibilityEngine 與 DesktopController 的 UIA 強化方法
    AccessibilityEngine._find_node_by_id_or_name = lambda self, query: find_best_node(self._cached_nodes, query, prefer_input=False)
    AccessibilityEngine.dump_window_tree = lambda self, hwnd=0, max_depth=12, max_nodes=120: enhanced_dump_window_tree(
        self, hwnd=hwnd, max_depth=max_depth, max_nodes=max_nodes
    )

    async def _patched_ui_invoke(self, element_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(enhanced_invoke_element_by_id, self.accessibility, element_id, self)

    async def _patched_ui_type(self, element_id: str, text: str, press_enter: bool = False) -> Dict[str, Any]:
        return await asyncio.to_thread(
            enhanced_set_element_value_by_id, self.accessibility, element_id, text, press_enter, self
        )

    DesktopController.ui_invoke = _patched_ui_invoke
    DesktopController.ui_type = _patched_ui_type

    # 擴充 ToolCallECC.TOOL_SCHEMAS["ui_type"] 支援可選的 press_enter
    if "ui_type" in ToolCallECC.TOOL_SCHEMAS:
        opt = set(ToolCallECC.TOOL_SCHEMAS["ui_type"].get("optional", set()))
        opt.add("press_enter")
        ToolCallECC.TOOL_SCHEMAS["ui_type"]["optional"] = opt

    # 6. 強化 AgentBrain.execute_tool 中的 launch_application 與 ui_type：
    #    - launch_application 成功拿到 hwnd 後，自動記錄 self._ui_target_hwnd = hwnd，方便後續直接 ui_invoke / ui_type
    #    - ui_type 支援傳遞 press_enter=bool(args.get("press_enter", False))
    _prev_execute_tool = brain_mod.AgentBrain.execute_tool

    async def _patched_brain_execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        model_full_id: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        if tool_name == "ui_type":
            blocked = await self._enforce_tool_permission(tool_name, args)
            if blocked is not None:
                return blocked, None
            elem_id = str(args.get("element_id", "input"))
            text_to_type = str(args.get("text", ""))
            press_enter = bool(args.get("press_enter", False))
            for secret in self.security_guard.get_active_secrets():
                if secret in text_to_type:
                    return json.dumps(
                        {"ok": False, "error": "❌ [資安最高防護阻斷] 偵測到嘗試在視窗輸入真實 API Key / Token，已強制攔截！"},
                        ensure_ascii=False,
                    ), None
            res = await self.desktop.ui_type(elem_id, text_to_type, press_enter=press_enter)
            return json.dumps(res, ensure_ascii=False), None

        out_str, out_img = await _prev_execute_tool(self, tool_name, args, model_full_id=model_full_id)
        if tool_name == "launch_application":
            try:
                data = json.loads(out_str)
                if isinstance(data, dict) and data.get("hwnd"):
                    self._ui_target_hwnd = int(data["hwnd"])
            except Exception:
                pass
        return out_str, out_img

    brain_mod.AgentBrain.execute_tool = _patched_brain_execute_tool

    # 7. 在 AgentBrain.SYSTEM_PROMPT 明確指示優先使用本機軟體與無障礙互動閉環
    local_app_rule = (
        "\n\n### 🖥️ 【本機桌面軟體優先與深度互動鐵律】\n"
        "- 當使用者要求使用某款軟體（例如「用桌面上的 Gemini」、「開啟本地軟體搜尋/建立筆記本」），"
        "**必須優先呼叫 `launch_application`（可直接傳入軟體名稱如 `\"Gemini\"`）啟動本機軟體，絕對禁止偷懶改用 `web_search` 網頁搜尋代替**！\n"
        "- `launch_application` 成功後會直接回傳該視窗的 `hwnd`。請立即接著執行：\n"
        "  1. `inspect_accessibility_tree(hwnd=...)` 讀取視窗內的按鈕與輸入框 ID（如「發起新對話 / New chat」、「輸入提示詞」、「建立 Gem / 筆記本」）。\n"
        "  2. 點擊按鈕（如開新對話、建立筆記本）請呼叫 `ui_invoke(element_id=\"#ID或按鈕名稱\")`。\n"
        "  3. 輸入提示詞並搜尋/送出請呼叫 `ui_type(element_id=\"#ID或input\", text=\"提示詞內容\", press_enter=True)`。"
    )
    if "【本機桌面軟體優先與深度互動鐵律】" not in brain_mod.AgentBrain.SYSTEM_PROMPT:
        brain_mod.AgentBrain.SYSTEM_PROMPT += local_app_rule

    install_model_router_hooks()
    DesktopController._app_launcher_hooked = True


# ===========================================================================
# 智慧模型路由器強化與過時模型自動遷移 (ModelRouter & Gemini 404/Ollama Offline Fix)
# ===========================================================================
_LOCAL_PORT_CACHE: Dict[str, Tuple[bool, float]] = {}
_DEAD_MODEL_FULL_IDS: set = set()

_DEPRECATED_GEMINI_MODEL_MAP: Dict[str, str] = {
    "gemini-2.5-pro": "gemini-3.5-flash",
    "models/gemini-2.5-pro": "gemini-3.5-flash",
    "gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "models/gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
}

_ACTIVE_GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
]


def is_local_endpoint_reachable(base_url: str, ttl: float = 10.0) -> bool:
    """以 40ms 極速 TCP 探測本機 Ollama (127.0.0.1:11434) 是否真的有啟動，避免未開 Ollama 時連撞兩次 ConnectError。"""
    import socket
    import urllib.parse

    burl = (base_url or "").strip()
    if not burl:
        return False
    now = time.time()
    cached = _LOCAL_PORT_CACHE.get(burl)
    if cached and (now - cached[1]) < ttl:
        return cached[0]

    try:
        parsed = urllib.parse.urlparse(burl)
        host = (parsed.hostname or "").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=0.04):
            _LOCAL_PORT_CACHE[burl] = (True, now)
            return True
    except Exception:
        _LOCAL_PORT_CACHE[burl] = (False, now)
        return False


def migrate_deprecated_provider_models(api_manager: Any) -> bool:
    """
    自動修復 data/api_providers.json 中已被 Google 停用 (404) 的 gemini-2.5-pro
    或免費額度為 0 (429 limit:0) 的 gemini-3.1-pro-preview，替換為實測可用的最新模型清單。
    """
    changed = False
    for p in getattr(api_manager, "providers", []):
        burl = (p.get("base_url") or "").lower()
        if "generativelanguage.googleapis.com" in burl or "gemini" in (p.get("id") or "").lower():
            old_models = list(p.get("models") or [])
            new_models: List[str] = []
            for m in old_models:
                mapped = _DEPRECATED_GEMINI_MODEL_MAP.get(m.strip(), m.strip())
                # 將免費層 limit:0 的 gemini-3.1-pro-preview 移至最後或替換為可用模型
                if mapped == "gemini-3.1-pro-preview":
                    continue
                if mapped not in new_models:
                    new_models.append(mapped)
            for active_m in _ACTIVE_GEMINI_MODELS:
                if active_m not in new_models:
                    new_models.append(active_m)
            if new_models != old_models:
                p["models"] = new_models
                changed = True
    if changed:
        try:
            api_manager.save()
        except Exception:
            pass
    return changed


def install_model_router_hooks() -> None:
    """
    動態修補 ApiManager、ModelRouter 與 LLMClient：
    1. 自動將已淘汰的 `gemini-2.5-pro` (404) 轉發至 `gemini-3.5-flash` / `gemini-2.5-flash`。
    2. 本機 Ollama (`127.0.0.1:11434`) 未啟動時，40ms 即時略過本機候選模型，不再苦等 ConnectError。
    3. 遭遇 404 或 Free Tier `limit: 0` 的模型自動加入熔斷名單，避免重試卡死。
    """
    from core.api_manager import ApiManager
    from core.model_router import ModelRouter
    from core.llm_client import llm_client

    if getattr(ModelRouter, "_router_smart_hooked", False):
        return

    # 1. 更新預設 Gemini 模型清單與特徵關鍵字
    if "gemini" in ApiManager.PRESETS:
        ApiManager.PRESETS["gemini"]["models"] = list(_ACTIVE_GEMINI_MODELS)

    for kw in ("gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-3.6-flash"):
        if kw not in ModelRouter.REASONING_KEYWORDS:
            ModelRouter.REASONING_KEYWORDS.append(kw)
        if kw not in ModelRouter.CODING_KEYWORDS:
            ModelRouter.CODING_KEYWORDS.append(kw)

    # 2. 包裝 ApiManager._load 自動升級舊版模型名稱
    _orig_am_init = ApiManager.__init__

    def _patched_am_init(self, *args, **kwargs):
        _orig_am_init(self, *args, **kwargs)
        migrate_deprecated_provider_models(self)

    ApiManager.__init__ = _patched_am_init

    # 3. 包裝 ModelRouter.resolve_candidates：過濾未啟動的 localhost Ollama 與已熔斷的 404/0-quota 模型
    _orig_resolve = ModelRouter.resolve_candidates

    def _patched_resolve_candidates(
        self,
        task_type: str = "general",
        has_image: bool = False,
        preferred: Optional[str] = None,
        difficulty: str = "LOCAL_CAPABLE",
    ) -> List[Dict[str, Any]]:
        migrate_deprecated_provider_models(self.api_manager)
        # 若 preferred 指向上線失敗的本機 Ollama 或已停用模型，自動轉為 auto_router
        eff_pref = preferred
        if eff_pref:
            if "ollama" in eff_pref.lower() and not is_local_endpoint_reachable("http://127.0.0.1:11434/v1"):
                eff_pref = "auto_router"
            elif any(dep in eff_pref for dep in ("gemini-2.5-pro", "gemini-3.1-pro-preview")):
                eff_pref = "auto_router"

        raw_candidates = _orig_resolve(
            self,
            task_type=task_type,
            has_image=has_image,
            preferred=eff_pref,
            difficulty=difficulty,
        )

        # 過濾掉未啟動的 localhost 端點與已知 404/limit:0 熔斷模型
        alive_candidates: List[Dict[str, Any]] = []
        offline_local_candidates: List[Dict[str, Any]] = []
        for cand in raw_candidates:
            conn = cand.get("connection") or {}
            fid = conn.get("full_id") or ""
            mid = conn.get("model_id") or ""
            burl = conn.get("base_url") or ""

            if fid in _DEAD_MODEL_FULL_IDS or mid in _DEAD_MODEL_FULL_IDS:
                continue

            if self.is_local_item(cand.get("item") or conn):
                if not is_local_endpoint_reachable(burl):
                    offline_local_candidates.append(cand)
                    continue

            alive_candidates.append(cand)

        return alive_candidates if alive_candidates else (raw_candidates or offline_local_candidates)

    ModelRouter.resolve_candidates = _patched_resolve_candidates

    # 4. 包裝 llm_client.chat：自動轉寫已停用的 model_id 並將 404 / limit:0 加入熔斷池
    _orig_chat = llm_client.chat

    async def _patched_llm_chat(
        protocol: str,
        base_url: str,
        api_key: str,
        model_id: str,
        messages: List[Dict[str, Any]],
        full_id: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        on_text: Any = None,
        fallback_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        actual_model = _DEPRECATED_GEMINI_MODEL_MAP.get(model_id.strip(), model_id.strip())
        res = await _orig_chat(
            protocol,
            base_url,
            api_key,
            actual_model,
            messages,
            full_id=full_id,
            tools=tools,
            temperature=temperature,
            on_text=on_text,
            fallback_messages=fallback_messages,
        )
        if not res.get("ok"):
            err_str = str(res.get("error") or "")
            if "HTTP 404" in err_str or "no longer available" in err_str or "limit: 0," in err_str:
                if full_id:
                    _DEAD_MODEL_FULL_IDS.add(full_id)
                _DEAD_MODEL_FULL_IDS.add(actual_model)
        return res

    llm_client.chat = _patched_llm_chat
    ModelRouter._router_smart_hooked = True
