import json
import os
from pathlib import Path
import shutil
import sys
from typing import Optional
import winreg


REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_REG_NAME = "SyntraHub"
APPDATA_SYNTRA_DIR = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "SyntraHub"
APPDATA_SYNTRA_DIR.mkdir(parents=True, exist_ok=True)
LOCATION_FILE = APPDATA_SYNTRA_DIR / "current_project_dir.txt"


BRANDED_EXE = APPDATA_SYNTRA_DIR / "runtime" / "Syntra.exe"


def get_pythonw_and_python() -> tuple[str, str]:
    """回傳 (無視窗執行檔, python.exe)。有品牌執行檔（工作管理員顯示 Syntra 星樞）時優先使用。"""
    py_exe = Path(sys.executable).resolve()
    pyw_exe = py_exe.parent / "pythonw.exe"
    if not pyw_exe.exists():
        pyw_exe = py_exe
    if BRANDED_EXE.exists() and (BRANDED_EXE.parent / "pyvenv.cfg").exists():
        pyw_exe = BRANDED_EXE
    return str(pyw_exe), str(py_exe)


def update_registered_location(project_dir: Optional[Path] = None):
    """將專案目前的真實目錄記錄到 %APPDATA%/SyntraHub/current_project_dir.txt"""
    p_dir = project_dir or Path(__file__).resolve().parent.parent
    try:
        LOCATION_FILE.write_text(str(p_dir.resolve()), encoding="utf-8")
    except Exception:
        pass


def get_registered_location() -> Optional[Path]:
    if LOCATION_FILE.exists():
        try:
            path_str = LOCATION_FILE.read_text(encoding="utf-8").strip()
            if path_str:
                p = Path(path_str)
                if (p / "desktop_app.py").exists():
                    return p
        except Exception:
            pass
    return None


def search_for_relocated_project_fast() -> Optional[Path]:
    """當目錄被移動時，極速在常用路徑搜尋（限制深度 3，跳過龐大快取目錄，0.05 秒內完成）"""
    user_home = Path.home()
    quick_roots = [
        user_home / "Desktop",
        user_home / "Documents",
        user_home / "Downloads",
        user_home / "Projects",
        user_home / "source",
        user_home,
    ]
    for letter in ["D:\\", "E:\\", "F:\\", "C:\\"]:
        if os.path.exists(letter):
            quick_roots.append(Path(letter))

    skip_names = {
        "AppData", "node_modules", ".git", "Windows", "Program Files",
        "Program Files (x86)", "$Recycle.Bin", "venv", ".venv", "__pycache__"
    }

    for root in quick_roots:
        if not root.exists():
            continue
        stack = [(root, 0)]
        while stack:
            cur, depth = stack.pop()
            if (cur / "desktop_app.py").exists() and (cur / "core" / "agent_brain.py").exists():
                return cur.resolve()
            if depth >= 3:
                continue
            try:
                for entry in os.scandir(cur):
                    if entry.is_dir(follow_symlinks=False) and entry.name not in skip_names and not entry.name.startswith("."):
                        stack.append((Path(entry.path), depth + 1))
            except (PermissionError, OSError):
                continue
    return None


def prompt_user_for_folder() -> Optional[Path]:
    """若智慧快搜未果，彈出原生 Windows 資料夾挑選對話框引導使用者選取新目錄"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Syntra 星樞 · 偵測到專案已搬移，請選取新資料夾")
        root.destroy()
        if selected:
            p = Path(selected)
            if (p / "desktop_app.py").exists():
                return p.resolve()
    except Exception:
        pass
    return None


def deploy_appdata_launcher():
    """生成並同步最穩固的動態跳板至 %APPDATA%/SyntraHub/launcher.py"""
    launcher_file = APPDATA_SYNTRA_DIR / "launcher.py"
    pyw_exe, _ = get_pythonw_and_python()

    launcher_content = '''# -*- coding: utf-8 -*-
"""
Syntra 星樞 · 永不失效動態啟動跳板
位於固定的 %APPDATA%/SyntraHub/launcher.py
即使使用者搬移、重新命名專案資料夾，桌面捷徑也絕對不會損壞！
"""
import os
from pathlib import Path
import runpy
import sys
import traceback

if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

def search_for_relocated_project_fast():
    user_home = Path.home()
    quick_roots = [
        user_home / "Desktop",
        user_home / "Documents",
        user_home / "Downloads",
        user_home / "Projects",
        user_home / "source",
        user_home,
    ]
    for letter in ["D:\\\\", "E:\\\\", "F:\\\\", "C:\\\\"]:
        if os.path.exists(letter):
            quick_roots.append(Path(letter))

    skip_names = {
        "AppData", "node_modules", ".git", "Windows", "Program Files",
        "Program Files (x86)", "$Recycle.Bin", "venv", ".venv", "__pycache__"
    }

    for root in quick_roots:
        if not root.exists():
            continue
        stack = [(root, 0)]
        while stack:
            cur, depth = stack.pop()
            if (cur / "desktop_app.py").exists() and (cur / "core" / "agent_brain.py").exists():
                return cur.resolve()
            if depth >= 3:
                continue
            try:
                for entry in os.scandir(cur):
                    if entry.is_dir(follow_symlinks=False) and entry.name not in skip_names and not entry.name.startswith("."):
                        stack.append((Path(entry.path), depth + 1))
            except (PermissionError, OSError):
                continue
    return None

def prompt_user_for_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Syntra 星樞 · 偵測到專案已搬移，請選取新資料夾")
        root.destroy()
        if selected:
            p = Path(selected)
            if (p / "desktop_app.py").exists():
                return p.resolve()
    except Exception:
        pass
    return None

def main():
    try:
        import ctypes
        hdesk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(hdesk)
    except Exception:
        pass

    appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "SyntraHub"
    loc_file = appdata / "current_project_dir.txt"
    err_log = appdata / "launcher_err.log"

    try:
        proj_dir = ""
        if loc_file.exists():
            try:
                proj_dir = loc_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        script_path = Path(proj_dir) / "desktop_app.py" if proj_dir else None

        # 若登記路徑不存在，啟動極速自定位修復
        if not script_path or not script_path.exists():
            found = search_for_relocated_project_fast()
            if not found:
                found = prompt_user_for_folder()

            if found and (found / "desktop_app.py").exists():
                proj_dir = str(found.resolve())
                loc_file.write_text(proj_dir, encoding="utf-8")
                script_path = found / "desktop_app.py"

        if script_path and script_path.exists():
            os.chdir(proj_dir)
            sys.argv = [str(script_path)] + sys.argv[1:]  # 轉傳 --tray 等參數
            if proj_dir not in sys.path:
                sys.path.insert(0, proj_dir)
            runpy.run_path(str(script_path), run_name="__main__")
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "找不到 Syntra 星樞 專案目錄！\\n\\n請在搬動後的資料夾內雙擊【開啟_Syntra_星樞.bat】，即可一鍵自動修復桌面捷徑與開機自啟！",
                "Syntra 星樞 搬移提醒",
                48,
            )
    except Exception as e:
        with err_log.open("a", encoding="utf-8") as f:
            f.write(f"CRASH: {e}\\n{traceback.format_exc()}\\n")

if __name__ == "__main__":
    main()
'''
    launcher_file.write_text(launcher_content, encoding="utf-8")


def configure_windows_autostart(enable: bool = True) -> dict:
    """設定 Windows 開機啟動，透過動態啟動跳板啟動，保證搬動目錄後依然開機自啟"""
    pyw_exe, _ = get_pythonw_and_python()
    launcher_py = APPDATA_SYNTRA_DIR / "launcher.py"
    cmd = f'"{pyw_exe}" "{launcher_py}"'

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        try:
            winreg.DeleteValue(key, "GeminiDesktopAgent")
        except FileNotFoundError:
            pass

        if enable:
            winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            return {"ok": True, "enabled": True, "command": cmd}
        else:
            try:
                winreg.DeleteValue(key, APP_REG_NAME)
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
            return {"ok": True, "enabled": False}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def create_desktop_shortcut() -> dict:
    """
    在桌面建立自定位捷徑：
    1. 複製專屬藍光圖示至 %APPDATA%/SyntraHub/（即使專案目錄被搬動，桌面圖示也絕對不會失效或變白！）
    2. 捷徑 Target 指向固定在 %APPDATA% 的智慧啟動跳板。
    3. WorkingDirectory 設為 %APPDATA%/SyntraHub（永遠不會因為專案目錄移動而被 Windows 判定為無效路徑）。
    4. 同步專案內的 便攜型 開啟_Syntra_星樞.bat，支援隨身移動點擊自動修復。
    """
    base_dir = Path(__file__).resolve().parent.parent
    update_registered_location(base_dir)
    deploy_appdata_launcher()

    desktop_dir = Path.home() / "Desktop"
    shortcut_path = desktop_dir / "Syntra 星樞.lnk"
    old_shortcut = desktop_dir / "開啟 Gemini 桌面 Agent.lnk"
    if old_shortcut.exists():
        try:
            old_shortcut.unlink()
        except Exception:
            pass

    # 將高畫質圖示備份一份在穩固的 %APPDATA%/SyntraHub，避免搬動後圖示遺失
    appdata_ico = APPDATA_SYNTRA_DIR / "syntra_icon.ico"
    local_ico = base_dir / "assets" / "syntra_icon.ico"
    if local_ico.exists():
        try:
            shutil.copy2(local_ico, appdata_ico)
        except Exception:
            pass

    launcher_py = APPDATA_SYNTRA_DIR / "launcher.py"
    pyw_exe, _ = get_pythonw_and_python()

    # 建立專案內的便攜型 .bat（使用相對路徑 %~dp0，無論資料夾搬到哪，雙擊此 bat 必開並自動修復桌面連結！）
    bat_path = base_dir / "開啟_Syntra_星樞.bat"
    bat_content = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "cd /d \"%~dp0\"\r\n"
        f'"{pyw_exe}" scripts\\setup_startup_and_shortcut.py --silent >nul 2>&1\r\n'
        f'start "" "{pyw_exe}" "{launcher_py}"\r\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")

    # 建立桌面原生 .lnk
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.TargetPath = pyw_exe
        shortcut.Arguments = f'"{launcher_py}"'
        # 重要：工作目錄固定指向 APPDATA，這樣就算搬動 my_agent，Windows 也不會跳出捷徑損壞！
        shortcut.WorkingDirectory = str(APPDATA_SYNTRA_DIR)
        shortcut.WindowStyle = 7  # 7 = 啟動時徹底隱藏控制台宿主黑框，純靜默後台運行
        shortcut.Description = "開啟 Syntra 星樞 (AI 寫程式監督 / 桌面自動化 / 多組 API / 畫面錄影)"
        ico_to_use = appdata_ico if appdata_ico.exists() else local_ico
        shortcut.IconLocation = f"{ico_to_use},0"
        shortcut.save()
        return {
            "ok": True,
            "shortcut_path": str(shortcut_path),
            "bat_path": str(bat_path),
        }
    except Exception as e:
        desktop_cmd = desktop_dir / "Syntra 星樞.cmd"
        cmd_content = (
            "@echo off\r\n"
            f'start "" "{pyw_exe}" "{launcher_py}"\r\n'
        )
        desktop_cmd.write_text(cmd_content, encoding="utf-8")
        return {
            "ok": True,
            "shortcut_path": str(desktop_cmd),
            "bat_path": str(bat_path),
            "note": f"Fallback to cmd ({e})",
        }


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r1 = configure_windows_autostart(True)
    r2 = create_desktop_shortcut()
    print("AutoStart:", r1)
    print("Shortcut:", r2)
