# -*- coding: utf-8 -*-
"""
建立「Syntra 星樞」品牌執行檔，讓工作管理員顯示 Syntra 星樞（而不是 Python）。

做法：把本機的 pythonw.exe 複製成 Syntra.exe，改寫它的版本資訊（工作管理員顯示的名稱）與圖示，
再放一份 pyvenv.cfg 指回原本的 Python，所以不需要重新安裝任何套件。

    python scripts/make_branded_runtime.py                 → 建在 %APPDATA%\\SyntraHub\\runtime
    python scripts/make_branded_runtime.py --out D:\\x     → 建在指定資料夾
    python scripts/make_branded_runtime.py --check         → 只驗證既有的 runtime 能不能跑

輸出資料夾內容：Syntra.exe、python3*.dll、vcruntime140*.dll、pyvenv.cfg（約 6 MB）。
Python 更新版本後重新執行一次即可。
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

PRODUCT = "Syntra 星樞"
EXE_NAME = "Syntra.exe"
VERSION = (1, 0, 0, 0)
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(os.environ.get("APPDATA", str(Path.home()))) / "SyntraHub" / "runtime"
DEFAULT_ICON = ROOT / "assets" / "syntra_icon.ico"

RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16


# ---------------------------------------------------------------- 版本資訊（VS_VERSIONINFO）
def _pad4(b: bytes) -> bytes:
    return b + b"\0" * ((4 - len(b) % 4) % 4)


def _node(key: str, value: bytes = b"", wtype: int = 1, children: List[bytes] = (), value_len: Optional[int] = None) -> bytes:
    """組一個版本資訊節點：wLength, wValueLength, wType, szKey, 對齊, Value, 對齊, Children。"""
    body = _pad4(struct.pack("<HHH", 0, 0, 0) + (key + "\0").encode("utf-16-le"))
    if value:
        body = _pad4(body + value)
    for ch in children:
        body = _pad4(body) + ch
    if value_len is None:
        value_len = len(value) // 2 if wtype == 1 else len(value)
    return struct.pack("<HHH", len(body), value_len, wtype) + body[6:]


def build_version_info(product: str = PRODUCT, version: Tuple[int, int, int, int] = VERSION,
                       original_name: str = EXE_NAME) -> bytes:
    ms = (version[0] << 16) | version[1]
    ls = (version[2] << 16) | version[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    ver_str = ".".join(map(str, version))
    strings = {
        "CompanyName": "Syntra",
        "FileDescription": product,      # 工作管理員顯示的名稱
        "FileVersion": ver_str,
        "InternalName": "Syntra",
        "OriginalFilename": original_name,
        "ProductName": product,
        "ProductVersion": ver_str,
        "LegalCopyright": "Syntra（以 Python 執行）",
    }
    string_nodes = [_node(k, (v + "\0").encode("utf-16-le"), 1) for k, v in strings.items()]
    table = _node("040404B0", children=string_nodes)  # 繁體中文（台灣）, Unicode
    sfi = _node("StringFileInfo", children=[table])
    var = _node("Translation", struct.pack("<HH", 0x0404, 1200), wtype=0)
    vfi = _node("VarFileInfo", children=[var])
    return _node("VS_VERSION_INFO", fixed, wtype=0, children=[sfi, vfi], value_len=len(fixed))


# ---------------------------------------------------------------- 圖示
def parse_ico(path: Path) -> List[Tuple[bytes, bytes]]:
    """回傳 [(GRPICONDIRENTRY 前 12 bytes, 圖片資料)]。"""
    data = path.read_bytes()
    _reserved, typ, count = struct.unpack_from("<HHH", data, 0)
    if typ != 1 or count == 0:
        raise ValueError(f"{path} 不是有效的 .ico 檔")
    out = []
    for i in range(count):
        w, h, colors, res, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        out.append((struct.pack("<BBBBHHI", w, h, colors, res, planes, bits, size), data[offset:offset + size]))
    return out


# ---------------------------------------------------------------- 寫入資源
def _languages(exe: Path, rtype: int) -> dict:
    import win32api
    found = {}
    h = win32api.LoadLibraryEx(str(exe), 0, 0x2)  # LOAD_LIBRARY_AS_DATAFILE
    try:
        try:
            names = win32api.EnumResourceNames(h, rtype)
        except Exception:
            names = []
        for name in names:
            try:
                found[name] = win32api.EnumResourceLanguages(h, rtype, name)
            except Exception:
                found[name] = [0]
    finally:
        win32api.FreeLibrary(h)
    return found


def brand_exe(exe: Path, icon: Optional[Path]):
    import win32api
    versions = _languages(exe, RT_VERSION)
    groups = _languages(exe, RT_GROUP_ICON) if icon else {}
    icons = _languages(exe, RT_ICON) if icon else {}

    h = win32api.BeginUpdateResource(str(exe), False)
    try:
        for name, langs in versions.items():
            for lang in langs:
                win32api.UpdateResource(h, RT_VERSION, name, None, lang)
        win32api.UpdateResource(h, RT_VERSION, 1, build_version_info(), 0x0404)

        if icon:
            for rtype, table in ((RT_GROUP_ICON, groups), (RT_ICON, icons)):
                for name, langs in table.items():
                    for lang in langs:
                        win32api.UpdateResource(h, rtype, name, None, lang)
            entries = parse_ico(icon)
            grp = struct.pack("<HHH", 0, 1, len(entries))
            for i, (head, img) in enumerate(entries, start=1):
                win32api.UpdateResource(h, RT_ICON, i, img, 0)
                grp += head + struct.pack("<H", i)
            win32api.UpdateResource(h, RT_GROUP_ICON, 1, grp, 0)
    except Exception:
        win32api.EndUpdateResource(h, True)  # 放棄修改
        raise
    win32api.EndUpdateResource(h, False)


def read_description(exe: Path) -> str:
    import win32api
    lang, cp = win32api.GetFileVersionInfo(str(exe), "\\VarFileInfo\\Translation")[0]
    return win32api.GetFileVersionInfo(str(exe), f"\\StringFileInfo\\{lang:04X}{cp:04X}\\FileDescription")


# ---------------------------------------------------------------- 組 runtime
def base_python_dir() -> Path:
    return Path(getattr(sys, "_base_executable", sys.executable)).resolve().parent


def build(out: Path, icon: Optional[Path] = DEFAULT_ICON) -> Path:
    base = base_python_dir()
    src = base / "pythonw.exe"
    if not src.exists():
        raise FileNotFoundError(f"找不到 {src}")
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / (EXE_NAME + ".new")
    shutil.copy2(src, tmp)
    brand_exe(tmp, icon if icon and icon.exists() else None)
    target = out / EXE_NAME
    try:
        os.replace(tmp, target)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise PermissionError(f"{target} 正在執行中，請先退出 Syntra 再重建") from e
    for dll in base.glob("*.dll"):  # python3.dll、python3XX.dll、vcruntime140*.dll
        try:
            shutil.copy2(dll, out / dll.name)
        except PermissionError:
            pass  # 執行中被鎖住：保留舊的同版本檔
    (out / "pyvenv.cfg").write_text(
        f"home = {base}\ninclude-system-site-packages = true\n"
        f"version = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n",
        encoding="utf-8")
    return target


def check(exe: Path) -> Tuple[bool, str]:
    code = ("import sys, PyQt5.QtCore, win32api, psutil, httpx; "
            "print(sys.version_info[:2], sys.executable)")
    try:
        r = subprocess.run([str(exe).replace("Syntra.exe", "Syntra.exe"), "-c", code], capture_output=True, text=True,
                           timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return r.returncode == 0, (r.stdout or r.stderr).strip()[-400:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="建立 Syntra 星樞品牌執行檔")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--icon", default=str(DEFAULT_ICON))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    exe = out / EXE_NAME
    if not args.check:
        exe = build(out, Path(args.icon) if args.icon else None)
        print(f"✅ 已建立 {exe}")
    print(f"工作管理員顯示名稱：{read_description(exe)}")
    ok, info = check(exe)
    print(("✅ 可以正常執行：" if ok else "❌ 無法執行：") + info)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
