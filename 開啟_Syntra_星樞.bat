@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
"%PYW%" scripts\setup_startup_and_shortcut.py --silent >nul 2>&1
if exist "%APPDATA%\SyntraHub\launcher.py" (
    start "" "%PYW%" "%APPDATA%\SyntraHub\launcher.py"
) else (
    start "" "%PYW%" desktop_app.py
)
