# -*- coding: utf-8 -*-
"""
內建軟體操作手冊（App Playbooks）

讓本機小模型不用靠截圖一格一格摸索：每個常用軟體寫好
- 指令列 / 專用工具的做法（最快、最穩，優先）
- 常見任務的固定步驟（任務 → 要呼叫哪些工具）
- 常用快捷鍵（必須操作 UI 時用）

處理順序原則：指令或專用工具 → 快捷鍵 → 截圖 + 滑鼠點擊（最後手段）。
這裡只是「知識」，不執行任何動作；實際動作仍走各工具原本的權限與同意流程。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

PLAYBOOKS: Dict[str, Dict[str, Any]] = {
    "vscode": {
        "name": "Visual Studio Code",
        "aliases": ["vscode", "vs code", "visual studio code", "vsc", "code.exe"],
        "process": ["code.exe"],
        "cli": "code",
        "tips": [
            "建立／寫入檔案不要用截圖打字：直接用 `write_text_file`（content 放完整程式碼，open_in=\"vscode\"），一步完成並在 VS Code 開啟。",
            "開啟既有檔案或資料夾：`open_file_in_app`（app=\"vscode\"），等同指令 `code <路徑>`。",
            "執行 Python 檔：`run_background_shell` 執行 `python \"<檔案路徑>\"`，不必在 VS Code 裡按執行。",
            "VS Code 是 Electron 程式，無障礙結構樹資訊很少；必須操作 UI 時改用快捷鍵（`computer_key`），不要反覆讀結構樹。",
        ],
        "tasks": [
            {"id": "new_file_with_content", "title": "新增檔案並寫入內容",
             "keywords": ["新增", "建立", "新檔", "寫", "檔案", "py", "程式", "hello", "create", "new file"],
             "steps": [
                 "決定檔名與位置：使用者沒指定就放桌面，例如 `%USERPROFILE%\\Desktop\\hello_world.py`",
                 "`write_text_file`：path=完整路徑，content=完整檔案內容（例如 print(\"Hello, World!\")），open_in=\"vscode\"",
                 "（選用）`run_background_shell`：`python \"<路徑>\"` 執行並回報輸出",
             ],
             "ui_fallback": "launch_application 開 VS Code → computer_key ctrl+n → type_text 內容 → computer_key ctrl+s → type_text 完整路徑 → computer_key enter"},
            {"id": "open_folder", "title": "開啟資料夾／專案",
             "keywords": ["開啟資料夾", "打開專案", "open folder", "專案"],
             "steps": ["`open_file_in_app`：path=資料夾路徑，app=\"vscode\""]},
            {"id": "run_python", "title": "執行 Python 檔案",
             "keywords": ["執行", "run", "跑", "python", "py檔", "跑起來"],
             "steps": ["`run_background_shell`：`python \"<檔案路徑>\"`，回報輸出"]},
        ],
        "shortcuts": {
            "新增檔案": "ctrl+n", "開啟檔案": "ctrl+o", "存檔": "ctrl+s", "另存新檔": "ctrl+shift+s",
            "命令選擇區": "ctrl+shift+p", "快速開檔": "ctrl+p", "終端機": "ctrl+`", "搜尋": "ctrl+shift+f",
            "關閉分頁": "ctrl+w", "側邊欄": "ctrl+b",
        },
    },
    "cursor": {
        "name": "Cursor",
        "aliases": ["cursor"],
        "process": ["cursor.exe"],
        "cli": "cursor",
        "tips": ["操作方式與 VS Code 相同；寫檔用 `write_text_file`（open_in=\"cursor\"）。",
                 "要叫 Cursor 的 AI 做事用 `dispatch_ai_coding_prompt`（tool_hint=\"cursor\"）。"],
        "tasks": [
            {"id": "new_file_with_content", "title": "新增檔案並寫入內容",
             "keywords": ["新增", "建立", "寫", "檔案"],
             "steps": ["`write_text_file`：path、content，open_in=\"cursor\""]},
        ],
        "shortcuts": {"新增檔案": "ctrl+n", "存檔": "ctrl+s", "命令選擇區": "ctrl+shift+p", "AI 對話": "ctrl+l"},
    },
    "notepad": {
        "name": "記事本",
        "aliases": ["記事本", "notepad", "筆記本"],
        "process": ["notepad.exe"],
        "cli": "notepad",
        "tips": ["寫文字檔用 `write_text_file`（open_in=\"notepad\"），不要開空白記事本再打字。"],
        "tasks": [
            {"id": "new_file_with_content", "title": "建立文字檔",
             "keywords": ["新增", "建立", "寫", "記下", "存成"],
             "steps": ["`write_text_file`：path=完整 .txt 路徑，content=內容，open_in=\"notepad\""],
             "ui_fallback": "launch_application 開記事本 → type_text 內容 → computer_key ctrl+s → type_text 路徑 → computer_key enter"},
        ],
        "shortcuts": {"新增": "ctrl+n", "開啟": "ctrl+o", "存檔": "ctrl+s", "另存新檔": "ctrl+shift+s", "尋找": "ctrl+f", "取代": "ctrl+h"},
    },
    "explorer": {
        "name": "檔案總管",
        "aliases": ["檔案總管", "file explorer", "explorer.exe"],
        "process": ["explorer.exe"],
        "cli": "explorer",
        "tips": ["打開某個資料夾：`open_file_in_app`（path=資料夾，app=\"explorer\"）。",
                 "找檔案不要在總管裡點：用 `search_local_files`。",
                 "新增／移動／刪除檔案會請使用者同意；能用 `write_text_file` 就不要用 shell。"],
        "tasks": [
            {"id": "open_folder", "title": "打開資料夾", "keywords": ["打開", "開啟", "資料夾", "folder"],
             "steps": ["`open_file_in_app`：path=資料夾完整路徑，app=\"explorer\""]},
            {"id": "find_file", "title": "找檔案", "keywords": ["找", "搜尋", "在哪"],
             "steps": ["`search_local_files`：query=關鍵字"]},
        ],
        "shortcuts": {"新資料夾": "ctrl+shift+n", "網址列": "ctrl+l", "重新命名": "f2", "搜尋": "ctrl+e"},
    },
    "chrome": {
        "name": "Google Chrome",
        "aliases": ["chrome", "google chrome", "谷歌瀏覽器"],
        "process": ["chrome.exe"],
        "cli": "chrome",
        "tips": ["查資料用 `web_search` / `web_fetch`，不必真的開瀏覽器。",
                 "需要在網頁上點擊、填表才用 `browser_*` 工具（有自己的瀏覽器分頁，比操作使用者的 Chrome 穩）。"],
        "tasks": [
            {"id": "open_url", "title": "打開網址", "keywords": ["打開", "開啟", "網址", "網站", "http"],
             "steps": ["`browser_navigate`：url=網址"]},
            {"id": "search", "title": "搜尋資料", "keywords": ["搜尋", "查", "google"],
             "steps": ["`web_search`：query=關鍵字"]},
        ],
        "shortcuts": {"新分頁": "ctrl+t", "網址列": "ctrl+l", "重新整理": "f5", "關閉分頁": "ctrl+w", "尋找": "ctrl+f"},
    },
    "edge": {
        "name": "Microsoft Edge",
        "aliases": ["edge", "microsoft edge"],
        "process": ["msedge.exe"],
        "cli": "msedge",
        "tips": ["與 Chrome 相同：查資料用 `web_search`，操作網頁用 `browser_*`。"],
        "tasks": [],
        "shortcuts": {"新分頁": "ctrl+t", "網址列": "ctrl+l", "重新整理": "f5"},
    },
    "terminal": {
        "name": "終端機 / PowerShell",
        "aliases": ["終端機", "terminal", "powershell", "cmd", "命令提示字元", "windows terminal"],
        "process": ["windowsterminal.exe", "powershell.exe", "pwsh.exe", "cmd.exe"],
        "cli": "wt",
        "tips": ["要跑指令直接用 `run_background_shell`，不要開終端機視窗再打字。",
                 "取得路徑用環境變數就好，例如 `$env:USERPROFILE`，不要寫 `powershell -Command \"$env:USERPROFILE\"`（會把路徑當指令執行而報錯）。"],
        "tasks": [],
        "shortcuts": {},
    },
    "word": {
        "name": "Microsoft Word",
        "aliases": ["microsoft word", "winword", "word 文件", "word檔"],
        "process": ["winword.exe"],
        "cli": "winword",
        "tips": ["讀 .docx 內容用 `read_local_file`；開檔用 `open_file_in_app`（app=\"word\"）。"],
        "tasks": [
            {"id": "open_doc", "title": "開啟文件", "keywords": ["開啟", "打開", "docx"],
             "steps": ["`open_file_in_app`：path=.docx 路徑，app=\"word\""]},
            {"id": "new_doc_type", "title": "開新文件並輸入文字",
             "keywords": ["新增", "新文件", "開新", "空白文件", "輸入", "寫入", "打字", "打上"],
             "steps": ["Word 還沒開就先 `launch_application`（target=\"Word\"）",
                       "`type_in_app`：app=\"word\"，text=要輸入的文字，new_document=true（一步完成：切到 Word、Ctrl+N 開新文件、輸入）",
                       "使用者沒說要存檔就不要存檔"]},
        ],
        "shortcuts": {"新文件": "ctrl+n", "存檔": "ctrl+s", "另存新檔": "f12", "粗體": "ctrl+b", "尋找": "ctrl+f"},
    },
    "excel": {
        "name": "Microsoft Excel",
        "aliases": ["excel", "試算表"],
        "process": ["excel.exe"],
        "cli": "excel",
        "tips": ["產生簡單表格可先用 `write_text_file` 寫成 .csv，再 `open_file_in_app`（app=\"excel\"）開啟。"],
        "tasks": [
            {"id": "new_table", "title": "建立表格", "keywords": ["表格", "建立", "csv", "新增"],
             "steps": ["`write_text_file`：path=.csv 路徑，content=逗號分隔內容", "`open_file_in_app`：app=\"excel\""]},
        ],
        "shortcuts": {"新活頁簿": "ctrl+n", "存檔": "ctrl+s", "另存新檔": "f12", "尋找": "ctrl+f"},
    },
    "powerpoint": {
        "name": "Microsoft PowerPoint",
        "aliases": ["powerpoint", "ppt", "簡報"],
        "process": ["powerpnt.exe"],
        "cli": "powerpnt",
        "tips": ["開檔用 `open_file_in_app`（app=\"powerpoint\"）。"],
        "tasks": [],
        "shortcuts": {"新簡報": "ctrl+n", "新投影片": "ctrl+m", "開始放映": "f5", "存檔": "ctrl+s"},
    },
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _alias_hit(alias: str, t: str, t_nospace: str) -> bool:
    """英文別名要整個字比對（避免 knowledge 裡的 edge、vsc 之類誤判）；中文別名直接包含即可。"""
    a = _norm(alias)
    if not a:
        return False
    if re.fullmatch(r"[a-z0-9 .\-]+", a):
        for cand, src in ((a, t), (a.replace(" ", ""), t_nospace)):
            if re.search(rf"(?<![a-z0-9]){re.escape(cand)}(?![a-z0-9])", src):
                return True
        return False
    return a in t or a.replace(" ", "") in t_nospace


def find_apps(text: str) -> List[str]:
    """回傳文字中提到的所有軟體 key，依別名長度由長到短排序（越具體越前面）。"""
    t = _norm(text)
    if not t:
        return []
    t_nospace = t.replace(" ", "")
    scored = []
    for key, pb in PLAYBOOKS.items():
        lens = [len(a) for a in pb["aliases"] if _alias_hit(a, t, t_nospace)]
        if lens:
            scored.append((max(lens), key))
    scored.sort(key=lambda x: -x[0])
    return [k for _, k in scored]


def find_app(text: str) -> Optional[str]:
    """從一段文字（使用者要求或工具參數）找出提到的軟體 key；最長的別名優先。"""
    hits = find_apps(text)
    return hits[0] if hits else None


def get(app: str) -> Optional[Dict[str, Any]]:
    key = app if app in PLAYBOOKS else find_app(app)
    return PLAYBOOKS.get(key) if key else None


def match_task(app_key: str, text: str) -> Optional[Dict[str, Any]]:
    """依關鍵字找最符合的任務。只命中一個短字（例如單獨的「檔案」）不算數，
    避免「比較兩個檔案」被誤判成「新增檔案」；長關鍵字（3 字以上）算 2 分，門檻 2 分。"""
    pb = PLAYBOOKS.get(app_key)
    if not pb:
        return None
    t = _norm(text)
    scored = []
    for task in pb.get("tasks", []):
        score = sum(2 if len(_norm(k)) >= 3 else 1 for k in task.get("keywords", []) if _norm(k) in t)
        if score >= 2:
            scored.append((score, task))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def render(app_key: str, task_text: str = "", compact: bool = True) -> str:
    """把手冊整理成給模型看的文字。compact=True 時只放最相關的任務，省上下文。"""
    pb = PLAYBOOKS.get(app_key)
    if not pb:
        return ""
    lines = [f"#### 📘 {pb['name']} 操作手冊"]
    lines += [f"- {t}" for t in pb.get("tips", [])]
    tasks = pb.get("tasks", [])
    best = match_task(app_key, task_text) if task_text else None
    shown = [best] if (compact and best) else ([] if compact else tasks)
    for task in shown:
        lines.append(f"- 任務「{task['title']}」建議步驟：")
        lines += [f"  {i}. {s}" for i, s in enumerate(task["steps"], 1)]
        if task.get("ui_fallback"):
            lines.append(f"  （指令方式失敗才用 UI：{task['ui_fallback']}）")
    if pb.get("shortcuts"):
        sc = "、".join(f"{k} `{v}`" for k, v in list(pb["shortcuts"].items())[: (6 if compact else 99)])
        lines.append(f"- 快捷鍵：{sc}")
    return "\n".join(lines)
