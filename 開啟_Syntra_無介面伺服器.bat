@echo off
chcp 65001 >nul
REM Syntra 無介面伺服器模式：不開視窗，開遙控 API（預設只接受本機連線）
REM 讓區域網路其他電腦連線：在下面那行最後加上  --host 0.0.0.0
cd /d "%~dp0"
python syntra_headless.py serve %*
pause
