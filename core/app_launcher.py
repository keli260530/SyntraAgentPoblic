# -*- coding: utf-8 -*-
"""
找出並開啟本機應用程式（含 Microsoft Store / MSIX 版，例如 Claude 桌面版、WhatsApp、Spotify）。

舊做法只讀登錄檔 Uninstall 清單，Store 版 App 不在裡面，agent 就誤以為沒安裝而改開網頁版。
這裡另外讀「開始功能表」的 App 清單（Get-StartApps，涵蓋傳統程式與 Store 版），
並用 `explorer.exe shell:AppsFolder\\<AppID>` 開啟，跟使用者從開始功能表點開完全一樣。
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_CACHE_SECONDS = 300
_cache: Dict[str, Any] = {"at": 0.0, "apps": []}
_lock = threading.Lock()
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _quiet_startupinfo():
    """啟動背景指令時不要讓滑鼠游標變成「忙碌中」的藍圈（STARTF_FORCEOFFFEEDBACK）。"""
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= 0x00000080
        return si
    except Exception:
        return None


def start_apps(refresh: bool = False) -> List[Dict[str, str]]:
    """開始功能表上的所有 App：[{name, app_id}]。結果快取 5 分鐘。"""
    with _lock:
        if not refresh and _cache["apps"] and time.time() - _cache["at"] < _CACHE_SECONDS:
            return list(_cache["apps"])
    apps: List[Dict[str, str]] = []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, timeout=20, creationflags=_NO_WINDOW, startupinfo=_quiet_startupinfo())
        data = json.loads((r.stdout or b"[]").decode("utf-8", "replace") or "[]")
        if isinstance(data, dict):
            data = [data]
        for d in data or []:
            name, app_id = str(d.get("Name") or "").strip(), str(d.get("AppID") or "").strip()
            if name and app_id:
                apps.append({"name": name, "app_id": app_id})
    except Exception:
        apps = []
    with _lock:
        if apps:
            _cache.update(at=time.time(), apps=apps)
        return list(apps or _cache["apps"])


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-\.]+", "", (s or "").lower())


def _is_store_app(app_id: str) -> bool:
    # Store / MSIX 的 AppID 長這樣：Claude_pzs8sxrjxfjjc!Claude
    return "!" in app_id and "\\" not in app_id


def _shortcut_apps() -> List[Dict[str, Any]]:
    """掃描工作列釘選、開始功能表與桌面（僅頂層）的 .lnk/.url 捷徑，補齊登錄檔與 Store 漏掉的程式。"""
    items: List[Dict[str, Any]] = []
    roots = [
        (os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"), "工作列釘選", True),
        (os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"), "開始功能表捷徑", True),
        (os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"), "開始功能表捷徑", True),
        (os.path.expandvars(r"%USERPROFILE%\Desktop"), "桌面捷徑", False),
        (os.path.expandvars(r"%PUBLIC%\Desktop"), "桌面捷徑", False),
    ]
    for base, source, recursive in roots:
        if not base or not os.path.isdir(base):
            continue
        try:
            if recursive:
                for root, _, files in os.walk(base):
                    for fn in files:
                        if fn.lower().endswith((".lnk", ".url")):
                            items.append({
                                "name": os.path.splitext(fn)[0],
                                "version": "", "publisher": "", "install_location": root,
                                "launch_target": os.path.join(root, fn), "source": source,
                            })
            else:
                for fn in os.listdir(base):
                    if fn.lower().endswith((".lnk", ".url")):
                        items.append({
                            "name": os.path.splitext(fn)[0],
                            "version": "", "publisher": "", "install_location": base,
                            "launch_target": os.path.join(base, fn), "source": source,
                        })
        except Exception:
            continue
    return items


def _windows_search_shortcuts(query: str) -> List[Dict[str, Any]]:
    """查詢 Windows 原生搜尋索引 (Search.CollatorDSO / 檔案總管同源索引) 找出符合名稱的 .lnk/.exe。"""
    q = re.sub(r"['\"%_;]", "", (query or "").strip())
    if len(q) < 2:
        return []
    ps = (
        "$conn = New-Object -ComObject ADODB.Connection;"
        "$conn.Open('Provider=Search.CollatorDSO;Extended Properties=\"Application=Windows\";');"
        f"$rs = $conn.Execute(\"SELECT TOP 8 System.ItemName, System.ItemPathDisplay FROM SYSTEMINDEX "
        f"WHERE System.ItemName LIKE '%{q}%' AND (System.FileExtension='.lnk' OR System.FileExtension='.exe')\");"
        "$out = @(); while (-not $rs.EOF) { "
        "$out += @{name=$rs.Fields.Item('System.ItemName').Value; path=$rs.Fields.Item('System.ItemPathDisplay').Value}; "
        "$rs.MoveNext() }; $out | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + ps],
            capture_output=True, timeout=4, creationflags=_NO_WINDOW, startupinfo=_quiet_startupinfo(),
        )
        data = json.loads((r.stdout or b"[]").decode("utf-8", "replace") or "[]")
        if isinstance(data, dict):
            data = [data]
        out = []
        for d in data or []:
            p = str(d.get("path") or "").strip()
            n = os.path.splitext(str(d.get("name") or ""))[0].strip()
            if n and p and os.path.isfile(p):
                out.append({"name": n, "version": "", "publisher": "", "install_location": os.path.dirname(p),
                            "launch_target": p, "source": "Windows 本地搜尋"})
        return out
    except Exception:
        return []


def merged_inventory(registry: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """登錄檔清單＋開始功能表 App＋工作列/桌面捷徑，去除重複名稱。"""
    items = list(registry)
    names = {_norm(x.get("name", "")) for x in items}
    for a in start_apps():
        key = _norm(a["name"])
        entry = {"name": a["name"], "version": "", "publisher": "",
                 "install_location": "", "launch_target": f"shell:AppsFolder\\{a['app_id']}",
                 "source": "Microsoft Store" if _is_store_app(a["app_id"]) else "開始功能表"}
        if key in names:
            # 同名的登錄檔項目沒有可用的啟動目標時，補上開始功能表的
            for x in items:
                if _norm(x.get("name", "")) == key and not _usable_exe(x.get("launch_target", "")):
                    x["launch_target"] = entry["launch_target"]
            continue
        names.add(key)
        items.append(entry)
    for sc in _shortcut_apps():
        key = _norm(sc["name"])
        if key not in names:
            names.add(key)
            items.append(sc)
    items.sort(key=lambda s: s["name"].lower())
    return items


# 使用者常用的英文／簡稱 → Windows 上實際的 App 名稱（中文系統多為中文名）
ALIASES = {
    "notepad": ["記事本", "notepad"], "calc": ["小算盤", "calculator"], "calculator": ["小算盤", "calculator"],
    "vscode": ["visual studio code"], "vs code": ["visual studio code"], "code": ["visual studio code"],
    "chrome": ["google chrome"], "edge": ["microsoft edge"], "explorer": ["檔案總管", "file explorer"],
    "paint": ["小畫家", "paint"], "terminal": ["終端機", "windows terminal", "terminal"],
    "settings": ["設定", "settings"], "line": ["line"], "word": ["word"], "excel": ["excel"],
    "powerpoint": ["powerpoint"], "teams": ["microsoft teams", "teams"], "spotify": ["spotify"],
}


_NOISE_RE = re.compile(r"(?:\.exe\b|桌面版|desktop|應用程式|軟體|用戶端|客戶端|client\b|app\b)", re.IGNORECASE)
_ALIAS_FILE = Path(__file__).resolve().parent.parent / "data" / "app_learning" / "app_aliases.json"


def _load_learned_aliases() -> Dict[str, str]:
    try:
        data = json.loads(_ALIAS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def remember_alias(query: str, real_name: str) -> None:
    """記住使用者輸入的縮寫／別稱對應到的本機正式軟體名稱。"""
    k = _norm(query)
    v = (real_name or "").strip()
    if not k or not v or k == _norm(v):
        return
    try:
        data = _load_learned_aliases()
        if data.get(k) == v:
            return
        data[k] = v
        _ALIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ALIAS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_subseq(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def filter_inventory_scored(items: List[Dict[str, Any]], query: str) -> List[tuple[int, Dict[str, Any]]]:
    """依相符程度排序並保留分數：0完全相同 > 1別名 > 2單字 > 3開頭 > 4包含 > 5詞元 > 6縮寫 > 7模糊。"""
    cleaned = _NOISE_RE.sub(" ", query or "").strip()
    q = _norm(cleaned or query)
    if not q:
        return [(0, x) for x in items]
    raw_q = (cleaned or query or "").strip().lower()
    learned = _load_learned_aliases().get(_norm(query)) or _load_learned_aliases().get(q)
    alias = [_norm(a) for a in ALIASES.get(raw_q, [])]
    if learned:
        alias.append(_norm(learned))
    tokens = [t for t in re.findall(r"[a-z0-9\u4e00-\u9fff]+", raw_q) if len(t) >= 2]

    def score(x) -> Optional[int]:
        n = _norm(x["name"])
        words = [w for w in re.split(r"[\s_\-\.()（）]+", x["name"].lower()) if w]
        if n == q:
            return 0
        if n in alias:
            return 1
        if raw_q in words or any(a and a in n for a in alias):
            return 2
        if n.startswith(q):
            return 3
        if q in n:
            return 4
        if tokens and any(t in n for t in tokens):
            return 5
        if len(q) >= 2 and n and q[0] == n[0] and _is_subseq(q, n):
            return 6
        if len(q) >= 3 and n and difflib.SequenceMatcher(None, q, n).ratio() >= 0.58:
            return 7
        return None

    ranked = [(s, len(x["name"]), x) for x in items for s in [score(x)] if s is not None]
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [(s, x) for s, _, x in ranked]


def filter_inventory(items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """依相符程度排序：完全相同 > 常用/學到別名 > 單字 > 開頭 > 包含 > 詞元 > 縮寫子序列 > 模糊相似度。"""
    return [x for _, x in filter_inventory_scored(items, query)]


def _usable_exe(target: str) -> Optional[str]:
    """登錄檔 DisplayIcon 常是 "C:\\x\\app.exe,0" 這種格式；整理成可執行的 exe 路徑。"""
    t = (target or "").strip().strip('"')
    t = re.sub(r",\s*-?\d+$", "", t).strip('"')
    if t.lower().endswith(".exe") and os.path.isfile(t):
        return t
    return None


def _open_apps_folder(app_id: str) -> None:
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], creationflags=_NO_WINDOW)


def launch(target: str, registry: List[Dict[str, Any]]) -> Dict[str, Any]:
    """依序嘗試：檔案路徑 → shell:AppsFolder → 開始功能表名稱 → 登錄檔名稱 → 交給系統。"""
    target = (target or "").strip().strip('"')
    if not target:
        return {"ok": False, "error": "未指定要開啟的軟體名稱或路徑。"}
    try:
        if os.path.exists(target):
            os.startfile(target)
            return {"ok": True, "launched": target, "how": "檔案路徑"}
        if target.lower().startswith("shell:appsfolder\\"):
            _open_apps_folder(target.split("\\", 1)[1])
            return {"ok": True, "launched": target, "how": "開始功能表"}
        scored = filter_inventory_scored(merged_inventory(registry), target)
        if not scored:
            start_apps(refresh=True)
            scored = filter_inventory_scored(merged_inventory(registry), target)
        if not scored:
            ws_hits = _windows_search_shortcuts(target)
            if ws_hits:
                scored = filter_inventory_scored(ws_hits, target)
        if len(scored) > 1 and scored[0][0] >= 5 and scored[1][0] == scored[0][0]:
            cands = [
                {"name": item["name"], "target": item.get("launch_target") or item["name"]}
                for _, item in scored[:6]
                if item.get("launch_target")
            ]
            if len(cands) > 1:
                return {
                    "ok": False,
                    "ambiguous": True,
                    "candidates": cands,
                    "error": "找到多個可能符合的本機軟體，請用一整排按鈕讓使用者點選要開啟哪一個。",
                }
        hits = [x for _, x in scored]
        for item in hits:
            lt = item.get("launch_target", "")
            if lt.lower().startswith("shell:appsfolder\\"):
                _open_apps_folder(lt.split("\\", 1)[1])
                remember_alias(target, item["name"])
                return {"ok": True, "launched": item["name"], "how": item.get("source") or "開始功能表",
                        "note": "已開啟本機安裝的版本"}
            exe = _usable_exe(lt)
            if exe:
                os.startfile(exe)
                remember_alias(target, item["name"])
                return {"ok": True, "launched": item["name"], "how": "已安裝程式", "path": exe,
                        "note": "已開啟本機安裝的版本"}
            if lt.lower().endswith((".lnk", ".url")) and os.path.isfile(lt):
                os.startfile(lt)
                remember_alias(target, item["name"])
                return {"ok": True, "launched": item["name"], "how": item.get("source") or "捷徑", "path": lt,
                        "note": "已開啟本機捷徑"}
        os.startfile(target)  # 例如 notepad、calc 這類系統認得的名稱
        return {"ok": True, "launched": target, "how": "系統指令"}
    except Exception as e:
        hint = ""
        if not target.lower().startswith("http"):
            hint = ("；請先呼叫 list_installed_software 檢查本機已安裝清單（含 Microsoft Store）；"
                    "若為縮寫或別稱，先上網搜尋確認該軟體的正式名稱／常見簡稱後再比對本機清單，"
                    "確認本機真的沒有才改開網頁版")
        return {"ok": False, "error": f"無法開啟「{target}」：{e}{hint}"}
