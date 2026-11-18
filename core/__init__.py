# Syntra 星樞 Agent Core Package
#
# 注意：這裡刻意不匯入任何子模組。
# 過去會在 `import core.xxx` 時順帶載入並建立 5 個從未被 agent 使用的模組
# （幽靈桌面、UIA 驅動、離席自律、語意剪貼簿、時間軸記憶）的全域實例，白白增加啟動時間。
# 需要時請直接 `from core.ghost_desktop_worker import ghost_worker` 等方式個別匯入。
