# -*- coding: utf-8 -*-
"""
軟體自主建圖與實測學習引擎（App Auto Mapper）。

核心原則（禁止寫死）：
1. 不硬編碼任何軟體清單、分類或固定操作步驟；所有軟體皆透過本機掃描動態發現。
2. 兩階段使用者授權：
   - Phase 1（建圖授權）：首次全面掃描、遇到未知軟體、或偵測到新下載/安裝軟體時，
     先通知並詢問使用者是否允許掃描與構建「使用說明＋操作地圖」。
   - Phase 2（實測授權）：建圖完成後，再詢問使用者是否允許實際啟動並測試操作軟體，
     以補全 UI 地圖（含啟動彈窗處理、控制項驗證）並確保後續操作正確。
3. 動態學習成果持久化至：
   - data/app_learning/installed_snapshot.json（已掃描軟體快照，用於比對新安裝/下載）
   - data/app_learning/app_profiles.json（各軟體動態生成的使用說明、能力與實測紀錄）
   - data/app_atlas/<proc>.json（UIA 實測操作地圖）
   - data/app_knowledge/<app>.json（操作步驟與彈窗處理知識）
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import app_atlas, app_knowledge

logger = logging.getLogger(__name__)

_LEARNING_DIR = Path(__file__).resolve().parent.parent / "data" / "app_learning"
_SNAPSHOT_FILE = _LEARNING_DIR / "installed_snapshot.json"
_PROFILES_FILE = _LEARNING_DIR / "app_profiles.json"
_STATE_FILE = _LEARNING_DIR / "mapper_state.json"

_DOC_PATTERNS = ("readme", "manual", "help", "guide", "說明", "使用手冊", "changelog", "release")
_DOC_EXTS = {".txt", ".md", ".rst", ".log", ".ini"}
_DISMISS_LABELS = ("確定", "確認", "好", "關閉", "略過", "取消", "知道", "ok", "yes", "close", "skip", "dismiss", "accept", "continue")
_QUEUE_FILE = _LEARNING_DIR / "test_queue.json"
_CHAT_PAY_KEYWORDS = ("chat", "message", "messenger", "mail", "im", "聊天", "訊息", "傳送", "通訊", "pay", "payment", "wallet", "bank", "checkout", "order", "trade", "付款", "支付", "轉帳", "結帳", "下單", "銀行", "錢包")
_UNSAFE_EXPLORE_WORDS = ("傳送", "送出", "發送", "付款", "結帳", "下單", "轉帳", "刪除", "移除", "登出", "結束", "關閉", "send", "pay", "checkout", "delete", "remove", "exit", "quit")


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, type(default)):
                return data
    except Exception:
        pass
    return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(data_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    p = (data_dir / "installed_snapshot.json") if data_dir else _SNAPSHOT_FILE
    return _load_json(p, {})


def save_snapshot(snapshot: Dict[str, Dict[str, Any]], data_dir: Optional[Path] = None) -> None:
    p = (data_dir / "installed_snapshot.json") if data_dir else _SNAPSHOT_FILE
    _save_json(p, snapshot)


def load_profiles(data_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    p = (data_dir / "app_profiles.json") if data_dir else _PROFILES_FILE
    return _load_json(p, {})


def save_profiles(profiles: Dict[str, Dict[str, Any]], data_dir: Optional[Path] = None) -> None:
    p = (data_dir / "app_profiles.json") if data_dir else _PROFILES_FILE
    _save_json(p, profiles)


def load_state(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    p = (data_dir / "mapper_state.json") if data_dir else _STATE_FILE
    return _load_json(p, {"initialized": False, "declined_keys": [], "skip_scan_keys": [], "skip_test_keys": [], "last_scan_ts": 0.0})


def save_state(state: Dict[str, Any], data_dir: Optional[Path] = None) -> None:
    p = (data_dir / "mapper_state.json") if data_dir else _STATE_FILE
    _save_json(p, state)


# ---------------------------------------------------------------- 動態掃描與差異比對
def _current_syntra_version() -> str:
    try:
        vf = Path(__file__).resolve().parent.parent / "VERSION"
        if vf.exists():
            return vf.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def detect_unmapped_or_new_apps(
    force_refresh: bool = True,
    scanner: Optional[Callable[[bool], List[Dict[str, Any]]]] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    動態掃描電腦目前已安裝軟體，並與快照及已建圖檔案比對：
    - is_initial: 是否為第一次掃描（尚未建立過快照）
    - new_apps: 相較上次快照新出現的軟體（新下載/新安裝）
    - unmapped_apps: 尚未建立使用說明與操作地圖的軟體
    - all_apps: 本次掃描到的全部軟體
    """
    if scanner is None:
        from .app_discovery_and_launcher import scan_all_local_apps
        scanner = scan_all_local_apps

    all_apps = scanner(force_refresh)
    snapshot = load_snapshot(data_dir)
    profiles = load_profiles(data_dir)
    state = load_state(data_dir)
    app_ver = _current_syntra_version()
    is_updated = bool(app_ver) and state.get("mapped_version") != app_ver
    is_initial = (not bool(state.get("initialized")) and len(snapshot) == 0) or is_updated

    new_apps: List[Dict[str, Any]] = []
    unmapped_apps: List[Dict[str, Any]] = []
    for app in all_apps:
        key = str(app.get("key") or "").strip()
        if not key:
            continue
        if key not in snapshot:
            new_apps.append(app)
        if key not in profiles:
            unmapped_apps.append(app)

    return {
        "is_initial": is_initial,
        "all_apps": all_apps,
        "new_apps": new_apps,
        "unmapped_apps": unmapped_apps,
    }


def _find_matching_scanned_apps(
    target_app: str,
    scanner: Optional[Callable[[bool], List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """依名稱/關鍵字在動態掃描結果中比對目標軟體。"""
    if scanner is None:
        from .app_discovery_and_launcher import scan_all_local_apps
        scanner = scan_all_local_apps
    q = (target_app or "").strip().lower()
    if not q:
        return []
    q_norm = re.sub(r"[\s_\-\.]+", "", q)
    apps = scanner(False) or scanner(True)
    exact: List[Dict[str, Any]] = []
    partial: List[Dict[str, Any]] = []
    for app in apps:
        name = str(app.get("name") or "").lower()
        key = str(app.get("key") or "").lower()
        exe = os.path.basename(str(app.get("launch_target") or "")).lower()
        if q in (key, name, exe) or q_norm == re.sub(r"[\s_\-\.]+", "", name):
            exact.append(app)
        elif q in name or q in key or q in exe or (q_norm and q_norm in re.sub(r"[\s_\-\.]+", "", name)):
            partial.append(app)
    return exact or partial


# ---------------------------------------------------------------- 靜態與執行期情報收集（無寫死）
def _read_pe_version_info(exe_path: str) -> Dict[str, str]:
    """透過 Windows version.dll 唯讀取得執行檔產品名稱、描述與公司名稱。"""
    out: Dict[str, str] = {}
    if os.name != "nt" or not exe_path or not os.path.isfile(exe_path):
        return out
    try:
        ver_dll = ctypes.windll.version
        size = ver_dll.GetFileVersionInfoSizeW(exe_path, None)
        if not size:
            return out
        buf = ctypes.create_string_buffer(size)
        if not ver_dll.GetFileVersionInfoW(exe_path, 0, size, buf):
            return out

        lptr = ctypes.c_void_p()
        ulen = ctypes.c_uint()
        # 取得語系/字碼頁清單
        lang_pairs = [(0x0404, 0x04B0), (0x0409, 0x04B0), (0x0409, 0x04E4), (0x0000, 0x04B0)]
        if ver_dll.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(lptr), ctypes.byref(ulen)) and ulen.value >= 4:
            arr = (ctypes.c_ushort * (ulen.value // 2)).from_address(lptr.value)
            for idx in range(0, len(arr) - 1, 2):
                lang_pairs.insert(0, (int(arr[idx]), int(arr[idx + 1])))

        fields = ("FileDescription", "ProductName", "CompanyName", "FileVersion", "Comments")
        seen_pairs = set()
        for lang, cp in lang_pairs:
            if (lang, cp) in seen_pairs:
                continue
            seen_pairs.add((lang, cp))
            for field in fields:
                if field in out:
                    continue
                sub = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{field}"
                vptr = ctypes.c_void_p()
                vlen = ctypes.c_uint()
                if ver_dll.VerQueryValueW(buf, sub, ctypes.byref(vptr), ctypes.byref(vlen)) and vptr.value and vlen.value > 0:
                    val = ctypes.wstring_at(vptr.value).strip()
                    if val:
                        out[field] = val
            if len(out) >= 3:
                break
    except Exception:
        pass
    return out


def _read_supported_extensions(exe_name: str) -> List[str]:
    """從 Windows 登錄檔 HKCR\Applications\<exe>\SupportedTypes 讀取該軟體可處理的副檔名。"""
    if os.name != "nt" or not exe_name:
        return []
    exts: List[str] = []
    try:
        import winreg
        sub = f"Applications\\{exe_name}\\SupportedTypes"
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, sub) as k:
            cnt = winreg.QueryInfoKey(k)[1]
            for i in range(min(cnt, 25)):
                vname, _, _ = winreg.EnumValue(k, i)
                if vname and vname.startswith("."):
                    exts.append(vname.lower())
    except Exception:
        pass
    return exts


def _read_registered_app_description(app_name: str, exe_name: str) -> str:
    """從 RegisteredApplications / Capabilities 與 MSIX AppxManifest.xml 讀取軟體官方描述。"""
    if os.name != "nt":
        return ""
    try:
        import winreg
        targets = [t.lower() for t in (app_name, os.path.splitext(exe_name)[0]) if t]
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\RegisteredApplications") as rk:
                    cnt = winreg.QueryInfoKey(rk)[1]
                    for i in range(min(cnt, 150)):
                        vname, vval, _ = winreg.EnumValue(rk, i)
                        if any(t in vname.lower() for t in targets) and isinstance(vval, str):
                            try:
                                with winreg.OpenKey(hive, vval) as ck:
                                    desc, _ = winreg.QueryValueEx(ck, "ApplicationDescription")
                                    if isinstance(desc, str) and desc.strip() and not desc.startswith("@"):
                                        return desc.strip()[:300]
                            except Exception:
                                pass
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _collect_local_docs(exe_path: str, max_chars: int = 1600) -> List[Dict[str, str]]:
    """從安裝資料夾安全讀取 README / 說明文字檔摘要（純讀取、不執行任何檔）。"""
    if not exe_path:
        return []
    base = Path(exe_path).parent if os.path.isfile(exe_path) else Path(exe_path)
    if not base.exists() or not base.is_dir():
        return []
    docs: List[Dict[str, str]] = []
    try:
        candidates = []
        for entry in list(base.iterdir())[:40]:
            if not entry.is_file():
                continue
            low = entry.name.lower()
            if entry.suffix.lower() in _DOC_EXTS and any(p in low for p in _DOC_PATTERNS):
                candidates.append(entry)
        for doc_path in candidates[:3]:
            try:
                if doc_path.stat().st_size > 250_000:
                    continue
                raw = doc_path.read_text(encoding="utf-8", errors="ignore").strip()
                if raw:
                    docs.append({"file": doc_path.name, "excerpt": raw[: max_chars // max(1, len(candidates[:3]))]})
            except Exception:
                continue
    except Exception:
        pass
    return docs


def _detect_process_name(app_entry: Dict[str, Any]) -> str:
    target = str(app_entry.get("launch_target") or "").strip()
    if target.lower().endswith(".exe"):
        return os.path.basename(target).lower()
    key = str(app_entry.get("key") or "unknown").strip().lower()
    return f"{key}.exe"


def _find_open_windows_for_app(app_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """尋找目前螢幕上屬於該軟體的視窗（若有開啟）。"""
    try:
        from .desktop_controller import desktop
        wins = desktop.list_open_windows() or []
    except Exception:
        return []
    proc = _detect_process_name(app_entry)
    name = str(app_entry.get("name") or "").lower()
    key = str(app_entry.get("key") or "").lower()
    matched = []
    for w in wins:
        wp = str(w.get("process_name") or "").lower()
        wt = str(w.get("title") or "").lower()
        if (proc and wp == proc) or (name and name in wt) or (key and len(key) >= 2 and key in wp):
            matched.append(w)
    return matched


async def _synthesize_usage_guide(brain, profile: Dict[str, Any]) -> str:
    """若有 LLM 可用，依據收集到的真實資訊歸納該軟體使用說明；否則以事實結構化整理。"""
    meta = profile.get("metadata") or {}
    docs = profile.get("local_docs") or []
    controls_summary = profile.get("atlas_summary") or ""
    facts = [
        f"軟體名稱：{profile.get('name')}",
        f"出版商：{profile.get('publisher') or meta.get('CompanyName') or '未知'}",
        f"版本：{profile.get('version') or meta.get('FileVersion') or '未知'}",
        f"執行檔：{profile.get('launch_target') or '未知'}",
    ]
    if meta.get("FileDescription"):
        facts.append(f"檔案描述：{meta['FileDescription']}")
    if meta.get("ProductName"):
        facts.append(f"產品名稱：{meta['ProductName']}")
    reg_desc = str(profile.get("registered_description") or "").strip()
    if reg_desc:
        facts.append("系統註冊用途說明：" + reg_desc)
    exts = profile.get("supported_extensions") or []
    if exts:
        facts.append("支援開啟檔案類型：" + ", ".join(exts[:15]))
    if docs:
        facts.append("本機說明摘錄：" + " | ".join(f"{d['file']}: {d['excerpt'][:300]}" for d in docs))
    if controls_summary:
        facts.append("已探索介面控制項：\n" + controls_summary[:900])

    fallback = "\n".join(facts)
    if brain is None or not hasattr(brain, "call_llm"):
        return fallback

    prompt = (
        "請根據以下真實掃描到的本機軟體資訊，為代理程式撰寫一份簡潔的「軟體使用說明與操作要點」（繁體中文，150~300字）。\n"
        "注意：只能依據提供的事實推論其用途、核心功能與建議操作方式；若某項資訊不足，請誠實標註「需實際開啟探索」，禁止編造不存在的快捷鍵或功能。\n\n"
        + fallback
    )
    try:
        res = await brain.call_llm(
            messages=[
                {"role": "system", "content": "你是謹慎的本機軟體分析專家，只依據真實中繼資料與介面樹撰寫簡潔的使用說明。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        text = ""
        if isinstance(res, dict):
            text = str(res.get("content") or res.get("text") or "").strip()
        elif isinstance(res, str):
            text = res.strip()
        if text:
            return text
    except Exception as e:
        logger.debug("LLM 歸納軟體說明略過：%s", e)
    return fallback


# ---------------------------------------------------------------- Phase 1：構建使用說明與操作地圖
async def build_app_guide_and_map(
    app_entry: Dict[str, Any],
    brain=None,
    data_dir: Optional[Path] = None,
    atlas_dir: Optional[Path] = None,
    knowledge_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Phase 1：為單一軟體動態構建使用說明與 UI 操作地圖（不執行未知程序，若視窗已開啟則唯讀探索 UIA）。
    """
    key = str(app_entry.get("key") or "").strip()
    name = str(app_entry.get("name") or key).strip()
    target = str(app_entry.get("launch_target") or "").strip()
    proc_name = _detect_process_name(app_entry)

    pe_meta = await asyncio.to_thread(_read_pe_version_info, target) if target else {}
    docs = await asyncio.to_thread(_collect_local_docs, target) if target else []
    supported_exts = await asyncio.to_thread(_read_supported_extensions, proc_name) if proc_name else []
    reg_desc = await asyncio.to_thread(_read_registered_app_description, name, proc_name)

    atlas_info: Dict[str, Any] = {}
    atlas_summary = ""
    open_wins = _find_open_windows_for_app(app_entry)
    for w in open_wins[:2]:
        try:
            atlas_info = await asyncio.to_thread(
                app_atlas.learn_window, w["hwnd"], w.get("process_name") or proc_name, w.get("title", ""), atlas_dir
            )
            atlas_summary = app_atlas.summarize(w.get("process_name") or proc_name, "", limit=25, data_dir=atlas_dir)
            if atlas_info.get("total", 0) > 0:
                break
        except Exception:
            pass

    if not atlas_summary:
        atlas_summary = app_atlas.summarize(proc_name, "", limit=25, data_dir=atlas_dir)

    profile: Dict[str, Any] = {
        "key": key,
        "name": name,
        "process_name": proc_name,
        "launch_target": target,
        "shortcut_path": str(app_entry.get("shortcut_path") or ""),
        "publisher": str(app_entry.get("publisher") or pe_meta.get("CompanyName") or ""),
        "version": str(app_entry.get("version") or pe_meta.get("FileVersion") or ""),
        "source": str(app_entry.get("source") or ""),
        "metadata": pe_meta,
        "local_docs": docs,
        "supported_extensions": supported_exts,
        "registered_description": reg_desc,
        "atlas_summary": atlas_summary,
        "tested": False,
        "modal_handlers": [],
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    profile["usage_guide"] = await _synthesize_usage_guide(brain, profile)

    profiles = load_profiles(data_dir)
    prev = profiles.get(key) or {}
    if prev.get("tested"):
        profile["tested"] = True
        profile["modal_handlers"] = prev.get("modal_handlers") or []
        profile["test_notes"] = prev.get("test_notes") or []
    profiles[key] = profile
    save_profiles(profiles, data_dir)

    # 更新快照
    snapshot = load_snapshot(data_dir)
    snapshot[key] = {
        "name": name,
        "launch_target": target,
        "version": profile["version"],
        "publisher": profile["publisher"],
        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_snapshot(snapshot, data_dir)

    # 同步登記到 app_learning 與 app_knowledge
    try:
        from . import app_learning
        app_learning.register(name, data_dir=data_dir)
        app_learning.register(proc_name, data_dir=data_dir)
    except Exception:
        pass
    try:
        steps = [s.strip() for s in profile["usage_guide"].splitlines() if s.strip()][:8]
        if steps:
            app_knowledge.save_note(
                app=name,
                task="軟體使用說明與功能概覽",
                steps=steps,
                origin="auto_mapper",
                verified=bool(profile.get("tested")),
                data_dir=knowledge_dir,
            )
    except Exception:
        pass

    return {"ok": True, "key": key, "name": name, "process_name": proc_name, "profile": profile, "atlas": atlas_info}


# ---------------------------------------------------------------- Phase 2：實際測試補全與彈窗學習
def _inspect_app_modal_and_windows_sync(proc_name: str, name_hint: str) -> Dict[str, Any]:
    """檢查目標程式所有頂層視窗，偵測主視窗是否被模態彈窗禁用，並讀取彈窗按鈕。"""
    import uiautomation as auto

    target_windows: List[Dict[str, Any]] = []
    root = auto.GetRootControl()
    proc_low = (proc_name or "").lower()
    hint_low = (name_hint or "").lower()

    for win in root.GetChildren():
        try:
            hwnd = int(win.NativeWindowHandle or 0)
            if not hwnd:
                continue
            title = (win.Name or "").strip()
            pid = int(win.ProcessId or 0)
            wp = ""
            try:
                import psutil
                wp = psutil.Process(pid).name().lower()
            except Exception:
                pass
            if (proc_low and wp == proc_low) or (hint_low and hint_low in title.lower()):
                enabled = bool(win.IsEnabled)
                controls = app_atlas._walk_uia(hwnd)
                rect = win.BoundingRectangle
                target_windows.append({
                    "hwnd": hwnd,
                    "title": title,
                    "process_name": wp or proc_low,
                    "enabled": enabled,
                    "controls": controls,
                    "rect": (rect.left, rect.top, rect.right, rect.bottom) if rect else None,
                })
        except Exception:
            continue

    disabled_wins = [w for w in target_windows if not w["enabled"]]
    enabled_wins = [w for w in target_windows if w["enabled"]]
    return {
        "windows": target_windows,
        "has_modal_block": bool(disabled_wins and enabled_wins),
        "modal_windows": enabled_wins if disabled_wins else [],
        "main_windows": disabled_wins or enabled_wins,
    }


def _try_dismiss_modal_sync(modal_win: Dict[str, Any]) -> Dict[str, Any]:
    """通用嘗試關閉阻擋主視窗的彈窗（UIA 按鈕優先 -> Enter -> Esc），不寫死特定視窗。"""
    import uiautomation as auto

    hwnd = modal_win["hwnd"]
    title = modal_win.get("title") or ""
    ctrl_root = auto.ControlFromHandle(hwnd)
    if ctrl_root is None:
        return {"dismissed": False, "method": "none", "modal_title": title}

    # 1. 先找具關閉/確認語意的 UIA 按鈕並 Invoke
    try:
        stack = [ctrl_root]
        visited = 0
        while stack and visited < 200:
            c = stack.pop()
            visited += 1
            cname = (c.Name or "").strip()
            ctype = getattr(c, "ControlTypeName", "")
            if ctype in ("ButtonControl", "HyperlinkControl") and cname:
                low = cname.lower()
                if any(lbl in low for lbl in _DISMISS_LABELS):
                    try:
                        c.Invoke()
                        time.sleep(0.5)
                        return {"dismissed": True, "method": f"uia_invoke:{cname}", "modal_title": title}
                    except Exception:
                        try:
                            c.Click()
                            time.sleep(0.5)
                            return {"dismissed": True, "method": f"uia_click:{cname}", "modal_title": title}
                        except Exception:
                            pass
            try:
                stack.extend(reversed(c.GetChildren()))
            except Exception:
                pass
    except Exception:
        pass

    # 2. UIA 讀不到按鈕時，聚焦視窗並嘗試 Enter，再檢查視窗是否已關閉
    try:
        ctrl_root.SetFocus()
        time.sleep(0.2)
        auto.SendKeys("{Enter}")
        time.sleep(0.6)
        if not auto.ControlFromHandle(hwnd):
            return {"dismissed": True, "method": "key:Enter", "modal_title": title}
    except Exception:
        pass

    # 3. 嘗試 Esc
    try:
        ctrl_root.SetFocus()
        time.sleep(0.2)
        auto.SendKeys("{Esc}")
        time.sleep(0.6)
        if not auto.ControlFromHandle(hwnd):
            return {"dismissed": True, "method": "key:Esc", "modal_title": title}
    except Exception:
        pass

    return {"dismissed": False, "method": "unhandled_custom_drawn_modal", "modal_title": title}


def create_desktop_test_sandbox(desktop_dir: Optional[Path] = None) -> Path:
    """在桌面底下建立專屬測試暫存資料夾，供實測存檔使用，測完一次刪除。"""
    base = desktop_dir or (Path.home() / "Desktop")
    sandbox = base / f"Syntra_AppTest_Tmp_{int(time.time())}"
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


def cleanup_desktop_test_sandbox(sandbox: Optional[Path]) -> bool:
    """測試完畢後一次刪除桌面測試暫存資料夾。"""
    if sandbox is None:
        return False
    try:
        if sandbox.exists():
            shutil.rmtree(sandbox, ignore_errors=True)
        return not sandbox.exists()
    except Exception:
        return False


def is_chat_or_payment_app(app_entry: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> bool:
    """動態從掃描到的名稱、檔案描述、說明摘錄判斷是否為聊天／通訊／付款／交易軟體（不寫死清單，英文採單詞邊界）。"""
    parts = [
        str(app_entry.get("name") or ""),
        str(app_entry.get("publisher") or ""),
        os.path.basename(str(app_entry.get("launch_target") or "")),
    ]
    if profile:
        meta = profile.get("metadata") or {}
        parts.extend([
            str(meta.get("FileDescription") or ""),
            str(meta.get("ProductName") or ""),
            str(profile.get("usage_guide") or "")[:400],
        ])
    hay = " ".join(parts).lower()
    for kw in _CHAT_PAY_KEYWORDS:
        if kw.isascii():
            if re.search(rf"\b{re.escape(kw)}\b", hay):
                return True
        elif kw in hay:
            return True
    return False


def load_test_queue(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    p = (data_dir / "test_queue.json") if data_dir else _QUEUE_FILE
    data = _load_json(p, [])
    return data if isinstance(data, list) else []


def save_test_queue(queue: List[Dict[str, Any]], data_dir: Optional[Path] = None) -> None:
    p = (data_dir / "test_queue.json") if data_dir else _QUEUE_FILE
    _save_json(p, queue)


def has_pending_test_queue(data_dir: Optional[Path] = None) -> int:
    return len(load_test_queue(data_dir))


def enqueue_test_targets(targets: List[Dict[str, Any]], data_dir: Optional[Path] = None, front: bool = False) -> List[Dict[str, Any]]:
    q = load_test_queue(data_dir)
    by_key = {item.get("key"): item for item in q if item.get("key")}
    if front:
        new_items = [t for t in targets if t.get("key") and not is_chat_or_payment_app(t)]
        rest = [item for item in q if item.get("key") not in {x.get("key") for x in new_items}]
        merged = new_items + rest
    else:
        merged = list(q)
        for t in targets:
            k = t.get("key")
            if k and k not in by_key and not is_chat_or_payment_app(t):
                merged.append(t)
                by_key[k] = t
    save_test_queue(merged, data_dir)
    return merged


def _is_user_using_computer(brain) -> bool:
    """檢查使用者是否正在用電腦（有操作、看影片、打遊戲），若是則讓出控制權給使用者優先。"""
    desk = getattr(brain, "desktop", None) if brain else None
    if desk is None:
        return False
    try:
        if desk.hard_block_reason():
            return True
        cg = getattr(desk, "context_guard", None)
        if cg is not None:
            can_use, _, _ = cg.can_take_foreground_control()
            return not can_use
    except Exception:
        pass
    return False


def _explore_top_menus_and_tabs_sync(hwnd: int, proc_name: str, atlas_dir: Optional[Path] = None) -> int:
    """安全遍歷軟體頂層選單與分頁（避開傳送/付款/刪除/關閉），補全深層控制項地圖。"""
    import uiautomation as auto

    root = auto.ControlFromHandle(int(hwnd))
    if root is None:
        return 0
    explored = 0
    try:
        stack = [(root, 0)]
        targets = []
        visited = 0
        while stack and visited < 180 and len(targets) < 10:
            ctrl, depth = stack.pop()
            visited += 1
            try:
                ctype = ctrl.ControlTypeName
                cname = (ctrl.Name or "").strip()
                if ctype in ("MenuItemControl", "TabItemControl") and cname and len(cname) <= 40:
                    low = cname.lower()
                    if not any(bad in low for bad in _UNSAFE_EXPLORE_WORDS):
                        targets.append(ctrl)
                if depth < 4:
                    for ch in reversed(ctrl.GetChildren()):
                        stack.append((ch, depth + 1))
            except Exception:
                continue

        for item in targets[:8]:
            try:
                try:
                    item.Invoke()
                except Exception:
                    item.Click()
                time.sleep(0.35)
                app_atlas.learn_window(hwnd, proc_name, "", data_dir=atlas_dir)
                explored += 1
            except Exception:
                continue
        if explored:
            try:
                auto.SendKeys("{Esc}")
            except Exception:
                pass
    except Exception:
        pass
    return explored


async def run_idle_test_worker(
    brain,
    data_dir: Optional[Path] = None,
    atlas_dir: Optional[Path] = None,
    knowledge_dir: Optional[Path] = None,
    max_per_run: int = 3,
) -> Dict[str, Any]:
    """在系統閒置不打擾使用者時消化待測佇列；使用者一動滑鼠或有任務就立刻暫停保存斷點。"""
    queue = load_test_queue(data_dir)
    if not queue:
        return {"ok": True, "tested": 0, "remaining": 0}
    profiles = load_profiles(data_dir)
    tested_now: List[Dict[str, Any]] = []
    sandbox = create_desktop_test_sandbox()
    try:
        while queue and len(tested_now) < max_per_run:
            if _is_user_using_computer(brain):
                break
            app_entry = queue[0]
            prof = profiles.get(app_entry.get("key") or "")
            if is_chat_or_payment_app(app_entry, prof):
                queue.pop(0)
                continue
            res = await live_test_and_complete_map(
                app_entry,
                brain=brain,
                data_dir=data_dir,
                atlas_dir=atlas_dir,
                knowledge_dir=knowledge_dir,
                sandbox_dir=sandbox,
            )
            tested_now.append(res)
            queue.pop(0)
            save_test_queue(queue, data_dir)
    finally:
        cleanup_desktop_test_sandbox(sandbox)
    save_test_queue(queue, data_dir)
    return {"ok": True, "tested": len(tested_now), "remaining": len(queue), "paused_for_user": _is_user_using_computer(brain)}


async def live_test_and_complete_map(
    app_entry: Dict[str, Any],
    brain=None,
    data_dir: Optional[Path] = None,
    atlas_dir: Optional[Path] = None,
    knowledge_dir: Optional[Path] = None,
    sandbox_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Phase 2：在使用者同意後，實際啟動軟體進行測試、偵測並學習如何通過啟動彈窗、
    補全完整 UI 操作地圖與測試註記。
    """
    key = str(app_entry.get("key") or "").strip()
    profiles_map = load_profiles(data_dir)
    is_sensitive = is_chat_or_payment_app(app_entry, profiles_map.get(key))
    if is_sensitive:
        ok_sup, sup_msg = await _ask_user(
            brain,
            title=f"敏感軟體「{app_entry.get('name') or key}」監督測試確認",
            reason="偵測為聊天／付款／敏感類軟體（背景排程會自動避開）。若要測試，需由您盯場並逐步確認每個動作，且隨時可按停止／拒絕中止。確定要進入監督逐步測試嗎？",
            payload={"action": "supervised_sensitive_test", "key": key},
            details={"kind": "sensitive_app_step_confirm", "what": f"監督測試 {app_entry.get('name') or key}", "why": "每步操作前皆會請您確認"},
        )
        if not ok_sup:
            return {"ok": False, "skipped_safety": True, "name": app_entry.get("name") or key,
                    "note": sup_msg or "已依安全原則避開聊天／付款軟體自動測試，僅保留使用說明學習。"}
    name = str(app_entry.get("name") or key).strip()
    proc_name = _detect_process_name(app_entry)

    # 1. 若尚未開啟，透過本機啟動器啟動
    open_wins = _find_open_windows_for_app(app_entry)
    launched_now = False
    if not open_wins:
        try:
            from .app_discovery_and_launcher import launch_local_app
            launch_res = await asyncio.to_thread(launch_local_app, app_entry.get("launch_target") or name)
            if launch_res.get("ok"):
                launched_now = True
                for _ in range(16):
                    await asyncio.sleep(0.5)
                    open_wins = _find_open_windows_for_app(app_entry)
                    if open_wins:
                        break
        except Exception as e:
            return {"ok": False, "error": f"啟動 {name} 失敗：{e}"}

    if not open_wins:
        return {"ok": False, "error": f"未能偵測到「{name}」的可見視窗，無法完成實測建圖。"}

    # 2. 偵測模態彈窗並嘗試通用處理
    modal_notes: List[str] = []
    inspect = await asyncio.to_thread(_inspect_app_modal_and_windows_sync, proc_name, name)
    if inspect.get("has_modal_block"):
        for mw in inspect.get("modal_windows", []):
            res = await asyncio.to_thread(_try_dismiss_modal_sync, mw)
            if res.get("dismissed"):
                modal_notes.append(f"啟動時偵測到阻擋彈窗「{res['modal_title']}」，實測以 {res['method']} 成功關閉。")
            else:
                modal_notes.append(
                    f"啟動時偵測到自繪阻擋彈窗「{res['modal_title']}」（UIA 與 Enter/Esc 未能直接關閉），"
                    "後續操作遇到此視窗需改用截圖視覺定位按鈕並滑鼠點擊。"
                )
        await asyncio.sleep(0.5)
        inspect = await asyncio.to_thread(_inspect_app_modal_and_windows_sync, proc_name, name)

    # 3. 對主視窗執行完整 UIA 地圖探索
    total_controls = 0
    for w in inspect.get("windows", []):
        try:
            res = await asyncio.to_thread(
                app_atlas.learn_window, w["hwnd"], w.get("process_name") or proc_name, w.get("title", ""), atlas_dir
            )
            total_controls = max(total_controls, int(res.get("total") or 0))
        except Exception:
            pass

    atlas_summary = app_atlas.summarize(proc_name, "", limit=30, data_dir=atlas_dir)
    test_notes: List[str] = [
        f"已實測啟動並驗證視窗可用（偵測視窗數：{len(inspect.get('windows', []))}，已收錄控制項：{total_controls}）。",
    ] + modal_notes
    if total_controls <= 6:
        test_notes.append("UIA 控制項較少（可能為自繪 / Electron / DirectUI 介面），操作時應優先結合快捷鍵或視覺截圖點擊。")

    # 4. 更新 profile 與知識庫
    profiles = load_profiles(data_dir)
    prof = profiles.get(key) or {"key": key, "name": name, "process_name": proc_name}
    prof["tested"] = True
    prof["tested_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    prof["modal_handlers"] = modal_notes
    prof["test_notes"] = test_notes
    prof["atlas_summary"] = atlas_summary
    prof["ui_control_count"] = total_controls
    if brain is not None:
        prof["usage_guide"] = await _synthesize_usage_guide(brain, prof)
    profiles[key] = prof
    save_profiles(profiles, data_dir)

    try:
        app_knowledge.save_note(
            app=name,
            task="實測驗證與啟動彈窗處理",
            steps=test_notes,
            origin="live_test",
            verified=True,
            data_dir=knowledge_dir,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "key": key,
        "name": name,
        "launched_now": launched_now,
        "controls_mapped": total_controls,
        "modal_notes": modal_notes,
        "test_notes": test_notes,
        "atlas_summary": atlas_summary,
    }


# ---------------------------------------------------------------- 詢問使用者授權 + 完整工作流
async def _ask_user(brain, title: str, reason: str, payload: Dict[str, Any], details: Dict[str, Any]) -> Tuple[bool, str]:
    sec = getattr(brain, "security_guard", None) if brain else None
    if sec is None or not hasattr(sec, "request_user_approval"):
        return False, "缺少安全審批介面，無法取得使用者同意。"
    return await sec.request_user_approval(
        risk_level="LOW_RISK",
        title=title,
        reason=reason,
        action_payload=payload,
        details=details,
    )


def _apply_user_selection(
    targets: List[Dict[str, Any]],
    user_note: str,
    persist_skip_field: str,
    data_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    依使用者回覆或既有不願意清單過濾軟體：
    - 先排除 mapper_state 內已標記不掃描/不測試的項目。
    - 若使用者回覆附帶排除條件（例如「跳過: A, B」或「不要測試 X」），將對應項目加入持久化跳過清單。
    """
    state = load_state(data_dir)
    skip_set = set(state.get(persist_skip_field) or [])
    note = (user_note or "").strip()
    if note and any(k in note for k in ("跳過", "排除", "不要", "不測", "skip", "exclude")):
        low_note = note.lower()
        for t in targets:
            nm = str(t.get("name") or "").lower()
            ky = str(t.get("key") or "").lower()
            if (nm and nm in low_note) or (ky and ky in low_note):
                skip_set.add(t["key"])
        state[persist_skip_field] = sorted(skip_set)[-300:]
        save_state(state, data_dir)

    kept = [t for t in targets if t.get("key") not in skip_set]
    skipped = [t for t in targets if t.get("key") in skip_set]
    return kept, skipped


def set_app_opt_out(app_key: str, skip_scan: Optional[bool] = None, skip_test: Optional[bool] = None, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    """供使用者或介面隨時切換某個軟體是否不掃描／不測試。"""
    state = load_state(data_dir)
    scan_skips = set(state.get("skip_scan_keys") or [])
    test_skips = set(state.get("skip_test_keys") or [])
    if skip_scan is True:
        scan_skips.add(app_key)
    elif skip_scan is False:
        scan_skips.discard(app_key)
    if skip_test is True:
        test_skips.add(app_key)
    elif skip_test is False:
        test_skips.discard(app_key)
    state["skip_scan_keys"] = sorted(scan_skips)
    state["skip_test_keys"] = sorted(test_skips)
    save_state(state, data_dir)
    return {"ok": True, "key": app_key, "skip_scan": app_key in scan_skips, "skip_test": app_key in test_skips}


async def run_discovery_and_mapping_flow(
    brain,
    mode: str = "unknown",
    target_app: str = "",
    ask_live_test: bool = True,
    scanner: Optional[Callable[[bool], List[Dict[str, Any]]]] = None,
    data_dir: Optional[Path] = None,
    atlas_dir: Optional[Path] = None,
    knowledge_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    完整兩階段流程：
    1. 掃描並辨識未知軟體 / 新下載軟體 / 全部軟體（不寫死）。
    2. 詢問使用者是否允許構建使用說明與操作地圖。
    3. 同意後構建使用說明與地圖。
    4. 構建完成後，詢問使用者是否允許實際測試補全並確保操作正確。
    5. 同意後進行實測並寫回知識庫。
    """
    diff = detect_unmapped_or_new_apps(force_refresh=True, scanner=scanner, data_dir=data_dir)
    mode_low = (mode or "unknown").strip().lower()

    if mode_low == "single" and target_app.strip():
        targets = _find_matching_scanned_apps(target_app, scanner=scanner)
        if not targets:
            return {"ok": False, "error": f"在本機電腦掃描不到名為「{target_app}」的軟體。"}
        targets = targets[:1]
        ask_title = f"請求授權認識「{targets[0]['name']}」"
        ask_reason = f"是否允許我掃描並了解「{targets[0]['name']}」的功能與介面操作方式？"
    elif mode_low == "new":
        targets = diff["new_apps"]
        if not targets:
            return {"ok": True, "message": "目前沒有偵測到新下載或新安裝的軟體。", "mapped": []}
        names_preview = "、".join(a["name"] for a in targets[:6]) + ("..." if len(targets) > 6 else "")
        ask_title = f"偵測到 {len(targets)} 個新安裝／下載的軟體"
        ask_reason = f"發現新軟體：{names_preview}。是否允許我掃描並學習這些軟體的介面與操作方式？"
    elif mode_low == "all":
        targets = diff["all_apps"]
        ask_title = f"請求掃描電腦已安裝軟體（共 {len(targets)} 個）"
        ask_reason = "是否允許我掃描您電腦目前的軟體清單，以了解各軟體的功能與操作方式？"
    else:
        targets = diff["unmapped_apps"]
        if not targets:
            return {"ok": True, "message": "電腦目前所有已掃描軟體皆已學習完成。", "mapped": []}
        names_preview = "、".join(a["name"] for a in targets[:6]) + ("..." if len(targets) > 6 else "")
        ask_title = f"發現 {len(targets)} 個尚未認識的本機軟體"
        ask_reason = f"包含：{names_preview}。是否允許我掃描並學習這些軟體的使用方式？"

    # 先過濾使用者先前標記為不掃描的軟體
    targets, _ = _apply_user_selection(targets, "", "skip_scan_keys", data_dir=data_dir)
    if not targets:
        return {"ok": True, "message": "目標軟體已依您的偏好設為不掃描。", "mapped": []}

    # 標記聊天/付款性質軟體，不允許自動實測
    for t in targets:
        if is_chat_or_payment_app(t):
            t["chat_or_payment_restricted"] = True

    consent_cb = getattr(brain, "app_consent_callback", None) if brain else None
    if callable(consent_cb) and len(targets) > 1:
        sel_res = await consent_cb(ask_title, ask_reason, targets, "確認掃描勾選軟體", "scan")
        if sel_res is not None:
            selected, skipped, remember = sel_res
            if remember and skipped:
                st = load_state(data_dir)
                sk = set(st.get("skip_scan_keys") or [])
                for s in skipped:
                    if s.get("key"):
                        sk.add(s["key"])
                st["skip_scan_keys"] = sorted(sk)[-400:]
                save_state(st, data_dir)
            if not selected:
                return {"ok": False, "declined": True, "message": "使用者未勾選任何要掃描學習的軟體。"}
            targets = selected
            approved_map = True
            msg = "ok"
        else:
            approved_map, msg = await _ask_user(
                brain,
                title=ask_title,
                reason=ask_reason,
                payload={"action": "discover_and_map_apps", "mode": mode_low, "count": len(targets)},
                details={"kind": "app_mapping_consent", "what": ask_title, "why": ask_reason},
            )
    else:
        approved_map, msg = await _ask_user(
            brain,
            title=ask_title,
            reason=ask_reason,
            payload={"action": "discover_and_map_apps", "mode": mode_low, "count": len(targets)},
            details={"kind": "app_mapping_consent", "what": ask_title, "why": ask_reason},
        )
    if not approved_map:
        # 若為新軟體被使用者拒絕掃描，記錄至 skip_scan_keys 避免重複請求
        if mode_low in ("new", "single"):
            st = load_state(data_dir)
            sk = set(st.get("skip_scan_keys") or [])
            for t in targets:
                sk.add(t["key"])
            st["skip_scan_keys"] = sorted(sk)[-300:]
            save_state(st, data_dir)
    if approved_map:
        targets, _ = _apply_user_selection(targets, msg, "skip_scan_keys", data_dir=data_dir)
    if not approved_map:
        state = load_state(data_dir)
        declined = set(state.get("declined_keys") or [])
        for t in targets[:30]:
            declined.add(t["key"])
        state["declined_keys"] = sorted(declined)[-200:]
        save_state(state, data_dir)
        return {"ok": False, "declined": True, "message": msg or "使用者未同意構建軟體使用說明與操作地圖。"}

    # 執行 Phase 1 建圖（若是大量全機掃描，先建完快照與靜態說明）
    mapped_results: List[Dict[str, Any]] = []
    for app_entry in targets:
        # 批次大量軟體時先以本機資料建檔，單一或少量（<= 5）時呼叫 LLM 深入歸納
        use_brain = brain if len(targets) <= 5 else None
        res = await build_app_guide_and_map(
            app_entry, brain=use_brain, data_dir=data_dir, atlas_dir=atlas_dir, knowledge_dir=knowledge_dir
        )
        mapped_results.append({"key": res["key"], "name": res["name"], "process_name": res["process_name"]})

    state = load_state(data_dir)
    state["initialized"] = True
    state["mapped_version"] = _current_syntra_version()
    state["last_scan_ts"] = time.time()
    save_state(state, data_dir)

    out: Dict[str, Any] = {
        "ok": True,
        "mapped_count": len(mapped_results),
        "mapped": mapped_results[:30],
        "tested": [],
    }

    if not ask_live_test or not targets:
        return out

    # 第二階段：建圖完成後，詢問使用者是否允許實際測試補全並確保操作正確
    test_targets, _ = _apply_user_selection(targets, "", "skip_test_keys", data_dir=data_dir)
    if not test_targets:
        out["note"] = "目標軟體皆已依您的偏好設為不實際測試。"
        return out
    if len(test_targets) > 5 and mode_low == "all":
        test_targets = test_targets[:5]
    test_names = "、".join(t["name"] for t in test_targets)
    approved_test, test_msg = await _ask_user(
        brain,
        title=f"是否允許實際測試並補全「{test_names}」的操作地圖？",
        reason=(
            f"已完成 {len(mapped_results)} 個軟體的初步使用說明與操作地圖構建。"
            f"是否允許我正式打開畫面實際操作一次「{test_names}」進行測試？"
            "（若測試過程需要存檔，會在桌面建立暫存測試資料夾，測試完畢後會一次自動刪除。）"
        ),
        payload={"action": "live_test_app_map", "targets": [t["key"] for t in test_targets]},
        details={"kind": "app_live_test_consent", "what": f"實測補全：{test_names}", "why": "確保操作路徑與彈窗處理正確"},
    )
    if approved_test:
        test_targets, _ = _apply_user_selection(test_targets, test_msg, "skip_test_keys", data_dir=data_dir)
    if not approved_test:
        out["live_test_declined"] = True
        out["note"] = test_msg or "已完成使用說明與初步地圖建構；使用者暫不允許實際啟動測試。"
        return out

    sandbox = create_desktop_test_sandbox()
    tested_results: List[Dict[str, Any]] = []
    try:
        for app_entry in test_targets:
            t_res = await live_test_and_complete_map(
                app_entry,
                brain=brain,
                data_dir=data_dir,
                atlas_dir=atlas_dir,
                knowledge_dir=knowledge_dir,
                sandbox_dir=sandbox,
            )
            tested_results.append(t_res)
    finally:
        cleaned = cleanup_desktop_test_sandbox(sandbox)
    out["tested"] = tested_results
    out["sandbox_cleaned"] = cleaned
    return out


# ---------------------------------------------------------------- 給 context_for / howto 查詢
def search_profiles_by_intent(query: str, limit: int = 5, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """依使用者描述的功能/意圖（例如「看盤」「技術分析」「剪輯」），在動態學到的 usage_guide 與 metadata 中搜尋本機軟體。"""
    profiles = load_profiles(data_dir)
    if not profiles or not query:
        return []
    q_low = query.lower()
    terms: List[str] = [w for w in re.findall(r"[a-z0-9]{2,}", q_low)]
    for seg in re.findall(r"[\u4e00-\u9fff]{2,}", q_low):
        if len(seg) <= 4:
            terms.append(seg)
        for i in range(len(seg) - 1):
            terms.append(seg[i : i + 2])
    terms = list(dict.fromkeys(terms))
    if not terms:
        return []
    scored = []
    for prof in profiles.values():
        hay = " ".join([
            str(prof.get("name") or ""),
            str(prof.get("publisher") or ""),
            str(prof.get("usage_guide") or ""),
            str((prof.get("metadata") or {}).get("FileDescription") or ""),
            str(prof.get("atlas_summary") or ""),
        ]).lower()
        hits = sum(2 if t in str(prof.get("name") or "").lower() else (1 if t in hay else 0) for t in terms)
        if hits > 0:
            scored.append((hits, prof))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:limit]]


def find_profile_for_text(text: str, data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """從使用者對話文字中動態比對已建圖的軟體（不寫死）。"""
    profiles = load_profiles(data_dir)
    if not profiles or not text:
        return []
    low = text.lower()
    low_compact = re.sub(r"[\s_\-]+", "", low)
    matched: List[Dict[str, Any]] = []
    for key, prof in profiles.items():
        name = str(prof.get("name") or "").lower()
        proc = str(prof.get("process_name") or "").lower().removesuffix(".exe")
        candidates = [c for c in (key.lower(), name, proc) if len(c) >= 2]
        if any((c in low) or (re.sub(r"[\s_\-]+", "", c) in low_compact) for c in candidates):
            matched.append(prof)
    return matched


def render_profile_context(prof: Dict[str, Any], query: str = "", atlas_dir: Optional[Path] = None) -> str:
    """組合動態學習到的使用說明、彈窗處理與實測 UI 地圖。"""
    parts: List[str] = [f"#### 📘 {prof.get('name')}（動態學習檔案，已實測：{bool(prof.get('tested'))}）"]
    guide = str(prof.get("usage_guide") or "").strip()
    if guide:
        parts.append(guide[:700])
    modals = prof.get("modal_handlers") or []
    if modals:
        parts.append("啟動彈窗與實測備註：\n" + "\n".join(f"- {m}" for m in modals[:4]))
    proc = str(prof.get("process_name") or "").strip()
    if proc:
        atlas_txt = app_atlas.summarize(proc, query, limit=15, data_dir=atlas_dir)
        if atlas_txt:
            parts.append(atlas_txt)
    return "\n".join(parts)


async def check_new_apps_on_startup_or_turn(
    brain,
    data_dir: Optional[Path] = None,
    scanner: Optional[Callable[[bool], List[Dict[str, Any]]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    輕量檢查：若從未掃描過電腦軟體，或偵測到新下載/新安裝的軟體，
    通知使用者並詢問是否允許構建使用說明與操作地圖（同批不重複打擾）。
    """
    state = load_state(data_dir)
    now = time.time()
    if now - float(state.get("last_scan_ts") or 0.0) < 300.0 and state.get("initialized"):
        return None
    diff = await asyncio.to_thread(detect_unmapped_or_new_apps, True, scanner, data_dir)
    declined = set(state.get("declined_keys") or [])
    state["last_scan_ts"] = now
    save_state(state, data_dir)

    if diff["is_initial"] and diff["all_apps"]:
        return await run_discovery_and_mapping_flow(
            brain, mode="all", ask_live_test=True, scanner=scanner, data_dir=data_dir
        )

    pending_new = [a for a in diff["new_apps"] if a.get("key") not in declined]
    if pending_new:
        return await run_discovery_and_mapping_flow(
            brain, mode="new", ask_live_test=True, scanner=scanner, data_dir=data_dir
        )
    return None
