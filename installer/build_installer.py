# -*- coding: utf-8 -*-
"""
建置可以發給別人的 Syntra 安裝檔（使用者電腦不需要安裝 Python）。

    python installer/build_installer.py            → dist/Syntra_Setup.exe
    python installer/build_installer.py --test     → 建置後，靜默安裝到暫存資料夾，在「沒有 Python」的環境變數下驗證

做法：
1. 程式檔：只收白名單裡的資料夾與檔案。user_profile/（對話紀錄、個人資料）、data/ 裡的個人設定
   與金鑰一律不收；打包前掃描金鑰與個人路徑，有問題就中止。
2. 內建 Python：複製本機 Python 3.11（不需要下載）＋程式實際用到的套件，裁掉用不到的大型檔案。
   runtime\\Syntra.exe 是改過名稱與圖示的 pythonw.exe，工作管理員會顯示「Syntra 星樞」。
3. 安裝目錄根的 Syntra.exe（C# 小啟動器）用內建環境開桌面版 desktop_app.py。
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.metadata as md
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
STAGE = DIST / "installer_stage"
PAYLOAD = DIST / "Syntra.payload.zip"
OUT_EXE = DIST / "Syntra_Setup.exe"
ICON = ROOT / "assets" / "syntra_icon.ico"

# ----------------------------------------------------------------------------- 程式檔白名單
APP_DIRS = ["core", "ui", "dlc", "modules", "cli", "guardian", "skills", "assets", "scripts"]
APP_FILES = ["desktop_app.py", "syntra_headless.py", "tray_launcher.py", "server.py", "requirements.txt", "README.md"]
DATA_FILES = ["data/credentials.json", "data/mcp_servers.json"]   # 預設設定；個人資料一律不收
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "logs", "user_profile", "data", "official_security_shield"}
EXCLUDE_GLOBS = ["*.pyc", "*.pyo", "*.log", "*.jsonl", "*.tmp", "*.bak", "*.dpapi", "*.db", "*.sqlite*",
                 ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12"]
EXCLUDE_FILES = {"scripts/apply_custom_icon.py", "core/self_defense_immortal.py"}   # 含開發者個人路徑或付費 DLC 模組

# 打包內容不可出現的個人資訊（只回報檔名，不印內容）
PERSONAL_MARKERS = [re.compile(r"C:[\\/]+Users[\\/]+Tim\b", re.I), re.compile(r"xavierlu469", re.I)]
# 安全模組把專案路徑寫死當預設值；只在打包的複本裡改成「程式所在資料夾」，不動原始碼
HARDCODED_ROOT = re.compile(r'r"C:\\Users\\Tim\\Desktop\\my_agent"')
PERSONAL_HOME = re.compile(r"C:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+Tim\b", re.I)
PORTABLE_ROOT = ('__import__("os").path.dirname(__import__("os").path.dirname('
                 '__import__("os").path.abspath(__file__)))')

# ----------------------------------------------------------------------------- 執行環境
ROOT_DISTS = ['PyQt5', 'PyYAML', 'WMI', 'beautifulsoup4', 'cryptography', 'fastapi', 'google-ai-generativelanguage',
              'google-api-core', 'google-api-python-client', 'google-auth', 'google-auth-oauthlib', 'google-genai',
              'google-generativeai', 'googleapis-common-protos', 'httpx', 'numpy', 'pillow', 'protobuf', 'psutil',
              'pydantic', 'pynput', 'pywin32', 'qrcode', 'requests', 'uiautomation', 'uvicorn', 'websockets']
# opencv-python（118MB）只有螢幕錄影才用到，而且是延遲載入；不放進安裝檔
SKIP_DISTS = {"opencv-python", "pip", "setuptools", "wheel"}
STDLIB_SKIP = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "__pycache__"}
DLLS_SKIP = {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll"}
GOOGLE_DOCS_KEEP = {"gmail.v1.json", "drive.v3.json", "calendar.v3.json", "docs.v1.json", "sheets.v4.json"}
QT_DROP = re.compile(r"(Quick|Qml|Designer|Location|Positioning|Bluetooth|Nfc|Sensors|RemoteObjects|Multimedia|"
                     r"WebChannel|XmlPatterns|SerialPort|TextToSpeech|Help|Test)", re.I)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _marker_ok(req: str) -> bool:
    if ";" not in req:
        return True
    marker = req.split(";", 1)[1]
    if "extra" in marker:
        return False
    try:
        from packaging.markers import Marker
        return Marker(marker).evaluate()
    except Exception:
        return "darwin" not in marker and "linux" not in marker


def dependency_closure(roots: Iterable[str]) -> Dict[str, md.Distribution]:
    seen: Dict[str, md.Distribution] = {}
    stack = list(roots)
    while stack:
        name = stack.pop()
        if _norm(name) in SKIP_DISTS:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        key = _norm(dist.metadata["Name"])
        if key in seen:
            continue
        seen[key] = dist
        for req in dist.requires or []:
            if _marker_ok(req):
                m = re.match(r"[A-Za-z0-9_.\-]+", req)
                if m:
                    stack.append(m.group(0))
    return seen


def _keep_site_file(rel: Path) -> bool:
    parts = rel.parts
    if "__pycache__" in parts or rel.suffix in (".pyc", ".pyi"):
        return False
    if parts[0] == "googleapiclient" and "documents" in parts and rel.suffix == ".json":
        return rel.name in GOOGLE_DOCS_KEEP
    if parts[0] == "PyQt5":
        if "qml" in parts:
            return False
        if "translations" in parts:
            return rel.name.endswith("zh_TW.qm")
        if QT_DROP.search(rel.name) and rel.suffix.lower() in (".dll", ".pyd", ".exe"):
            return False
    return True


def build_runtime(dest: Path) -> Tuple[int, int]:
    base = Path(sys.base_prefix)
    if (sys.version_info.major, sys.version_info.minor) != (3, 11):
        print(f"⚠️ 建置用的 Python 是 {sys.version.split()[0]}，程式是以 3.11 開發測試的")
    dest.mkdir(parents=True)
    for f in base.iterdir():
        if f.is_file() and (f.suffix.lower() in (".dll",) or f.name in ("python.exe", "pythonw.exe", "LICENSE.txt")):
            shutil.copy2(f, dest / f.name)
    shutil.copytree(base / "DLLs", dest / "DLLs", ignore=lambda d, names: [n for n in names if n in DLLS_SKIP])
    shutil.copytree(base / "Lib", dest / "Lib", ignore=lambda d, names: [
        n for n in names if (Path(d) == base / "Lib" and n in STDLIB_SKIP) or n == "__pycache__"])

    site_src = base / "Lib" / "site-packages"
    site_dst = dest / "Lib" / "site-packages"
    site_dst.mkdir()
    count = 0
    dists = dependency_closure(ROOT_DISTS)
    for key, dist in sorted(dists.items()):
        for f in dist.files or []:
            src = Path(dist.locate_file(f)).resolve()
            try:
                rel = src.relative_to(site_src)
            except ValueError:
                continue   # Scripts\ 底下的命令列工具等，不需要
            if not src.is_file() or not _keep_site_file(rel):
                continue
            out = site_dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            count += 1
    # 改名品牌化的主程式（工作管理員顯示「Syntra 星樞」）
    sys.path.insert(0, str(ROOT / "scripts"))
    from make_branded_runtime import brand_exe
    shutil.copy2(dest / "pythonw.exe", dest / "Syntra.exe")
    brand_exe(dest / "Syntra.exe", ICON if ICON.exists() else None)
    return len(dists), count


# ----------------------------------------------------------------------------- 程式檔
def _excluded(rel: Path) -> bool:
    if rel.as_posix() in EXCLUDE_FILES:
        return True
    if any(p in EXCLUDE_DIRS for p in rel.parts[:-1]):
        return True
    return any(fnmatch.fnmatch(rel.name, g) for g in EXCLUDE_GLOBS)


def iter_app_files() -> List[Path]:
    files: List[Path] = []
    for d in APP_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file():
                rel = p.relative_to(ROOT)
                if not _excluded(rel):
                    files.append(rel)
    for f in APP_FILES + DATA_FILES:
        if (ROOT / f).is_file():
            files.append(Path(f))
    return files


def copy_app(dest: Path) -> Tuple[int, List[str]]:
    patched: List[str] = []
    files = iter_app_files()
    for rel in files:
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel.suffix == ".py":
            text = (ROOT / rel).read_text(encoding="utf-8")
            new = HARDCODED_ROOT.sub(PORTABLE_ROOT, text)
            new = PERSONAL_HOME.sub("%USERPROFILE%", new)   # 範例路徑／註解裡的開發者家目錄
            if new != text:
                patched.append(rel.as_posix())
            out.write_text(new, encoding="utf-8", newline="")
        else:
            shutil.copy2(ROOT / rel, out)
    return len(files), patched


def audit(stage: Path) -> List[str]:
    """掃描要打包的程式檔：金鑰、個人路徑、個人資料夾。只回報位置，不印內容。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_release import scan_secrets
    app_files = [p.relative_to(stage) for p in stage.rglob("*")
                 if p.is_file() and p.relative_to(stage).parts[0] != "runtime"]
    problems = scan_secrets(stage, app_files)
    for rel in app_files:
        top = rel.parts[0]
        if top in ("user_profile",) or (top == "data" and rel.as_posix() not in DATA_FILES):
            problems.append(f"{rel.as_posix()}: 個人資料夾不應出現在安裝檔")
        if rel.suffix.lower() in (".py", ".json", ".md", ".txt", ".ps1", ".bat", ".vbs", ".cfg", ".ini"):
            text = (stage / rel).read_text(encoding="utf-8", errors="ignore")
            for pat in PERSONAL_MARKERS:
                for m in pat.finditer(text):
                    problems.append(f"{rel.as_posix()}:{text.count(chr(10), 0, m.start()) + 1}  含開發者個人資訊")
    return problems


# ----------------------------------------------------------------------------- 編譯
def _csc() -> Path:
    for fw in ("Framework64", "Framework"):
        p = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / fw / "v4.0.30319" / "csc.exe"
        if p.exists():
            return p
    raise FileNotFoundError("找不到 .NET Framework 4 的 csc.exe")


def compile_cs(src: Path, out: Path, resources: List[Tuple[Path, str]] = ()) -> None:
    args = [str(_csc()), "/nologo", "/target:winexe", "/optimize+", "/codepage:65001", f"/out:{out}",
            "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:Microsoft.CSharp.dll",
            "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll"]
    if ICON.exists():
        args.append(f"/win32icon:{ICON}")
    for path, name in resources:
        args.append(f"/resource:{path},{name}")
    args.append(str(src))
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"編譯 {src.name} 失敗：\n{r.stdout}\n{r.stderr}")


def make_payload(stage: Path, out: Path) -> int:
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(stage).as_posix())
                n += 1
    return n


def build() -> Path:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    n_app, patched = copy_app(STAGE)
    print(f"程式檔：{n_app} 個（改成可攜路徑的安全模組：{len(patched)} 個）")
    problems = audit(STAGE)
    if problems:
        print("❌ 發現不該打包的內容，已中止：")
        for p in problems[:50]:
            print("   ", p)
        raise SystemExit(2)
    print("隱私掃描：通過（沒有金鑰、個人路徑、對話紀錄或個人設定）")
    n_dist, n_site = build_runtime(STAGE / "runtime")
    print(f"內建執行環境：Python {sys.version.split()[0]}＋{n_dist} 個套件（{n_site} 個檔案）")
    compile_cs(ROOT / "installer" / "launcher" / "SyntraLauncher.cs", STAGE / "Syntra.exe")
    n = make_payload(STAGE, PAYLOAD)
    print(f"封包：{n} 個檔案，{PAYLOAD.stat().st_size / 1e6:.0f} MB")
    compile_cs(ROOT / "installer" / "launcher" / "ModernWizardInstaller.cs", OUT_EXE,
               [(PAYLOAD, "Syntra.payload.zip")])
    print(f"完成：{OUT_EXE}（{OUT_EXE.stat().st_size / 1e6:.0f} MB）")
    return OUT_EXE


# ----------------------------------------------------------------------------- 驗證
SMOKE = r'''
import os, sys, json
root = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, root)
os.chdir(root)
outside = [p for p in sys.path if p and not os.path.abspath(p).lower().startswith(root.lower())]
import importlib
mods = ["PyQt5.QtWidgets", "PyQt5.QtSvg", "PyQt5.QtNetwork", "win32api", "win32crypt", "pythoncom", "psutil",
        "httpx", "numpy", "PIL.Image", "google.oauth2.credentials", "google_auth_oauthlib.flow",
        "googleapiclient.discovery", "google.genai", "uiautomation", "pynput", "cryptography", "yaml", "bs4"]
failed = {}
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        failed[m] = repr(e)[:200]
from PyQt5.QtWidgets import QApplication
app = QApplication([])
try:
    import desktop_app
except Exception as e:
    import traceback
    failed["desktop_app"] = traceback.format_exc()[-1500:]
leaked = sorted({os.path.dirname(getattr(m, "__file__", "") or "") for m in list(sys.modules.values())
                 if getattr(m, "__file__", None) and not os.path.abspath(m.__file__).lower().startswith(root.lower())})
print(json.dumps({"python": sys.version.split()[0], "outside_sys_path": outside, "failed": failed,
                  "modules_loaded_from_outside": leaked[:20]}, ensure_ascii=False), flush=True)
os._exit(0)
'''


def test(setup: Path) -> bool:
    import json
    import tempfile
    target = Path(tempfile.mkdtemp(prefix="syntra_install_test_"))
    r = subprocess.run([str(setup), "/S", f"/D={target}"], timeout=900)
    if r.returncode != 0:
        print(f"❌ 靜默安裝失敗（代碼 {r.returncode}）")
        return False
    print(f"已安裝到測試資料夾：{target}")
    # 模擬「沒有安裝 Python」：PATH 只留 Windows 系統資料夾，清掉所有 PYTHON* 變數
    win = os.environ.get("WINDIR", r"C:\Windows")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env["PATH"] = f"{win}\\System32;{win};{win}\\System32\\Wbem"
    env["PYTHONNOUSERSITE"] = "1"
    smoke = target / "smoke_test.py"
    smoke.write_text(SMOKE, encoding="utf-8")
    r = subprocess.run([str(target / "runtime" / "python.exe"), "-I", "-X", "utf8", str(smoke)], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, cwd=target)
    smoke.unlink(missing_ok=True)
    line = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if not line:
        print("❌ 驗證程式沒有輸出：\n", r.stdout[-2000:], r.stderr[-3000:])
        return False
    res = json.loads(line[-1])
    ok = not res["failed"] and not res["outside_sys_path"] and not res["modules_loaded_from_outside"]
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print("✅ 驗證通過：沒有 Python 的環境也能載入整個程式" if ok else "❌ 驗證未通過")
    for exe in (target / "Syntra.exe", target / "runtime" / "Syntra.exe"):
        print(f"   {exe.relative_to(target)} 存在：{exe.exists()}")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="建置後在模擬無 Python 環境中安裝並驗證")
    ap.add_argument("--test-only", action="store_true", help="不重新建置，只驗證既有的 dist/Syntra_Setup.exe")
    args = ap.parse_args(argv)
    setup = OUT_EXE if args.test_only else build()
    if args.test or args.test_only:
        return 0 if test(setup) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
