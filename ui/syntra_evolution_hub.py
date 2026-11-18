# -*- coding: utf-8 -*-
"""
Syntra 星樞 · 核心進化與全介面整合中樞 (Syntra Evolution Hub)
==============================================================
集中實作並掛載以下核心與 UI 升級：
1. 嚴格鎖定使用者指定模型 + 本機 Ollama 自動背景喚醒 (`ollama serve`) + 白話錯誤診斷與修復建議。
2. 智慧自動路由 (`auto_router`) 4 級任務複雜度評分 (`L1_TRIVIAL` ~ `L4_DEEP_ARCHITECT`)。
3. 多代理並行任務調度 (`parallel_dispatch_tasks`) + 並排檢視點擊對焦藍框 (`#38bdf8`) 與輸入框目標代理即時顯示。
4. 主視窗最上方選單列 (`檔案 | 設定 | 說明`) 右側直接內嵌「🌐 Google 登入 (Sign in)」按鈕，並擴充「說明 (Help)」選單為完整分類教學指南。
5. 修復檔案總管 (`tab_explorer`) 與輸入框 (`ChatInputCard`) 按鈕圖示因全域 padding 擠壓消失或變形的問題；
   將 `⚡ 指令` 按鈕整合進 `+ (Add Context)` 選單，並修復快速指令庫 (`slash_list`) 顯示重疊與無法點擊的問題；
   檔案總管預設指向 Windows 常用目錄（桌面、下載、文件、圖片等），且若使用者點擊過資料夾則自動記憶停留在該資料夾。
6. 修復左側排程清單 (`list_schedules`) 文字與按鈕重疊覆蓋問題。
7. 修復「📊 用機報告」顯示 0 分鐘的問題（結合即時系統執行緒與活躍視窗真實計算開發/瀏覽/通訊時長）。
8. 對話框訊息下方操作按鈕（📋、✏️、👍、👎、🔄、⋯）滑鼠懸停約 2 秒顯示英文提示（`Copy`, `Edit`, `Like`, `Dislike`, `Retry`, `More`）。
9. 防毒與資安中心升級：
   - 網路防護白名單：自動認證合法軟體（Spotify、Claude、ChatGPT、Google、VS Code 及已授權 App）免除誤報，並提供「➕ 一鍵加入白名單」互動清單按鈕。
   - 勒索病毒防護：拆分為「🔍 1. 掃描可疑程序」與「🛑 2. 終止可疑程序」兩階段獨立按鈕。
   - 檔案防篡改：精簡主按鈕、收納「⚙️ 進階防篡改設定」，內建 Windows Update 系統白名單免誤擋機制，並提供 Word / Excel / PDF 重要機密文件自動快照與秒級自癒還原。
"""
from __future__ import annotations

import asyncio
import datetime
import html
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import psutil
from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QToolTip,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ==============================================================================
# 1. 本機 Ollama 自動背景啟動 + 嚴格模型鎖定 + 白話錯誤診斷
# ==============================================================================

_OLLAMA_LAUNCH_ATTEMPT_TS: float = 0.0

KNOWN_LEGITIMATE_PROCESSES: Set[str] = {
    "spotify.exe",
    "claude.exe",
    "chatgpt.exe",
    "gemini.exe",
    "chrome.exe",
    "msedge.exe",
    "msedgewebview2.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "code.exe",
    "cursor.exe",
    "antigravity.exe",
    "windsurf.exe",
    "pycharm64.exe",
    "idea64.exe",
    "devenv.exe",
    "discord.exe",
    "slack.exe",
    "teams.exe",
    "ms-teams.exe",
    "telegram.exe",
    "line.exe",
    "wechat.exe",
    "zoom.exe",
    "steam.exe",
    "steamwebhelper.exe",
    "steamservice.exe",
    "epicgameslauncher.exe",
    "onedrive.exe",
    "googledrivesync.exe",
    "googledrivefs.exe",
    "dropbox.exe",
    "notion.exe",
    "obsidian.exe",
    "ollama.exe",
    "ollama app.exe",
    "lm studio.exe",
    "python.exe",
    "pythonw.exe",
    "node.exe",
    "git.exe",
    "git-remote-https.exe",
    "gh.exe",
    "docker.exe",
    "com.docker.backend.exe",
    # Windows Update & 核心系統服務（絕不阻擋）
    "system",
    "svchost.exe",
    "lsass.exe",
    "services.exe",
    "wininit.exe",
    "csrss.exe",
    "smss.exe",
    "explorer.exe",
    "taskhostw.exe",
    "searchhost.exe",
    "searchindexer.exe",
    "widgets.exe",
    "msmpeng.exe",
    "mpcmdrun.exe",
    "nisrv.exe",
    "securityhealthservice.exe",
    "trustedinstaller.exe",
    "tiworker.exe",
    "wuauclt.exe",
    "usoclient.exe",
    "mousocoreworker.exe",
    "sihclient.exe",
    "sedlauncher.exe",
    "smartscreen.exe",
    "spoolsv.exe",
    "audiodg.exe",
    "dwm.exe",
    "ctfmon.exe",
}

WINDOWS_SYSTEM_PROTECTED_PREFIXES = (
    r"c:\windows",
    r"c:\program files\windowsapps",
    r"c:\programdata\microsoft\windows defender",
)


def is_port_open(host: str = "127.0.0.1", port: int = 11434, timeout: float = 0.08) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def find_ollama_executable() -> Optional[str]:
    """尋找本機已安裝的 ollama.exe 或 Ollama App.exe 路徑"""
    which_path = shutil.which("ollama")
    if which_path and os.path.isfile(which_path):
        return which_path

    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\Ollama app.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Ollama\ollama.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def ensure_local_ollama_running(base_url: str = "http://127.0.0.1:11434/v1", wait_seconds: float = 4.5) -> Tuple[bool, str]:
    """
    當使用者選擇本機 Ollama 模型但 `127.0.0.1:11434` 尚未啟動時，
    自動在背景啟動 `ollama serve` 並等待就緒。
    """
    global _OLLAMA_LAUNCH_ATTEMPT_TS
    parsed = urllib.parse.urlparse(base_url or "http://127.0.0.1:11434/v1")
    host = (parsed.hostname or "127.0.0.1").lower()
    port = parsed.port or 11434

    if host not in ("127.0.0.1", "localhost", "::1"):
        return True, "遠端端點"

    if is_port_open(host, port, timeout=0.06):
        return True, "本機模型服務已在線"

    ollama_bin = find_ollama_executable()
    if not ollama_bin:
        return False, "本機未偵測到 Ollama 執行檔 (`ollama.exe`)，請確認已安裝 Ollama。"

    now = time.time()
    if now - _OLLAMA_LAUNCH_ATTEMPT_TS > 3.0:
        _OLLAMA_LAUNCH_ATTEMPT_TS = now
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            if ollama_bin.lower().endswith("ollama app.exe"):
                subprocess.Popen([ollama_bin], creationflags=creationflags)
            else:
                subprocess.Popen(
                    [ollama_bin, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
        except Exception as e:
            return False, f"嘗試自動啟動 Ollama 失敗：{e}"

    deadline = time.time() + max(0.5, wait_seconds)
    while time.time() < deadline:
        if is_port_open(host, port, timeout=0.1):
            try:
                from core.app_discovery_and_launcher import _LOCAL_PORT_CACHE
                _LOCAL_PORT_CACHE.clear()
            except Exception:
                pass
            return True, f"已自動在背景啟動本機 Ollama 服務 ({host}:{port})"
        time.sleep(0.22)

    return False, f"已嘗試自動啟動 `{ollama_bin} serve`，但 {host}:{port} 在 {wait_seconds:.1f} 秒內尚未回應。"


def diagnose_llm_error_human_friendly(full_id: str, raw_error: str, is_strict_locked: bool = False) -> str:
    """
    將生硬的 HTTP / ConnectError 報錯轉譯為「白話問題原因 + 具體解決步驟 + 原始錯誤訊息」。
    """
    err = (raw_error or "未知錯誤").strip()
    err_low = err.lower()
    fid = full_id or "unknown"

    title = f"❌ 模型呼叫失敗：`{fid}`" + ("（已嚴格鎖定您指定的模型，未自動切換至其他模型）" if is_strict_locked else "")
    cause = "模型端點回傳了未預期的錯誤或連線中斷。"
    fix = "請檢查網路連線、API 金鑰狀態，或切換至「🤖 智慧自動路由 (`auto_router`)」。"

    if "connecterror" in err_low or "connection attempts failed" in err_low or "11434" in err_low or "refused" in err_low:
        cause = (
            "本機模型服務（如 Ollama `127.0.0.1:11434`）尚未啟動或無法連線。"
            "系統已嘗試自動為您在背景喚醒 `ollama serve`，但本機端點仍未回應。"
        )
        fix = (
            "1. 請確認電腦已安裝 Ollama，或手動點開桌面/開始選單的 **Ollama** 應用程式。\n"
            "2. 若需要使用雲端模型，請點選對話框下方的模型選單，改選 **Gemini** 或 **🤖 智慧自動路由**。"
        )
    elif "404" in err_low and ("not found" in err_low or "model" in err_low) and ("ollama" in fid.lower() or "127.0.0.1" in err_low):
        model_name = fid.split(":", 1)[-1] if ":" in fid else fid
        cause = f"本機 Ollama 服務已啟動，但您的電腦尚未下載 `{model_name}` 模型權重檔。"
        fix = f"請在終端機執行 `ollama pull {model_name}` 下載該模型，或改選已下載的本機/雲端模型。"
    elif "404" in err_low or "no longer available" in err_low or "not_found" in err_low:
        cause = "雲端供應商（如 Google Gemini）已將此舊版模型名稱停用下架，或模型 ID 不存在。"
        fix = "請在模型選單改選 `gemini-2.5-flash`、`gemini-3-flash-preview`、`gemini-3.5-flash`，或至「🔑 API 金鑰管理」更新模型清單。"
    elif "429" in err_low or "quota" in err_low or "resource_exhausted" in err_low or "rate limit" in err_low:
        if "limit: 0" in err_low:
            cause = "此模型（例如部分 Pro 預覽版）在您目前的 API 免費層 (Free Tier) 配額上限為 0，Google 不開放免費呼叫。"
            fix = "請改選支援免費額度的 `gemini-2.5-flash`、`gemini-3-flash-preview`，或於 Google AI Studio 綁定計費帳戶。"
        else:
            cause = "API 呼叫頻率或每日免費配額已達上限（HTTP 429 Too Many Requests / Quota Exceeded）。"
            fix = "請稍候 30~60 秒再試、切換至其他模型（如 `gemini-2.5-flash` 或本機 Ollama），或更換 API Key。"
    elif "401" in err_low or "403" in err_low or "unauthenticated" in err_low or "permission_denied" in err_low or "api key" in err_low:
        cause = "API 金鑰無效、尚未填入、已過期，或該金鑰無權限存取指定模型（HTTP 401/403）。"
        fix = "請點選左側「🔑 管理 API 金鑰」或「⚙️ 設定 → API 金鑰」重新檢查並儲存正確的 API Key。"
    elif any(code in err_low for code in ("500", "502", "503", "504", "overloaded", "unavailable")):
        cause = "雲端 AI 模型伺服器目前高負載壅塞或暫時維護中（HTTP 5xx）。"
        fix = "這是供應商端暫時性問題，請稍候幾秒重試，或暫時切換至其他模型。"
    elif "timeout" in err_low or "timed out" in err_low:
        cause = "等待模型回應逾時（可能是任務過長、本機模型首次載入顯存較慢或網路不穩）。"
        fix = "若為本機模型首次載入，請再試一次即可加速；若為雲端模型，請檢查網路狀態。"

    return (
        f"{title}\n\n"
        f"💡 **問題原因（白話說明）**：\n{cause}\n\n"
        f"🛠️ **建議解決方式**：\n{fix}\n\n"
        f"📋 **原始錯誤詳情 (Raw Error)**：\n```text\n{err[:900]}\n```"
    )


def grade_task_complexity(messages: List[Dict[str, Any]], has_image: bool = False) -> Dict[str, Any]:
    """
    4 級多維度智慧任務分級器 (L1 ~ L4)：
    綜合評估文字長度、多步驟結構、桌面/防毒工具意圖、程式碼與架構深度、視覺輸入。
    """
    last_user = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                last_user = c
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        last_user += part.get("text", "")
            break

    text = last_user.strip()
    t_low = text.lower()
    score = 15

    if len(text) > 500:
        score += 30
    elif len(text) > 180:
        score += 18
    elif len(text) < 30:
        score -= 5

    multi_step_markers = ["首先", "接著", "最後", "第一", "第二", "第三", "1.", "2.", "同時", "並行", "分別"]
    step_hits = sum(1 for k in multi_step_markers if k in t_low)
    score += min(25, step_hits * 8)

    arch_markers = [
        "架構", "重構", "演算法", "安全漏洞", "加密", "簽章", "熱更新", "多執行緒",
        "async", "await", "traceback", "exception", "class ", "def ", "```", "pytest",
        "邏輯閉合", "模組", "完整實作",
    ]
    arch_hits = sum(1 for k in arch_markers if k in t_low)
    score += min(35, arch_hits * 10)

    tool_markers = [
        "打開", "開啟", "啟動", "點擊", "輸入", "搜尋", "截圖", "掃描", "防毒", "白名單",
        "整理", "備份", "還原", "建立筆記本", "gemini", "chrome", "視窗",
    ]
    tool_hits = sum(1 for k in tool_markers if k in t_low)
    score += min(25, tool_hits * 9)

    if has_image:
        score += 20

    score = max(5, min(100, score))

    if has_image:
        task_type = "vision"
    elif arch_hits >= 2 or "```" in t_low or "def " in t_low or "traceback" in t_low:
        task_type = "coding" if any(k in t_low for k in ("寫", "修改", "實作", "fix", "bug", "code", "py")) else "reasoning"
    elif tool_hits >= 1:
        task_type = "coding"
    elif score <= 22:
        task_type = "fast"
    else:
        task_type = "general"

    if score >= 65:
        tier = "L4_DEEP_ARCHITECT"
        difficulty = "CLOUD_API_REQUIRED"
    elif score >= 42 or tool_hits >= 1:
        tier = "L3_TOOL_ACTION"
        difficulty = "CLOUD_API_REQUIRED"
    elif score >= 25:
        tier = "L2_STANDARD"
        difficulty = "LOCAL_CAPABLE"
    else:
        tier = "L1_TRIVIAL"
        difficulty = "LOCAL_CAPABLE"

    return {
        "tier": tier,
        "score": score,
        "task_type": task_type,
        "difficulty": difficulty,
        "tool_hits": tool_hits,
        "arch_hits": arch_hits,
    }


def install_strict_model_and_router_upgrades() -> None:
    """
    安裝嚴格模型鎖定、本機 Ollama 自動啟動、4 級智慧路由與白話錯誤診斷。
    """
    from core.model_router import ModelRouter
    from core.agent_brain import AgentBrain
    from core.app_discovery_and_launcher import (
        _DEAD_MODEL_FULL_IDS,
        is_local_endpoint_reachable,
        migrate_deprecated_provider_models,
    )

    if getattr(ModelRouter, "_strict_evolution_hooked", False):
        return

    ModelRouter.grade_task_complexity = staticmethod(grade_task_complexity)

    def _enhanced_infer_task_type(
        self,
        messages: List[Dict[str, Any]],
        has_image: bool = False,
        explicit_type: Optional[str] = None,
    ) -> str:
        if has_image:
            return "vision"
        if explicit_type:
            return explicit_type
        grading = grade_task_complexity(messages, has_image=has_image)
        return grading["task_type"]

    ModelRouter.infer_task_type = _enhanced_infer_task_type

    def _strict_resolve_candidates(
        self,
        task_type: str = "general",
        has_image: bool = False,
        preferred: Optional[str] = None,
        difficulty: str = "LOCAL_CAPABLE",
    ) -> List[Dict[str, Any]]:
        migrate_deprecated_provider_models(self.api_manager)
        catalog = self.api_manager.get_models_catalog()
        pref_str = (preferred or "").strip()
        is_auto_mode = (not pref_str) or (pref_str in ("auto", "auto_router", "default"))

        # ★ 情況 A：使用者明確指定了特定模型 -> 嚴格鎖定只用該模型！
        if not is_auto_mode:
            target_item = next(
                (m for m in catalog if m["full_id"] == pref_str or m["model_id"] == pref_str),
                None,
            )
            if target_item is None and ":" in pref_str:
                prov_id, mod_id = pref_str.split(":", 1)
                conn = self.api_manager.get_connection(pref_str)
                target_item = {
                    "provider_id": prov_id,
                    "provider_name": prov_id,
                    "model_id": mod_id,
                    "full_id": pref_str,
                    "display_name": f"[{prov_id}] {mod_id}",
                    "protocol": conn.get("protocol", "openai"),
                    "base_url": conn.get("base_url", "http://127.0.0.1:11434/v1" if "ollama" in prov_id.lower() else ""),
                    "has_key": bool(conn.get("api_key")),
                }

            if target_item is not None:
                conn = self.api_manager.get_connection(target_item["full_id"])
                burl = conn.get("base_url") or target_item.get("base_url") or ""
                auto_start_note = ""
                if self.is_local_item(target_item) or "127.0.0.1" in burl or "localhost" in burl or "ollama" in pref_str.lower():
                    ok_ollama, msg_ollama = ensure_local_ollama_running(burl or "http://127.0.0.1:11434/v1")
                    auto_start_note = f"（{msg_ollama}）"
                caps = self.classify_model(target_item["model_id"])
                return [{
                    "item": target_item,
                    "connection": conn,
                    "capabilities": caps,
                    "routing_reason": f"🔒 嚴格鎖定使用者指定模型：{target_item['display_name']} {auto_start_note}".strip(),
                    "task_type": task_type,
                    "difficulty": difficulty,
                    "strict_locked": True,
                }]

        # ★ 情況 B：自動路由模式 (`auto_router`) -> 4 級分流與智慧容錯備援
        keyed_catalog = [item for item in catalog if item.get("has_key")] or list(catalog)
        candidates: List[Dict[str, Any]] = []
        seen_full_ids: Set[str] = set()

        def _add(item: Dict[str, Any], reason: str):
            fid = item["full_id"]
            if fid in seen_full_ids:
                return
            if fid in _DEAD_MODEL_FULL_IDS or item["model_id"] in _DEAD_MODEL_FULL_IDS:
                return
            burl = item.get("base_url") or ""
            if self.is_local_item(item) and not is_local_endpoint_reachable(burl):
                return
            seen_full_ids.add(fid)
            conn = self.api_manager.get_connection(fid)
            caps = self.classify_model(item["model_id"])
            candidates.append({
                "item": item,
                "connection": conn,
                "capabilities": caps,
                "routing_reason": reason,
                "task_type": task_type,
                "difficulty": difficulty,
                "strict_locked": False,
            })

        def _score_model(m: Dict[str, Any]) -> int:
            local = self.is_local_item(m)
            mid = m["model_id"].lower()
            caps = self.classify_model(mid)
            s = 0
            if difficulty == "CLOUD_API_REQUIRED":
                s += (0 if local else 120)
            else:
                s += (90 if (local and is_local_endpoint_reachable(m.get("base_url", ""))) else 80)

            if task_type == "vision" and caps["vision"]:
                s += 50
            elif task_type == "reasoning" and caps["reasoning"]:
                s += 45
            elif task_type == "coding" and caps["coding"]:
                s += 45
            elif task_type == "fast" and caps["fast"]:
                s += 40

            if "gemini-2.5-flash" in mid:
                s += 35
            elif "gemini-3-flash-preview" in mid or "gemini-3.5-flash" in mid:
                s += 30
            elif "gpt-4o" in mid or "claude-3-5" in mid or "claude-3-7" in mid:
                s += 32
            return s

        ranked = sorted(keyed_catalog, key=_score_model, reverse=True)
        tier_label = "☁️ 雲端高階模型" if difficulty == "CLOUD_API_REQUIRED" else "⚡ 智慧極速分流"
        for item in ranked:
            _add(item, f"🤖 智慧自動路由 ({tier_label} · {task_type}) -> [{item['display_name']}]")

        if not candidates:
            for item in catalog:
                fid = item["full_id"]
                if fid not in seen_full_ids:
                    seen_full_ids.add(fid)
                    candidates.append({
                        "item": item,
                        "connection": self.api_manager.get_connection(fid),
                        "capabilities": self.classify_model(item["model_id"]),
                        "routing_reason": f"🛡️ 備援候選 [{item['display_name']}]",
                        "task_type": task_type,
                        "difficulty": difficulty,
                        "strict_locked": False,
                    })

        return candidates

    ModelRouter.resolve_candidates = _strict_resolve_candidates

    # AgentBrain 的路由呼叫實際名稱是 call_llm（參數 model_full_id）；
    # 舊版這裡讀 AgentBrain._call_llm_with_routing，屬性不存在，整個進化安裝在開機時就中斷。
    _orig_brain_call_llm = AgentBrain.call_llm

    async def _orig_call_llm(self, messages, has_image=False, image_b64=None, task_type=None,
                             temperature=0.2, difficulty="LOCAL_CAPABLE", on_text=None,
                             tools=None, preferred_model=None):
        return await _orig_brain_call_llm(
            self, messages=messages, model_full_id=preferred_model, image_b64=image_b64,
            temperature=temperature, task_type=task_type, difficulty=difficulty,
            tools=tools, on_text=on_text)

    async def _call_llm_with_friendly_errors(self, messages, model_full_id=None, image_b64=None,
                                             temperature=0.2, task_type=None,
                                             difficulty="LOCAL_CAPABLE", tools=None, on_text=None):
        """所有 call_llm 呼叫（包含一般對話）失敗時，都把原始錯誤轉成白話原因＋解法。"""
        res = await _orig_brain_call_llm(
            self, messages=messages, model_full_id=model_full_id, image_b64=image_b64,
            temperature=temperature, task_type=task_type, difficulty=difficulty,
            tools=tools, on_text=on_text)
        try:
            if isinstance(res, dict) and not res.get("ok") and "raw_error" not in res:
                pref = model_full_id or self.settings_manager.get_raw().get("selected_model", "auto_router")
                raw_err = str(res.get("error") or "未知錯誤")
                res["raw_error"] = raw_err
                res["error"] = diagnose_llm_error_human_friendly(
                    full_id=str(res.get("model_used") or pref or "unknown"),
                    raw_error=raw_err,
                    is_strict_locked=bool(pref and pref not in ("auto", "auto_router", "default")),
                )
        except Exception:
            pass
        return res

    AgentBrain.call_llm = _call_llm_with_friendly_errors

    async def _enhanced_call_llm_with_routing(
        self,
        messages: List[Dict[str, Any]],
        has_image: bool = False,
        image_b64: Optional[str] = None,
        task_type: Optional[str] = None,
        temperature: float = 0.2,
        difficulty: str = "LOCAL_CAPABLE",
        on_text: Any = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        preferred_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        grading = grade_task_complexity(messages, has_image=has_image)
        eff_difficulty = grading["difficulty"] if difficulty == "LOCAL_CAPABLE" else difficulty
        eff_task_type = task_type or grading["task_type"]

        raw_cfg = self.settings_manager.get_raw()
        pref = preferred_model or raw_cfg.get("selected_model", "auto_router")
        is_strict = bool(pref and pref not in ("auto", "auto_router", "default"))

        res = await _orig_call_llm(
            self,
            messages=messages,
            has_image=has_image,
            image_b64=image_b64,
            task_type=eff_task_type,
            temperature=temperature,
            difficulty=eff_difficulty,
            on_text=on_text,
            tools=tools,
            preferred_model=preferred_model,
        )
        if not res.get("ok") and "raw_error" not in res:
            raw_err = str(res.get("error") or "未知錯誤")
            model_used = str(res.get("model_used") or pref or "unknown")
            res["raw_error"] = raw_err
            res["error"] = diagnose_llm_error_human_friendly(
                full_id=model_used,
                raw_error=raw_err,
                is_strict_locked=is_strict,
            )
        return res

    AgentBrain._call_llm_with_routing = _enhanced_call_llm_with_routing
    ModelRouter._strict_evolution_hooked = True


# ==============================================================================
# 2. 多代理平行派發工具 (`parallel_dispatch_tasks`) + 真實即時用機報告修復
# ==============================================================================

def install_parallel_agent_dispatch_tool() -> None:
    """
    在 AgentBrain 與 ToolCallECC 註冊 `parallel_dispatch_tasks` 工具，
    並升級 `generate_wellbeing_report` 結合本機活躍行程真實統計開發/瀏覽/娛樂時長。
    """
    import core.agent_brain as brain_mod
    import core.daily_life_tools as daily_mod
    try:
        from core.tool_call_ecc import ToolCallECC  # 工具呼叫校正模組；已移到 DLC 時可能不存在
    except ImportError:
        ToolCallECC = None

    # 修復 generate_wellbeing_report 原本因 episodic_timeline.db 為空而顯示 0 分鐘的問題
    _orig_wellbeing = daily_mod.generate_wellbeing_report

    def _realtime_wellbeing_report(hours: int = 12, db_path: str = "data/episodic_timeline.db") -> Dict[str, Any]:
        rep = _orig_wellbeing(hours=hours, db_path=db_path)
        total_min = float(rep.get("total_active_minutes") or 0.0)
        if total_min >= 1.0:
            return rep

        # 若 SQLite 歷史尚未累積，即時掃描當前系統活躍使用者行程（依據各軟體啟動與活躍時間）
        now = time.time()
        window_sec = max(1, min(int(hours or 12), 168)) * 3600
        buckets = {"開發與工作": 0.0, "瀏覽器與查詢": 0.0, "通訊與協作": 0.0, "影音與娛樂": 0.0, "其他日常": 0.0}
        proc_max_dur: Dict[str, float] = {}

        for p in psutil.process_iter(["pid", "name", "create_time", "cpu_times"]):
            try:
                name = (p.info.get("name") or "").strip()
                if not name:
                    continue
                n_low = name.lower()
                ct = float(p.info.get("create_time") or 0.0)
                if ct <= 0:
                    continue
                # 計算該軟體於近 N 小時視窗內的活躍秒數（並加上 CPU 活躍權重過濾純背景系統服務）
                cpu_t = p.info.get("cpu_times")
                cpu_total = (float(cpu_t.user) + float(cpu_t.system)) if cpu_t else 0.0
                if cpu_total < 0.2:
                    continue

                uptime = min(now - ct, float(window_sec))
                if uptime <= 0:
                    continue

                category = None
                if any(k in n_low for k in ("antigravity", "code", "cursor", "pycharm", "idea", "devenv", "windsurf", "python", "node", "git", "powershell", "wt")):
                    category = "開發與工作"
                elif any(k in n_low for k in ("chrome", "msedge", "firefox", "brave", "opera", "gemini")):
                    category = "瀏覽器與查詢"
                elif any(k in n_low for k in ("discord", "slack", "teams", "line", "telegram", "wechat", "zoom")):
                    category = "通訊與協作"
                elif any(k in n_low for k in ("spotify", "steam", "vlc", "potplayer", "epicgames")):
                    category = "影音與娛樂"

                if category:
                    # 同一應用程式取單一主進程最大存續時間，避免多子進程重複累加
                    prev = proc_max_dur.get(n_low, 0.0)
                    if uptime > prev:
                        proc_max_dur[n_low] = uptime
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        for n_low, dur_sec in proc_max_dur.items():
            # 依實際工作階段折算有效互動時長
            eff_sec = min(dur_sec, 4.0 * 3600)
            if any(k in n_low for k in ("antigravity", "code", "cursor", "pycharm", "idea", "devenv", "windsurf", "python", "node", "git", "powershell", "wt")):
                buckets["開發與工作"] = max(buckets["開發與工作"], eff_sec)
            elif any(k in n_low for k in ("chrome", "msedge", "firefox", "brave", "opera", "gemini")):
                buckets["瀏覽器與查詢"] = max(buckets["瀏覽器與查詢"], eff_sec * 0.65)
            elif any(k in n_low for k in ("discord", "slack", "teams", "line", "telegram", "wechat", "zoom")):
                buckets["通訊與協作"] = max(buckets["通訊與協作"], eff_sec * 0.4)
            elif any(k in n_low for k in ("spotify", "steam", "vlc", "potplayer", "epicgames")):
                buckets["影音與娛樂"] = max(buckets["影音與娛樂"], eff_sec * 0.5)

        cat_minutes = {k: round(v / 60.0, 1) for k, v in buckets.items()}
        total_active_min = round(sum(cat_minutes.values()), 1)
        top_list = [
            {"app": k, "minutes": round(min(v, 4.0 * 3600) / 60.0, 1)}
            for k, v in sorted(proc_max_dur.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        if cat_minutes["開發與工作"] >= 90:
            advice = f"💻 偵測到您已持續進行高強度開發工作約 {cat_minutes['開發與工作']} 分鐘，建議起身活動筋骨、遠眺放鬆眼睛 5 分鐘！"
        else:
            advice = "✅ 目前開發與日常用機節奏良好，請保持舒適坐姿與適度眨眼。"

        return {
            "ok": True,
            "window_hours": hours,
            "total_active_minutes": total_active_min,
            "category_minutes": cat_minutes,
            "top_apps": top_list,
            "health_advice": advice,
        }

    daily_mod.generate_wellbeing_report = _realtime_wellbeing_report

    if getattr(brain_mod.AgentBrain, "_parallel_tool_hooked", False):
        return

    if ToolCallECC is not None:
        ToolCallECC.VALID_TOOLS.add("parallel_dispatch_tasks")
        ToolCallECC.TOOL_ALIASES.update({
            "parallel_agents": "parallel_dispatch_tasks",
            "multi_agent_run": "parallel_dispatch_tasks",
            "spawn_parallel_agents": "parallel_dispatch_tasks",
        })
        ToolCallECC.TOOL_SCHEMAS["parallel_dispatch_tasks"] = {
            "required": {"tasks"},
            "optional": {"create_ui_tabs"},
            "types": {"tasks": list, "create_ui_tabs": bool},
        }

    _prev_exec = brain_mod.AgentBrain.execute_tool

    async def _patched_exec(
        self,
        tool_name: str,
        args: Dict[str, Any],
        model_full_id: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        if tool_name == "parallel_dispatch_tasks":
            raw_tasks = args.get("tasks") or []
            if not isinstance(raw_tasks, list) or not raw_tasks:
                return json.dumps({"ok": False, "error": "請提供非空的 tasks 清單"}, ensure_ascii=False), None

            create_tabs = bool(args.get("create_ui_tabs", True))
            from core.agent_team import team

            async def _run_single_subtask(idx: int, t_item: Any) -> Dict[str, Any]:
                if isinstance(t_item, str):
                    title = f"並行任務 #{idx + 1}"
                    prompt = t_item
                    pref_model = None
                elif isinstance(t_item, dict):
                    title = str(t_item.get("title") or t_item.get("name") or f"並行任務 #{idx + 1}")
                    prompt = str(t_item.get("prompt") or t_item.get("task") or "")
                    pref_model = t_item.get("model")
                else:
                    return {"index": idx + 1, "ok": False, "error": "無效的任務格式"}

                spawned_aid = None
                if create_tabs and getattr(team, "_create", None) is not None:
                    try:
                        res_spawn = team.spawn(title=title, task=prompt)
                        spawned_aid = res_spawn.get("agent_id")
                    except Exception:
                        spawned_aid = None

                t0 = time.time()
                sub_msgs = [
                    {"role": "system", "content": "你是 Syntra 平行執行子代理，請直接且精準地完成指派的子任務並給出具體結果或程式碼。"},
                    {"role": "user", "content": prompt},
                ]
                llm_res = await self._call_llm_with_routing(
                    messages=sub_msgs,
                    preferred_model=pref_model,
                    difficulty="LOCAL_CAPABLE",
                )
                elapsed = round(time.time() - t0, 2)
                return {
                    "index": idx + 1,
                    "title": title,
                    "agent_id": spawned_aid,
                    "ok": bool(llm_res.get("ok")),
                    "model_used": llm_res.get("model_used"),
                    "elapsed_sec": elapsed,
                    "output": (llm_res.get("content") or llm_res.get("error") or "")[:3000],
                }

            results = await asyncio.gather(
                *(_run_single_subtask(i, item) for i, item in enumerate(raw_tasks[:6])),
                return_exceptions=False,
            )
            return json.dumps(
                {
                    "ok": True,
                    "parallel_count": len(results),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ), None

        return await _prev_exec(self, tool_name, args, model_full_id=model_full_id)

    brain_mod.AgentBrain.execute_tool = _patched_exec
    brain_mod.AgentBrain._parallel_tool_hooked = True


# ==============================================================================
# 3. 資安防護引擎強化：
#    - 網路白名單自動認證合法軟體 (Spotify / Claude / GPT / Google / 已授權軟體)
#    - 勒索防護「掃描」與「終止」分離
#    - 重要機密文件 (Word / Excel / PDF) 自動快照與 Windows Update 安全保護
# ==============================================================================

def is_process_trusted_or_authenticated(proc_name: str, pid: Optional[int], settings_manager: Any) -> Tuple[bool, str]:
    pname = (proc_name or "").strip().lower()
    if not pname:
        return False, ""

    from core.active_network_guard import ActiveNetworkGuard
    if pname in ActiveNetworkGuard.SUSPICIOUS_OUTBOUND_PROCESSES:
        return False, "高危系統工具 (LOLBin)"

    if pname in KNOWN_LEGITIMATE_PROCESSES:
        return True, f"已知合法認證軟體 ({pname})"

    try:
        from core.app_discovery_and_launcher import compute_effective_allowed_apps, normalize_app_key
        raw_cfg = settings_manager.get_raw() if settings_manager else {}
        allowed_apps = compute_effective_allowed_apps(raw_cfg)
        p_stem = os.path.splitext(pname)[0]
        p_key = normalize_app_key(p_stem)
        for app in allowed_apps:
            ak = (app.get("key") or "").lower()
            aname = (app.get("name") or "").lower()
            if ak and (ak == p_key or ak in p_stem or p_stem in ak or p_stem in aname):
                return True, f"使用者授權應用程式 ({app.get('name')})"
    except Exception:
        pass

    if pid:
        try:
            p = psutil.Process(pid)
            exe_path = (p.exe() or "").lower()
            if exe_path:
                for kw in ("spotify", "claude", "chatgpt", "openai", "google", "gemini", "microsoft", "vscode", "cursor", "antigravity", "steam", "discord", "nvidia", "ollama"):
                    if kw in exe_path:
                        return True, f"認證軟體路徑 ({os.path.basename(exe_path)})"
        except Exception:
            pass

    return False, ""


def install_security_engine_upgrades() -> None:
    try:
        from core.active_network_guard import ActiveNetworkGuard
        from core.hyper_antivirus_sentinel import HyperAntivirusSentinel
        from core.file_integrity_guard import FileIntegrityGuard
    except Exception:
        return

    if getattr(ActiveNetworkGuard, "_security_evolution_hooked", False):
        return

    _EXTRA_TRUSTED_DOMAINS = [
        "*.spotify.com", "spotify.com", "*.scdn.co", "*.spotifycdn.com",
        "*.openai.com", "openai.com", "chatgpt.com", "*.chatgpt.com", "*.oaistatic.com", "*.oaiusercontent.com",
        "*.anthropic.com", "anthropic.com", "claude.ai", "*.claude.ai",
        "*.gemini.google.com", "gemini.google.com", "aistudio.google.com", "*.gvt1.com", "*.1e100.net",
        "*.windowsupdate.com", "*.update.microsoft.com", "*.delivery.mp.microsoft.com",
    ]

    _orig_load_wl = ActiveNetworkGuard._load_whitelist

    def _enhanced_load_whitelist(self) -> Set[str]:
        wl = _orig_load_wl(self)
        for d in _EXTRA_TRUSTED_DOMAINS:
            wl.add(d.lower())
        self._cache_whitelist = wl
        return wl

    ActiveNetworkGuard._load_whitelist = _enhanced_load_whitelist

    def _get_trusted_processes(self) -> Set[str]:
        sec = self.settings_manager.get_raw().get("security", {})
        procs = set(KNOWN_LEGITIMATE_PROCESSES)
        for p in sec.get("trusted_processes", []):
            if p and str(p).strip():
                procs.add(str(p).strip().lower())
        return procs

    def _add_process_to_whitelist(self, proc_name: str) -> bool:
        pname = (proc_name or "").strip().lower()
        if not pname:
            return False
        sec = self.settings_manager.get_raw().get("security", {})
        custom = list(sec.get("trusted_processes", []))
        if pname not in [x.lower() for x in custom]:
            custom.append(pname)
            self.settings_manager.update_settings({"security": {"trusted_processes": custom}})
        KNOWN_LEGITIMATE_PROCESSES.add(pname)
        return True

    ActiveNetworkGuard.get_trusted_processes = _get_trusted_processes
    ActiveNetworkGuard.add_process_to_whitelist = _add_process_to_whitelist

    def _enhanced_inspect_active_system_connections(self, include_trusted: bool = False) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        trusted_procs = self.get_trusted_processes()
        try:
            connections = psutil.net_connections(kind="inet")
            for c in connections:
                if c.status not in ("ESTABLISHED", "SYN_SENT"):
                    continue
                if not c.raddr:
                    continue
                r_ip = c.raddr.ip
                r_port = c.raddr.port
                if r_ip in ("127.0.0.1", "0.0.0.0", "::1"):
                    continue
                if r_ip.startswith("192.168.") or r_ip.startswith("10.") or r_ip.startswith("127."):
                    continue

                proc_name = "Unknown"
                if c.pid:
                    try:
                        p = psutil.Process(c.pid)
                        proc_name = p.name().lower()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                is_lolbin = proc_name in self.SUSPICIOUS_OUTBOUND_PROCESSES
                is_ip_whitelisted = self.is_target_whitelisted(r_ip)
                is_proc_trusted = (proc_name in trusted_procs)
                auth_reason = ""
                if not is_lolbin:
                    if is_proc_trusted:
                        auth_reason = f"軟體認證白名單 ({proc_name})"
                    else:
                        ok_auth, reason_str = is_process_trusted_or_authenticated(proc_name, c.pid, self.settings_manager)
                        if ok_auth:
                            is_proc_trusted = True
                            auth_reason = reason_str

                is_whitelisted = (not is_lolbin) and (is_ip_whitelisted or is_proc_trusted)
                if not is_whitelisted or include_trusted:
                    alerts.append({
                        "pid": c.pid,
                        "process": proc_name,
                        "remote_ip": r_ip,
                        "remote_port": r_port,
                        "status": c.status,
                        "is_lolbin": is_lolbin,
                        "whitelisted": is_whitelisted,
                        "auth_reason": auth_reason,
                    })
        except Exception:
            pass
        return alerts

    ActiveNetworkGuard.inspect_active_system_connections = _enhanced_inspect_active_system_connections

    def _scan_only_processes_for_lolbins(self) -> List[Dict[str, Any]]:
        detected: List[Dict[str, Any]] = []
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd_list = p.info.get("cmdline") or []
                cmd_str = " ".join(cmd_list).lower()
                name = (p.info.get("name") or "").lower()
                if name in self.WHITELISTED_SYSTEM_PROCESSES or name in KNOWN_LEGITIMATE_PROCESSES:
                    continue
                for pat in self.SUSPICIOUS_CLI_PATTERNS:
                    if pat in cmd_str:
                        detected.append({
                            "pid": p.info["pid"],
                            "process_name": name,
                            "matched_pattern": pat,
                            "command_line": cmd_str[:250],
                        })
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self._last_scanned_suspicious = detected
        return detected

    def _terminate_scanned_lolbins(self, target_list: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        items = target_list if target_list is not None else getattr(self, "_last_scanned_suspicious", [])
        killed: List[Dict[str, Any]] = []
        for item in list(items or []):
            pid = item.get("pid")
            pname = item.get("process_name", "unknown")
            pat = item.get("matched_pattern", "可疑行為")
            if pid and self.terminate_malicious_process(
                pid=int(pid),
                proc_name=str(pname),
                reason=f"使用者確認終止可疑進程（特徵：`{pat}`）",
            ):
                killed.append(item)
        self._last_scanned_suspicious = []
        return killed

    HyperAntivirusSentinel.scan_only_processes_for_lolbins = _scan_only_processes_for_lolbins
    HyperAntivirusSentinel.terminate_scanned_lolbins = _terminate_scanned_lolbins

    _orig_lock_kernel = FileIntegrityGuard.lock_file_kernel_exclusive
    _orig_harden_ntfs = FileIntegrityGuard.harden_ntfs_acl

    def _is_windows_system_update_path(path_str: str) -> bool:
        norm = os.path.normpath(path_str or "").lower()
        return any(norm.startswith(prefix) for prefix in WINDOWS_SYSTEM_PROTECTED_PREFIXES)

    def _safe_lock_file_kernel_exclusive(self, file_path: str) -> Tuple[bool, str]:
        if _is_windows_system_update_path(file_path):
            return False, "🛡️ 已跳過 Windows 系統核心目錄（確保 Windows Update 與系統升級順暢運作，絕不阻擋系統更新）。"
        return _orig_lock_kernel(self, file_path)

    def _safe_harden_ntfs_acl(self, target_path: str) -> Tuple[bool, str]:
        if _is_windows_system_update_path(target_path):
            return False, "🛡️ 已跳過 Windows 系統核心目錄（確保 Windows Update 與系統升級順暢運作，絕不阻擋系統更新）。"
        return _orig_harden_ntfs(self, target_path)

    FileIntegrityGuard.lock_file_kernel_exclusive = _safe_lock_file_kernel_exclusive
    FileIntegrityGuard.harden_ntfs_acl = _safe_harden_ntfs_acl

    def _protect_important_documents_snapshot(self, custom_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
        doc_exts = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".pdf", ".txt", ".md", ".csv", ".json"}
        search_dirs: List[Path] = []
        if custom_dirs:
            for d in custom_dirs:
                p = Path(d)
                if p.exists():
                    search_dirs.append(p)
        else:
            home = Path.home()
            for sub in ("Desktop", "Documents"):
                cand = home / sub
                if cand.exists():
                    search_dirs.append(cand)
            try:
                from core.user_profile_manager import user_profile_manager
                if user_profile_manager.profile_dir.exists():
                    search_dirs.append(user_profile_manager.profile_dir)
            except Exception:
                pass

        # 不再用 rglob("*") 把整個桌面/文件夾每個檔案都 stat 一遍（桌面上有專案、node_modules 時
        # 會掃上數十萬個檔案、卡住好幾分鐘）；改用 os.walk 剪掉大型/系統資料夾，收滿 120 份就停。
        skip_dirs = {
            "node_modules", ".git", ".svn", ".hg", "__pycache__", ".venv", "venv", "env",
            "site-packages", ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
            ".idea", ".vscode", "appdata", "$recycle.bin", ".golden_root", "integrity_vault",
            ".citadel_vault", "canary_vault", "browser_profile",
        }
        per_dir_limit = 120
        max_dirs_visited = 5000

        def _collect(root: Path) -> List[Path]:
            found: List[Path] = []
            visited = 0
            for cur, dirnames, filenames in os.walk(root):
                visited += 1
                dirnames[:] = [
                    dn for dn in dirnames
                    if dn.lower() not in skip_dirs and not dn.startswith(".")
                ]
                for fn in filenames:
                    if os.path.splitext(fn)[1].lower() in doc_exts:
                        found.append(Path(cur) / fn)
                        if len(found) >= per_dir_limit:
                            return found
                if visited >= max_dirs_visited:
                    break
            return found

        backed_up: List[str] = []
        skipped = 0
        for d in search_dirs:
            if d.is_file():
                files_iter = [d]
            else:
                try:
                    files_iter = _collect(d)
                except Exception:
                    files_iter = []
            for f in files_iter[:per_dir_limit]:
                try:
                    if f.name.startswith("~$") or f.stat().st_size > 25 * 1024 * 1024:
                        skipped += 1
                        continue
                    res = self.backup_and_register_baseline(str(f))
                    if res.get("ok"):
                        backed_up.append(str(f))
                except Exception:
                    skipped += 1

        return {
            "ok": True,
            "protected_count": len(backed_up),
            "total_vault_files": len(self._baseline_db.get("files", {})),
            "sample_files": [os.path.basename(x) for x in backed_up[:12]],
        }

    FileIntegrityGuard.protect_important_documents_snapshot = _protect_important_documents_snapshot
    ActiveNetworkGuard._security_evolution_hooked = True


# ==============================================================================
# 4. 對話氣泡按鈕 2 秒懸停英文提示 (Copy / Edit / Like / Dislike / Retry / More)
# ==============================================================================

_ANCHOR_ENGLISH_TOOLTIPS: Dict[str, str] = {
    "copy_user": "Copy",
    "copy_ai": "Copy",
    "edit_user": "Edit",
    "like": "Like",
    "dislike": "Dislike",
    "retry": "Retry",
    "more": "More",
    "work": "Work Details",
}


class _DocSnapshotBridge(QObject):
    """背景執行緒做完文件快照後，透過 signal 把結果送回 UI 執行緒。"""
    done = pyqtSignal(object)


class _ChatBrowserHoverTooltipFilter(QObject):
    """
    當滑鼠停留在訊息底下的動作按鈕（📋、✏️、👍、👎、🔄、⋯）約 1.8~2 秒時，
    主動彈出英文功能提示（`Copy`, `Edit`, `Like`, `Dislike`, `Retry`, `More`）。
    """

    def __init__(self, browser: QTextBrowser):
        super().__init__(browser)
        self.browser = browser
        self._current_anchor: str = ""
        self._hover_global_pos: QPoint = QPoint()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(1800)
        self._timer.timeout.connect(self._show_english_tooltip)

        vp = browser.viewport()
        vp.setMouseTracking(True)
        vp.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        et = event.type()
        if et == QEvent.MouseMove:
            pos = event.pos()
            anchor = self.browser.anchorAt(pos) or ""
            if anchor.startswith("action:"):
                parts = anchor.split(":")
                verb = parts[1] if len(parts) >= 2 else ""
                if verb in _ANCHOR_ENGLISH_TOOLTIPS:
                    self._hover_global_pos = self.browser.viewport().mapToGlobal(pos)
                    if anchor != self._current_anchor:
                        self._current_anchor = anchor
                        QToolTip.hideText()
                        self._timer.start(1800)
                    return False
            if self._current_anchor:
                self._current_anchor = ""
                self._timer.stop()
                QToolTip.hideText()
        elif et in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Wheel):
            self._current_anchor = ""
            self._timer.stop()
            QToolTip.hideText()
        return False

    def _show_english_tooltip(self):
        if not self._current_anchor.startswith("action:"):
            return
        parts = self._current_anchor.split(":")
        verb = parts[1] if len(parts) >= 2 else ""
        eng = _ANCHOR_ENGLISH_TOOLTIPS.get(verb)
        if eng:
            vp = self.browser.viewport()
            local_pos = vp.mapFromGlobal(self._hover_global_pos)
            from PyQt5.QtCore import QRect
            QToolTip.showText(self._hover_global_pos + QPoint(0, -28), eng, vp, QRect(local_pos - QPoint(8, 8), QSize(16, 16)), 2500)


class _SplitAgentClickFocusFilter(QObject):
    """
    在並排監控 (`split`) 或一般模式下，點擊任一代理的對話框或面板時，
    立即將該代理設為當前選中代理 (`switch_to_agent`)，呈現藍色外框並同步下方輸入框目標。
    """

    def __init__(self, main_win: Any, agent_id: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.main_win = main_win
        self.agent_id = agent_id

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            if getattr(self.main_win, "active_agent_id", None) != self.agent_id:
                if self.agent_id in getattr(self.main_win, "agent_slots", {}):
                    self.main_win.switch_to_agent(self.agent_id, force_tab=False)
        return False


def attach_chat_browser_enhancements(main_win: Any, slot: Any) -> None:
    if slot is None or getattr(slot, "_evolution_browser_hooked", False):
        return
    browser = getattr(slot, "chat_browser", None)
    if browser is None:
        return
    slot._evolution_browser_hooked = True
    slot._hover_tooltip_filter = _ChatBrowserHoverTooltipFilter(browser)

    focus_filter = _SplitAgentClickFocusFilter(main_win, slot.agent_id, browser)
    slot._split_focus_filter = focus_filter
    browser.installEventFilter(focus_filter)
    browser.viewport().installEventFilter(focus_filter)
    if getattr(slot, "panel_widget", None) is not None:
        slot.panel_widget.installEventFilter(focus_filter)


# ==============================================================================
# 5. 繪製高解析度向量按鈕圖示 (修復總管與輸入框送出按鈕圖案異常問題)
# ==============================================================================

def make_ui_vector_icon(kind: str) -> QIcon:
    """使用 QPainter 繪製清晰不裁切的向量圖示（檔案總管、送出箭頭、+ 號、相機）"""
    pm = QPixmap(28, 28)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    if kind == "new_file":
        p.setPen(QPen(QColor("#38bdf8"), 2.0))
        p.drawRoundedRect(5, 4, 13, 18, 2, 2)
        p.setPen(QPen(QColor("#4ade80"), 2.4))
        p.drawLine(21, 14, 21, 22)
        p.drawLine(17, 18, 25, 18)
    elif kind == "new_folder":
        p.setPen(QPen(QColor("#fbbf24"), 2.0))
        p.drawRoundedRect(3, 7, 16, 14, 2, 2)
        p.drawLine(5, 5, 11, 5)
        p.setPen(QPen(QColor("#4ade80"), 2.4))
        p.drawLine(22, 14, 22, 22)
        p.drawLine(18, 18, 26, 18)
    elif kind == "open_folder":
        p.setPen(QPen(QColor("#60a5fa"), 2.2))
        p.drawRoundedRect(4, 7, 20, 15, 2.5, 2.5)
        p.drawLine(6, 5, 13, 5)
    elif kind == "refresh":
        p.setPen(QPen(QColor("#cbd5e1"), 2.2))
        p.drawArc(5, 5, 18, 18, 30 * 16, 290 * 16)
        p.drawLine(20, 4, 23, 9)
        p.drawLine(17, 9, 23, 9)
    elif kind == "send":
        # 現代白色上箭頭 / 紙飛機發送圖示
        pen = QPen(QColor("#ffffff"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(14, 21, 14, 7)
        p.drawLine(8, 13, 14, 7)
        p.drawLine(20, 13, 14, 7)
    elif kind == "plus":
        pen = QPen(QColor("#e2e8f0"), 2.4, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(14, 7, 14, 21)
        p.drawLine(7, 14, 21, 14)
    elif kind == "camera":
        pen = QPen(QColor("#cbd5e1"), 2.0)
        p.setPen(pen)
        p.drawRoundedRect(4, 8, 20, 14, 3, 3)
        p.drawLine(9, 6, 19, 6)
        p.drawEllipse(10, 11, 8, 8)

    p.end()
    return QIcon(pm)


# ==============================================================================
# 6. 完整分類說明指南對話框 (`SyntraUserGuideDialog`)
# ==============================================================================

USER_GUIDE_SECTIONS: List[Tuple[str, str, str]] = [
    (
        "quickstart",
        "📘 1. 快速入門與介面總覽",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>📘 1. 快速入門與介面總覽 (Quick Start)</h2>
        <p>歡迎使用 <b>Syntra 星樞 · 桌面全能 AI 代理系統</b>！主視窗分為四大核心區域：</p>
        <ul>
          <li><b>頂部選單列</b>：左側提供「檔案、設定、說明」，最右側提供「🔄 檢查更新」與「🌐 Google 登入 (Sign in)」快捷按鈕。</li>
          <li><b>左側邊欄</b>：可透過下拉選單切換「⚡ 快速執行」、「📁 檔案總管（預設顯示 Windows 常用目錄，並自動記住您上次開啟的資料夾）」、「📜 歷史紀錄（永久保存區＋2週暫存區）」與「⏰ 定時背景排程」。</li>
          <li><b>中央多代理工作區</b>：上方為多代理分頁列與檢視切換，中間為對話與終端機，下方為整合式卡片輸入框。</li>
          <li><b>右側多功能面板</b>：提供「🖥️ 即時畫面同步與自動閉環監督」、「🔌 Skills & MCP 管理」、「🌐 上網透明通報」與「🛡️ CDR 沙箱與防毒中心」。</li>
        </ul>
        <p><b>💡 對話氣泡按鈕說明</b>：將滑鼠停留在回覆或提問下方的圖示約 2 秒，會顯示英文功能提示：
        <code>Copy</code> (📋 複製)、<code>Edit</code> (✏️ 編輯重發)、<code>Like</code> (👍 好評)、<code>Dislike</code> (👎 待改進)、<code>Retry</code> (🔄 重新生成)、<code>More</code> (⋯ 分支對話/朗讀/匯出)。</p>
        """
    ),
    (
        "multi_agent",
        "🤖 2. 多代理並行、並排監控與畫布",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>🤖 2. 多代理並行、並排監控與代理畫布</h2>
        <ul>
          <li><b>新增與切換代理</b>：點擊代理分頁列的 <code>＋</code> 或右鍵可建立多個主代理或子代理（<code>↳</code>）。</li>
          <li><b>三種檢視模式</b>（點頂部「🤖 N 個代理在線 ▾」切換）：
            <ol>
              <li><b>🗖 分頁模式</b>：一次專注檢視單一代理與其專屬終端機。</li>
              <li><b>🗗 並排監控模式 (Split View)</b>：多個代理並排同時顯示！<b>直接用滑鼠點擊任一代理的對話框，該代理外框會立刻變成亮藍色框（<code>#38bdf8</code>）</b>，且下方輸入框頂部會同步顯示「🎯 正在輸入至：該代理名稱」，打字送出就會直接進入該代理！</li>
              <li><b>🕸 代理畫布模式 (Canvas View)</b>：以節點卡片呈現所有代理，可拖線串接兩個代理共用終端機或互傳結果。</li>
            </ol>
          </li>
          <li><b>⚡ 多代理同時實作</b>：點擊輸入框右上角的「⚡ 多代理同時實作」按鈕，每行輸入一項子任務，系統會自動開啟對應數量的代理並切換為並排模式同時執行！</li>
        </ul>
        """
    ),
    (
        "model_routing",
        "🧠 3. 模型選擇、自動路由與本機 Ollama",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>🧠 3. 模型選擇、智慧自動路由與本機 Ollama</h2>
        <ul>
          <li><b>🔒 嚴格鎖定指定模型</b>：當您在輸入框下方模型選單手動指定特定模型（例如某個 Gemini 模型或本機 Ollama 模型）時，系統會<b>嚴格鎖定只使用您指定的模型</b>，絕不偷偷切換至其他模型。</li>
          <li><b>🚀 本機 Ollama 自動喚醒</b>：當您選擇本機模型（如 <code>ollama_local:gpt-oss:20b</code> 或 <code>gemma3:12b</code>）而本機尚未開啟 Ollama 時，系統會自動在背景啟動 <code>ollama serve</code>。</li>
          <li><b>🤖 智慧自動路由 (Auto Router)</b>：若選擇「🤖 智慧自動路由」，系統會依任務複雜度（L1 輕量問答 ～ L4 深度架構研發、視覺圖片、桌控工具）自動匹配最佳模型，並在單一端點滿載時自動切換備援。</li>
          <li><b>💡 白話錯誤診斷</b>：若遇到 API 額度用盡 (HTTP 429)、舊模型停用 (HTTP 404)、金鑰錯誤 (HTTP 401/403) 或本機未安裝模型，系統會同時給出<b>白話原因說明、具體解決步驟</b>與原始錯誤訊息。</li>
        </ul>
        """
    ),
    (
        "desktop_control",
        "🖥️ 4. 桌面自動化、無障礙樹與軟體權限",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>🖥️ 4. 桌面自動化、無障礙語意樹與軟體權限控制</h2>
        <ul>
          <li><b>📱 AI 可使用的應用程式權限（預設僅開啟 Google）</b>：
            進入「⚙️ 設定 → 🔐 權限與功能」，系統會自動掃描電腦上所有已安裝軟體與桌面捷徑並以開關列出。<b>預設除 Google 相關軟體外全部為關閉</b>，您可隨時用開關授權特定軟體。</li>
          <li><b>🖥️ 本機軟體深度操作</b>：當您請 AI 操作本機軟體（例如「用桌面上的 Gemini 搜尋並建立筆記本」），AI 會直接啟動本機執行檔並透過 Windows UIA 無障礙語意樹（<code>inspect_accessibility_tree</code> / <code>ui_invoke</code> / <code>ui_type</code>）精準點擊按鈕與輸入文字。</li>
          <li><b>🛡️ 四級執行審批模式</b>（輸入框右下角 <code>🛡️ Mode ▾</code>）：
            支援 <code>Request Review</code>（每步審批）、<code>Default</code>（標準防護）、<code>Auto</code>（智慧判定）、<code>Turbo</code>（全速自動化）。</li>
        </ul>
        """
    ),
    (
        "security_center",
        "🛡️ 5. CDR 防毒、網路白名單、勒索與防篡改",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>🛡️ 5. CDR 防毒沙箱、網路白名單、勒索防護與機密文件防篡改</h2>
        <ul>
          <li><b>🧼 檔案清洗 (CDR) 與掃毒</b>：去除 PDF/Office/圖片中潛藏的巨集與腳本威脅，並結合本地啟發式與 Windows Defender 深度掃描。</li>
          <li><b>🌐 網路防護與動態白名單</b>：
            <ul>
              <li>自動識別並放行合法認證軟體（如 <b>Spotify、Claude、ChatGPT、Google、VS Code</b> 及您已開啟權限的軟體），避免正常連線被誤判為異常。</li>
              <li>點擊「🔍 檢查對外連線」後，任何未在白名單的連線右側皆有<b>「➕ 一鍵加入白名單」</b>按鈕，點一下即可將該軟體或 IP 納入信任白名單。</li>
            </ul>
          </li>
          <li><b>🪤 勒索病毒與可疑程序防護（兩階段分離）</b>：
            提供獨立的<b>「🔍 1. 掃描可疑程序」</b>（僅掃描列出，不自動誤殺）與<b>「🛑 2. 終止可疑程序」</b>按鈕，讓您先檢視清單再決定是否終止。</li>
          <li><b>🔒 檔案防篡改與機密文件快照（相容 Windows Update）</b>：
            <ul>
              <li><b>絕不阻擋 Windows 更新</b>：內建 Windows Update 與 <code>C:\\Windows</code> 核心白名單，系統更新完全順暢。</li>
              <li><b>📄 重要機密文件 (Word / Excel / PDF) 防篡改快照</b>：自動為您的 <code>.docx</code>、<code>.xlsx</code>、<code>.pptx</code>、<code>.pdf</code> 建立加密保險庫快照。平時可正常用 Word 編輯；萬一遭病毒竄改或加密，點擊<b>「💊 檢查並自動修復」</b>即可 0 秒原位還原！</li>
            </ul>
          </li>
        </ul>
        """
    ),
    (
        "google_and_daily",
        "🌐 6. Google 雲端漫遊、個資保護與日常管家",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>🌐 6. Google 帳號漫遊、個資保護保險庫與日常電腦管家</h2>
        <ul>
          <li><b>🌐 頂部右側 Google 登入</b>：點擊選單列最右邊的「🌐 Google 登入 (Sign in)」即可啟動瀏覽器 OAuth 授權。</li>
          <li><b>🔒 獨立個資保護資料夾 (<code>user_profile/</code>)</b>：所有個人化習慣、記憶與日常紀錄均集中存放於受保護的 <code>user_profile/</code>，嚴格禁止上傳至公開程式碼庫 (Git)，僅在您登入 Google 並同意後才可加密備份至個人 Google Drive 或從雲端連回。</li>
          <li><b>🧹 桌面/下載區自動整理與一鍵還原</b>：
            點擊「🧹 整理下載區」或「🖥️ 整理桌面」會先預覽分類結果；整理後若不滿意，隨時點擊旁邊的<b>「↩️ 還原整理」</b>即可 100% 恢復原本位置！</li>
          <li><b>📊 用機報告與情境切換</b>：即時統計開發、瀏覽、通訊、娛樂時長並給出護眼建議；支援一鍵切換「💻 工作 / 🎤 開會 / 🎮 娛樂 / 🌿 休息」模式。</li>
        </ul>
        """
    ),
    (
        "addons_and_update",
        "🧩 7. 選配擴充模組 (DLC)、字體大小與熱更新",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>🧩 7. 選配擴充模組 (DLC)、字體大小設定與數位簽章熱更新</h2>
        <ul>
          <li><b>🔤 字體大小設定</b>：已整合至「⚙️ 設定 → 一般設定 → 🔤 介面文字大小與縮放比例」，支援 Word 標準字級 (8~72pt) 與百分比滑桿 (50%~300%)，亦支援 <code>Ctrl + 滑鼠滾輪</code>。</li>
          <li><b>🧩 選配擴充模組 (DLC)</b>：如「💰 個人財務與帳單記帳管家」、「🎓 學術文獻與深度研究助手」、「🌿 個人健康與習慣教練」，預設關閉，可於「⚙️ 設定 → 權限與功能」自由勾選啟用。</li>
          <li><b>🔏 官方數位簽章與零停機熱更新</b>：所有主程式熱更新包與 DLC/DLL 模組均採用 <code>Ed25519 + HMAC-SHA256</code> 官方雙重簽章驗證，點擊頂部右側「🔄 檢查更新」即可檢查網頁更新並驗證模組簽章。</li>
        </ul>
        """
    ),
    (
        "shortcuts",
        "⌨️ 8. 快捷鍵與斜線指令 (/) 速查表",
        """
        <h2 style='color:#38bdf8; margin-top:0;'>⌨️ 8. 快捷鍵與斜線指令速查表</h2>
        <h4>⌨️ 全域與視窗快捷鍵</h4>
        <ul>
          <li><code>Ctrl + Alt + Q</code> 或 <code>Ctrl + Shift + F12</code>：🛑 緊急停止所有代理與桌面操作 (Kill Switch)</li>
          <li><code>Ctrl + Shift + Space</code>：召喚懸浮快速輸入列</li>
          <li><code>Ctrl + T</code>：開啟新對話　|　<code>Ctrl + N</code>：多開新視窗</li>
          <li><code>Ctrl + 滑鼠滾輪</code> 或 <code>Ctrl + +/-/0</code>：無段縮放介面字體大小</li>
          <li><code>Enter</code>：送出訊息　|　<code>Shift + Enter</code>：輸入框內換行</li>
        </ul>
        <h4>⚡ 常用斜線指令（可點輸入框左下角 <code>+</code> → <code>⚡ 快捷指令庫</code> 直接點選）</h4>
        <ul>
          <li><code>/audit</code>：全方位架構與資安漏洞審查　|　<code>/fix</code>：自動診斷報錯並修復程式碼</li>
          <li><code>/test</code>：自動撰寫並執行單元測試　|　<code>/git</code>：檢查 Git 狀態與產生變更摘要</li>
          <li><code>/browser</code>：深度瀏覽與擷取網頁重點　|　<code>/sec</code>：執行系統資安與防毒巡檢</li>
        </ul>
        """
    ),
]


class SyntraUserGuideDialog(QDialog):
    """完整分類使用說明書對話框（左欄分類導覽 + 右欄圖文詳解 + 關鍵字搜尋）"""

    def __init__(self, parent=None, initial_key: str = "quickstart"):
        super().__init__(parent)
        self.setWindowTitle("📖 Syntra 星樞 · 完整分類使用說明指南 (User Guide)")
        self.resize(880, 600)
        self.setStyleSheet("""
            QDialog { background-color: #0e1015; color: #f1f5f9; }
            QListWidget {
                background: #141824;
                border: 1px solid rgba(148, 163, 184, 0.18);
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QListWidget::item {
                padding: 9px 10px;
                border-radius: 6px;
                color: #cbd5e1;
                font-size: 12.5px;
                font-weight: 600;
            }
            QListWidget::item:hover { background: rgba(56, 189, 248, 0.12); }
            QListWidget::item:selected { background: #2563eb; color: #ffffff; }
            QTextBrowser {
                background: #141824;
                border: 1px solid rgba(148, 163, 184, 0.18);
                border-radius: 8px;
                padding: 14px;
                color: #e2e8f0;
                font-size: 13.5px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top_row = QHBoxLayout()
        lbl_h = QLabel("<b>📖 Syntra 星樞 · 官方分類操作說明書</b>")
        lbl_h.setStyleSheet("font-size: 15px; color: #60a5fa;")
        top_row.addWidget(lbl_h)
        top_row.addStretch()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜尋說明關鍵字（例如：並排、白名單、Ollama、還原、字體）...")
        self.search_edit.setFixedWidth(340)
        self.search_edit.textChanged.connect(self._on_search)
        top_row.addWidget(self.search_edit)
        root.addLayout(top_row)

        split = QSplitter(Qt.Horizontal)
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(255)
        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)

        for key, title, _html in USER_GUIDE_SECTIONS:
            it = QListWidgetItem(title)
            it.setData(Qt.UserRole, key)
            self.nav_list.addItem(it)

        self.nav_list.currentRowChanged.connect(self._on_row_changed)
        split.addWidget(self.nav_list)
        split.addWidget(self.viewer)
        split.setStretchFactor(0, 0)
        split.addWidget(self.viewer)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        bot_row = QHBoxLayout()
        lbl_tip = QLabel("💡 提示：任何功能也可直接在對話框詢問 AI，或按 Ctrl+Alt+Q 緊急停止所有操作。")
        lbl_tip.setStyleSheet("color: #94a3b8; font-size: 11.5px;")
        bot_row.addWidget(lbl_tip)
        bot_row.addStretch()
        btn_close = QPushButton("關閉說明")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        bot_row.addWidget(btn_close)
        root.addLayout(bot_row)

        self.select_section(initial_key)

    def select_section(self, key: str):
        for i in range(self.nav_list.count()):
            if self.nav_list.item(i).data(Qt.UserRole) == key:
                self.nav_list.setCurrentRow(i)
                return
        self.nav_list.setCurrentRow(0)

    def _on_row_changed(self, row: int):
        if 0 <= row < len(USER_GUIDE_SECTIONS):
            _, _, body_html = USER_GUIDE_SECTIONS[row]
            self.viewer.setHtml(
                "<div style='line-height:1.65; font-family:\"Segoe UI\",\"Microsoft JhengHei\",sans-serif;'>"
                + body_html
                + "</div>"
            )

    def _on_search(self, q: str):
        q_str = (q or "").strip().lower()
        if not q_str:
            self._on_row_changed(self.nav_list.currentRow())
            return
        matched_html = []
        for _k, title, body in USER_GUIDE_SECTIONS:
            if q_str in title.lower() or q_str in body.lower():
                matched_html.append(body)
        if matched_html:
            self.viewer.setHtml(
                "<div style='line-height:1.65; font-family:\"Segoe UI\",\"Microsoft JhengHei\",sans-serif;'>"
                + "<hr style='border:1px solid #1e293b; margin:14px 0;'>".join(matched_html)
                + "</div>"
            )
        else:
            self.viewer.setHtml(f"<p style='color:#94a3b8;'>找不到包含「{html.escape(q)}」的說明段落。</p>")


def open_user_guide_dialog(main_win: Any, section_key: str = "quickstart") -> None:
    dlg = SyntraUserGuideDialog(main_win, initial_key=section_key)
    dlg.exec_()


# ==============================================================================
# 7. 主視窗 (`MainWindow`) 全方位 UI 改造與掛載
# ==============================================================================

def install_main_window_evolution(main_win: Any) -> None:
    if getattr(main_win, "_main_evolution_installed", False):
        return
    main_win._main_evolution_installed = True

    def _hot_update_hooks():
        from core.hot_update_manager import install_hot_update_and_dlc_hooks
        install_hot_update_and_dlc_hooks()

    # 每一步各自隔離：某一步失敗只記錄下來，不會讓後面的升級全部跳過（以前一步出錯就整段中斷）
    steps = [
        install_strict_model_and_router_upgrades,
        install_parallel_agent_dispatch_tool,
        install_security_engine_upgrades,
        _hot_update_hooks,
        lambda: _setup_menubar_right_google_and_help_guide(main_win),
        lambda: _fix_explorer_icons_and_windows_common_folders(main_win),
        lambda: _fix_schedule_list_overlap(main_win),
        lambda: _setup_split_view_blue_border_and_input_indicator(main_win),
        lambda: _fix_chat_input_card_icons_and_slash_commands(main_win),
        lambda: _upgrade_security_center_ui(main_win),
        lambda: _install_local_guide_chat_qa_tool(main_win),
        lambda: _enhance_mcp_and_skills_tables(main_win),
        lambda: _install_modular_cdr_tab_switch(main_win),
    ]
    failures = []
    for step in steps:
        try:
            step()
        except Exception:
            import traceback
            failures.append(traceback.format_exc())
    main_win._main_evolution_failures = failures
    try:
        log_path = Path(__file__).resolve().parent.parent / "data" / "evolution_install_errors.log"
        if failures:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {datetime.datetime.now()} ---\n" + "\n".join(failures))
    except Exception:
        pass


def _setup_menubar_right_google_and_help_guide(main_win: Any) -> None:
    """
    1. 在最上方 `檔案 | 設定 | 說明` 選單列右側 (`Qt.TopRightCorner`) 放置「🌐 Google 登入 (Sign in)」按鈕與「🔄 檢查更新」。
    2. 擴充「說明 (Help)」選單：不再只有緊急終止，加入完整 8 大分類教學指南與總覽！
    """
    menubar = main_win.menuBar()
    if menubar is None:
        return

    # A. 擴充「說明 (menu_help)」選單
    menu_help = getattr(main_win, "menu_help", None)
    if menu_help is not None:
        menu_help.clear()
        act_guide_all = menu_help.addAction("📖 完整使用說明指南 (User Guide 總覽)")
        act_guide_all.setShortcut("F1")
        act_guide_all.triggered.connect(lambda: open_user_guide_dialog(main_win, "quickstart"))
        menu_help.addSeparator()

        for sec_key, sec_title, _ in USER_GUIDE_SECTIONS:
            act_sec = menu_help.addAction(sec_title)
            act_sec.triggered.connect(lambda _=False, k=sec_key: open_user_guide_dialog(main_win, k))

        menu_help.addSeparator()
        act_chk_upd = menu_help.addAction("🔄 檢查網頁更新與 DLC 數位簽章狀態")
        act_chk_upd.triggered.connect(lambda: _on_check_hot_update_clicked(main_win))
        menu_help.addSeparator()
        act_help_kill = menu_help.addAction("🛑 緊急停止所有代理與桌面操作 (Ctrl+Alt+Q)")
        act_help_kill.triggered.connect(main_win.trigger_kill_switch)

    # B. 右上角 Corner Widget：檢查更新 + Google 登入
    corner_box = QWidget(menubar)
    c_lay = QHBoxLayout(corner_box)
    c_lay.setContentsMargins(4, 1, 8, 1)
    c_lay.setSpacing(6)

    btn_update = QPushButton("🔄 檢查更新")
    btn_update.setCursor(Qt.PointingHandCursor)
    btn_update.setToolTip("Check for Updates (檢查網頁熱更新與 DLC 數位簽章狀態)")
    btn_update.setFixedHeight(24)
    btn_update.setStyleSheet("""
        QPushButton {
            background: rgba(56, 189, 248, 0.12);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.35);
            border-radius: 5px;
            padding: 2px 8px;
            font-size: 11.5px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: rgba(56, 189, 248, 0.25);
            color: #ffffff;
        }
    """)
    btn_update.clicked.connect(lambda: _on_check_hot_update_clicked(main_win))
    c_lay.addWidget(btn_update)

    btn_g = QToolButton(corner_box)
    btn_g.setPopupMode(QToolButton.InstantPopup)
    btn_g.setCursor(Qt.PointingHandCursor)
    btn_g.setFixedHeight(24)
    btn_g.setToolTip("Google Sign in / Account & Cloud Sync")
    main_win.btn_menubar_google = btn_g
    c_lay.addWidget(btn_g)

    menubar.setCornerWidget(corner_box, Qt.TopRightCorner)

    if not getattr(main_win, "_menubar_google_wrapped", False):
        main_win._menubar_google_wrapped = True
        _orig_update_g = main_win._update_google_login_button

        def _synced_update_google_login_button():
            _orig_update_g()
            b = getattr(main_win, "btn_menubar_google", None)
            src = getattr(main_win, "btn_google_login", None)
            if b is None or src is None:
                return
            from core.google_workspace_suite import google_suite
            is_auth = google_suite.is_authenticated()
            if is_auth:
                b.setText("🟢 Google 已登入 (Signed in) ▾")
                b.setStyleSheet("""
                    QToolButton {
                        background-color: #065f46;
                        color: #4ade80;
                        border: 1px solid rgba(74, 222, 128, 0.45);
                        border-radius: 5px;
                        padding: 2px 10px;
                        font-weight: 700;
                        font-size: 11.5px;
                    }
                    QToolButton:hover { background-color: #047857; color: #ffffff; }
                    QToolButton::menu-indicator { image: none; width: 0px; }
                """)
            else:
                b.setText("🌐 Google 登入 (Sign in) ▾")
                b.setStyleSheet("""
                    QToolButton {
                        background-color: #2563eb;
                        color: #ffffff;
                        border: 1px solid rgba(147, 197, 253, 0.4);
                        border-radius: 5px;
                        padding: 2px 10px;
                        font-weight: 700;
                        font-size: 11.5px;
                    }
                    QToolButton:hover { background-color: #1d4ed8; }
                    QToolButton::menu-indicator { image: none; width: 0px; }
                """)
            if src.menu() is not None:
                b.setMenu(src.menu())

        main_win._update_google_login_button = _synced_update_google_login_button

        _orig_create_mb = main_win._create_menu_bar

        def _patched_create_menu_bar():
            _orig_create_mb()
            QTimer.singleShot(0, lambda: _setup_menubar_right_google_and_help_guide(main_win))

        main_win._create_menu_bar = _patched_create_menu_bar

    main_win._update_google_login_button()


def _on_check_hot_update_clicked(main_win: Any) -> None:
    try:
        from core.hot_update_manager import hot_update_manager
        from core.addon_module_manager import addon_manager

        dlc_results = []
        for m in addon_manager.list_modules():
            mid = m["id"]
            v = hot_update_manager.verify_dlc_directory(Path(m["dir"]))
            status = "🔏 簽章有效" if v.get("ok") else f"⚠️ {v.get('error')}"
            dlc_results.append(f"• {m['name']} (`{mid}`)：{status}")

        remote_res = hot_update_manager.check_remote_update()
        if remote_res.get("has_update"):
            msg = (
                f"🎉 偵測到新版本：{remote_res.get('latest_version')}\n"
                f"目前版本：{remote_res.get('current_version')}\n"
                f"更新說明：{remote_res.get('release_notes', '無')}\n\n"
                f"【本機 DLC 擴充模組數位簽章校驗】：\n" + "\n".join(dlc_results)
            )
        else:
            msg = (
                f"✅ 目前已是最新版本（v{hot_update_manager.CURRENT_VERSION}）！\n"
                f"檢查狀態：{remote_res.get('message') or '所有核心模組與簽章皆為最新狀態'}\n\n"
                f"🔑 官方公鑰指紋：{hot_update_manager.authority.get_public_key_hex()[:24]}...\n\n"
                f"【本機 DLC 擴充模組數位簽章校驗】：\n" + "\n".join(dlc_results)
            )
        QMessageBox.information(main_win, "🔄 軟體更新與數位簽章檢查", msg)
    except Exception as e:
        QMessageBox.warning(main_win, "檢查更新", f"檢查更新時發生例外：{e}")


def _get_windows_common_folders() -> List[Tuple[str, Path]]:
    """取得如同 Windows 檔案總管的「常用資料夾 (Quick Access)」清單"""
    home = Path.home()
    candidates = [
        ("🖥️ 桌面 (Desktop)", home / "Desktop"),
        ("📥 下載 (Downloads)", home / "Downloads"),
        ("📄 文件 (Documents)", home / "Documents"),
        ("🖼️ 圖片 (Pictures)", home / "Pictures"),
        ("🎵 音樂 (Music)", home / "Music"),
        ("🎬 影片 (Videos)", home / "Videos"),
    ]
    return [(label, p) for label, p in candidates if p.exists()]


def _fix_explorer_icons_and_windows_common_folders(main_win: Any) -> None:
    """
    1. 修復檔案總管 (`tab_explorer`) 頂部 4 顆按鈕圖示消失的問題（加上清晰向量圖示與 0 padding）。
    2. 檔案總管預設跟 Windows 一樣指向「⭐ 常用資料夾（桌面、下載、文件、圖片...）」，
       不要直接指在 Syntra 的 `my_agent` 資料夾下！
    3. 若使用者之前有點擊或選擇過某個資料夾（`last_explorer_dir`），啟動時就自動停在該資料夾！
    """
    base_dir_norm = os.path.normcase(os.path.abspath(str(Path(__file__).resolve().parent.parent)))

    # 包裝 populate_file_tree：頂部永遠提供「⭐ Windows 常用資料夾」快速入口，下方展開當前選擇的資料夾
    _orig_populate = main_win.populate_file_tree

    def _enhanced_populate_file_tree(root_dir: Path):
        tree = getattr(main_win, "tree_workspace", None)
        if tree is None:
            return _orig_populate(root_dir)

        tree.clear()

        # 1. 頂部群組：⭐ Windows 常用資料夾 (Quick Access)
        qa_root = QTreeWidgetItem(tree)
        qa_root.setText(0, "⭐ 常用資料夾 (Windows Quick Access)")
        qa_root.setData(0, Qt.UserRole, "")
        qa_root.setExpanded(True)
        for label, fpath in _get_windows_common_folders():
            qa_item = QTreeWidgetItem(qa_root)
            qa_item.setText(0, label)
            qa_item.setData(0, Qt.UserRole, str(fpath))
            qa_item.setToolTip(0, f"雙擊或右鍵切換至：{fpath}")

        # 2. 當前停留的工作資料夾
        if not root_dir or not root_dir.exists():
            root_dir = Path.home() / "Desktop" if (Path.home() / "Desktop").exists() else Path.home()

        cur_root = QTreeWidgetItem(tree)
        cur_root.setText(0, f"📂 目前資料夾：{root_dir.name}")
        cur_root.setData(0, Qt.UserRole, str(root_dir))
        cur_root.setToolTip(0, str(root_dir))
        cur_root.setExpanded(True)

        ignored_names = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}

        def _add_children(parent_item: QTreeWidgetItem, cur_path: Path, depth: int = 0):
            if depth > 2:
                return
            try:
                entries = sorted(list(cur_path.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))[:150]
                for p in entries:
                    if p.name in ignored_names or p.name.startswith("."):
                        continue
                    item = QTreeWidgetItem(parent_item)
                    item.setData(0, Qt.UserRole, str(p))
                    if p.is_dir():
                        item.setText(0, f"📁 {p.name}")
                        if depth < 1:
                            _add_children(item, p, depth + 1)
                    else:
                        ext = p.suffix.lower()
                        icon = "📄"
                        if ext == ".py":
                            icon = "🐍"
                        elif ext in (".js", ".jsx", ".ts", ".tsx"):
                            icon = "📜"
                        elif ext in (".json", ".yaml", ".yml"):
                            icon = "⚙️"
                        elif ext in (".html", ".htm"):
                            icon = "🌐"
                        elif ext in (".md", ".txt", ".rst", ".docx", ".doc"):
                            icon = "📝"
                        elif ext in (".xlsx", ".xls", ".csv"):
                            icon = "📊"
                        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".ico"):
                            icon = "🖼️"
                        elif ext == ".pdf":
                            icon = "📕"
                        item.setText(0, f"{icon} {p.name}")
            except Exception:
                pass

        _add_children(cur_root, root_dir)

    main_win.populate_file_tree = _enhanced_populate_file_tree

    # 當使用者在樹狀總管點擊或雙擊資料夾時，記憶該資料夾並可切換停留於該資料夾
    def _remember_explorer_folder(folder_path: Path):
        try:
            f_str = str(folder_path.resolve())
            if os.path.normcase(f_str) != base_dir_norm:
                main_win.settings_manager.update_settings({"last_explorer_dir": f_str, "workspace_dir": f_str})
        except Exception:
            pass

    _orig_dbl = main_win._on_file_tree_double_clicked

    def _enhanced_on_tree_double_clicked(item: QTreeWidgetItem, column: int):
        path_str = item.data(0, Qt.UserRole)
        if not path_str:
            return
        target_path = Path(path_str)
        if target_path.is_dir():
            main_win.current_workspace_dir = target_path
            if hasattr(main_win, "lbl_workspace_name"):
                main_win.lbl_workspace_name.setText(f"📁 {target_path.name}")
                main_win.lbl_workspace_name.setToolTip(f"目前資料夾：{target_path}")
            _remember_explorer_folder(target_path)
            main_win.populate_file_tree(target_path)
            return
        _orig_dbl(item, column)

    main_win._on_file_tree_double_clicked = _enhanced_on_tree_double_clicked

    def _on_tree_single_clicked(item: QTreeWidgetItem, column: int):
        path_str = item.data(0, Qt.UserRole)
        if not path_str:
            return
        target_path = Path(path_str)
        # 若點選的是「⭐ 常用資料夾」下的項目，一鍵切換進入該常用資料夾並記憶！
        parent = item.parent()
        if target_path.is_dir() and parent is not None and "常用資料夾" in (parent.text(0) or ""):
            main_win.current_workspace_dir = target_path
            if hasattr(main_win, "lbl_workspace_name"):
                main_win.lbl_workspace_name.setText(f"📁 {target_path.name}")
                main_win.lbl_workspace_name.setToolTip(f"目前資料夾：{target_path}")
            _remember_explorer_folder(target_path)
            main_win.populate_file_tree(target_path)
        elif target_path.is_dir():
            _remember_explorer_folder(target_path)

    if hasattr(main_win, "tree_workspace"):
        try:
            main_win.tree_workspace.itemDoubleClicked.disconnect()
        except Exception:
            pass
        main_win.tree_workspace.itemDoubleClicked.connect(_enhanced_on_tree_double_clicked)
        main_win.tree_workspace.itemClicked.connect(_on_tree_single_clicked)

    _orig_select_ws = main_win.select_workspace_folder

    def _persisted_select_workspace_folder():
        _orig_select_ws()
        _remember_explorer_folder(main_win.current_workspace_dir)

    main_win.select_workspace_folder = _persisted_select_workspace_folder

    # 決定啟動時停留的資料夾：優先讀取使用者上次點擊的 `last_explorer_dir`，否則預設指向 Windows 桌面 (Desktop)
    saved_last = (
        main_win.settings_manager.get("last_explorer_dir", "")
        or main_win.settings_manager.get("workspace_dir", "")
        or ""
    ).strip()
    if saved_last and os.path.isdir(saved_last) and os.path.normcase(os.path.abspath(saved_last)) != base_dir_norm:
        initial_dir = Path(saved_last)
    else:
        desktop_dir = Path.home() / "Desktop"
        initial_dir = desktop_dir if desktop_dir.exists() else Path.home()

    main_win.current_workspace_dir = initial_dir
    if hasattr(main_win, "lbl_workspace_name"):
        main_win.lbl_workspace_name.setText(f"📁 {initial_dir.name}")
        main_win.lbl_workspace_name.setToolTip(f"目前資料夾：{initial_dir}")
    main_win.populate_file_tree(initial_dir)

    # 修復檔案總管頂部 4 顆按鈕圖示
    icon_btn_qss = """
        QPushButton {
            background-color: #1e2536;
            color: #e2e8f0;
            border: 1px solid rgba(148, 163, 184, 0.28);
            border-radius: 6px;
            padding: 0px;
            margin: 0px;
        }
        QPushButton:hover {
            background-color: #2563eb;
            color: #ffffff;
            border-color: #60a5fa;
        }
    """
    sidebar = getattr(main_win, "sidebar_widget", None)
    if sidebar is not None:
        for btn in sidebar.findChildren(QPushButton):
            tip = btn.toolTip() or ""
            txt = btn.text() or ""
            if "新增檔案" in tip or "📄" in txt:
                btn.setText("")
                btn.setIcon(make_ui_vector_icon("new_file"))
                btn.setIconSize(QSize(20, 20))
                btn.setFixedSize(30, 28)
                btn.setStyleSheet(icon_btn_qss)
                btn.setToolTip("New File (在目前目錄新增檔案)")
            elif "新增資料夾" in tip or "📁＋" in txt:
                btn.setText("")
                btn.setIcon(make_ui_vector_icon("new_folder"))
                btn.setIconSize(QSize(20, 20))
                btn.setFixedSize(30, 28)
                btn.setStyleSheet(icon_btn_qss)
                btn.setToolTip("New Folder (在目前目錄新增資料夾)")
            elif "切換工作資料夾" in tip or txt == "📂":
                btn.setText("")
                btn.setIcon(make_ui_vector_icon("open_folder"))
                btn.setIconSize(QSize(20, 20))
                btn.setFixedSize(30, 28)
                btn.setStyleSheet(icon_btn_qss)
                btn.setToolTip("Open Folder (選擇其他資料夾)")
            elif "重新整理檔案清單" in tip or txt == "🔄":
                btn.setText("")
                btn.setIcon(make_ui_vector_icon("refresh"))
                btn.setIconSize(QSize(20, 20))
                btn.setFixedSize(30, 28)
                btn.setStyleSheet(icon_btn_qss)
                btn.setToolTip("Refresh Explorer (重新整理檔案清單)")


def _fix_schedule_list_overlap(main_win: Any) -> None:
    """修復左側選單「⏰ 排程專區」卡片內容與按鈕重疊、文字被裁切的問題。"""
    def _clean_reload_schedules_list():
        if not hasattr(main_win, "list_schedules"):
            return
        schedules = main_win.schedule_manager.list_schedules()
        main_win.list_schedules.clear()
        main_win.list_schedules.setSpacing(4)

        for s in schedules:
            sched_id = s["id"]
            enabled = s.get("enabled", False)
            interval = s.get("interval_minutes", 30)
            next_t = time.strftime("%H:%M", time.localtime(s.get("next_run", 0)))
            name_str = str(s.get("name") or "未命名排程")
            prompt_str = str(s.get("prompt") or "")

            item = QListWidgetItem()
            item.setSizeHint(QSize(240, 68))
            item.setData(Qt.UserRole, sched_id)
            main_win.list_schedules.addItem(item)

            card = QFrame()
            card.setToolTip(f"排程名稱：{name_str}\n執行間隔：每 {interval} 分鐘\n下次執行：{next_t}\n任務內容：{prompt_str}")
            card.setStyleSheet("""
                QFrame {
                    background: #141824;
                    border: 1px solid rgba(148, 163, 184, 0.2);
                    border-radius: 8px;
                }
                QFrame:hover { border-color: #38bdf8; }
            """)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 6)
            card_layout.setSpacing(6)

            status_btn = QPushButton("🟢" if enabled else "⚪")
            status_btn.setFixedSize(26, 26)
            status_btn.setCursor(Qt.PointingHandCursor)
            status_btn.setToolTip("Toggle Enable/Disable (切換啟用 / 停用)")
            status_btn.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0px; font-size: 14px; }")
            status_btn.clicked.connect(lambda _, sid=sched_id, cur_en=enabled: main_win._toggle_schedule_enabled(sid, cur_en))
            card_layout.addWidget(status_btn)

            txt_box = QVBoxLayout()
            txt_box.setContentsMargins(0, 0, 0, 0)
            txt_box.setSpacing(2)

            short_title = name_str if len(name_str) <= 15 else name_str[:14] + "…"
            lbl_title = QLabel(html.escape(short_title))
            lbl_title.setStyleSheet("color: #f1f5f9; font-size: 12px; font-weight: 700; border: none; background: transparent;")
            lbl_title.setMinimumHeight(18)

            lbl_sub = QLabel(f"⏱️ 每 {interval} 分 · 下次 {next_t}")
            lbl_sub.setStyleSheet("color: #94a3b8; font-size: 10.5px; border: none; background: transparent;")
            lbl_sub.setMinimumHeight(16)

            txt_box.addWidget(lbl_title)
            txt_box.addWidget(lbl_sub)
            card_layout.addLayout(txt_box, stretch=1)

            btn_run = QPushButton("▶")
            btn_run.setToolTip("Run Now (立即手動執行此排程)")
            btn_run.setFixedSize(26, 26)
            btn_run.setCursor(Qt.PointingHandCursor)
            btn_run.setStyleSheet("""
                QPushButton {
                    background: rgba(56, 189, 248, 0.15);
                    color: #38bdf8;
                    border: 1px solid rgba(56, 189, 248, 0.35);
                    border-radius: 6px;
                    padding: 0px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background: #0284c7; color: #ffffff; }
            """)
            btn_run.clicked.connect(lambda _, sc=s: main_win._trigger_schedule_task(sc))
            card_layout.addWidget(btn_run)

            btn_del = QPushButton("✕")
            btn_del.setToolTip("Delete Schedule (直接刪除此排程)")
            btn_del.setFixedSize(26, 26)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.setStyleSheet("""
                QPushButton {
                    background: rgba(239, 68, 68, 0.15);
                    color: #f87171;
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    border-radius: 6px;
                    padding: 0px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover { background: #dc2626; color: #ffffff; }
            """)
            btn_del.clicked.connect(lambda _, sid=sched_id: main_win.delete_schedule_direct(sid))
            card_layout.addWidget(btn_del)

            main_win.list_schedules.setItemWidget(item, card)

    main_win.reload_schedules_list = _clean_reload_schedules_list
    _clean_reload_schedules_list()


def _setup_split_view_blue_border_and_input_indicator(main_win: Any) -> None:
    """
    實作並排監控 (`split`) 與多代理切換時的視覺連動：
    1. 點擊任一並排對話框即可直接選中該代理，並將該代理外框變為亮藍框 (`#38bdf8`)。
    2. 在下方輸入框 (`ChatInputCard`) 頂部顯示「🎯 正在輸入至：<代理名稱>」指示條，並同步更新 placeholder。
    3. 在輸入框右上角提供「⚡ 多代理同時實作」快捷按鈕。
    """
    card = getattr(main_win, "chat_input_card", None)
    if card is not None and not hasattr(card, "lbl_active_agent_target"):
        target_bar = QFrame(card)
        t_lay = QHBoxLayout(target_bar)
        t_lay.setContentsMargins(4, 0, 4, 2)
        t_lay.setSpacing(8)

        lbl_target = QLabel("🎯 正在輸入至：<b>🤖 代理 #1</b>")
        lbl_target.setStyleSheet("color: #38bdf8; font-size: 11.5px; font-weight: 600; background: transparent; border: none;")
        t_lay.addWidget(lbl_target)
        t_lay.addStretch()

        btn_parallel = QPushButton("⚡ 多代理同時實作 (Parallel Run)")
        btn_parallel.setCursor(Qt.PointingHandCursor)
        btn_parallel.setToolTip("Parallel Dispatch (開多個代理同時平行執行多項任務)")
        btn_parallel.setFixedHeight(22)
        btn_parallel.setStyleSheet("""
            QPushButton {
                background: rgba(56, 189, 248, 0.14);
                color: #38bdf8;
                border: 1px solid rgba(56, 189, 248, 0.35);
                border-radius: 5px;
                padding: 1px 8px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #0284c7;
                color: #ffffff;
            }
        """)
        btn_parallel.clicked.connect(lambda: _open_parallel_dispatch_dialog(main_win))
        t_lay.addWidget(btn_parallel)

        card.card_layout.insertWidget(0, target_bar)
        card.lbl_active_agent_target = lbl_target

    def _refresh_active_agent_visuals():
        active_id = getattr(main_win, "active_agent_id", "")
        slots = getattr(main_win, "agent_slots", {})
        active_slot = slots.get(active_id)
        active_name = main_win._agent_display_name(active_id) if active_slot else active_id

        for aid, s in slots.items():
            attach_chat_browser_enhancements(main_win, s)
            pw = getattr(s, "panel_widget", None)
            if pw is not None:
                pw.setObjectName(f"agentPanel_{aid}")
                if aid == active_id:
                    pw.setStyleSheet(
                        f"QFrame#agentPanel_{aid} {{"
                        " background: #141926;"
                        " border: 2px solid #38bdf8;"
                        " border-radius: 10px;"
                        "}"
                    )
                else:
                    pw.setStyleSheet(
                        f"QFrame#agentPanel_{aid} {{"
                        " background: #12151e;"
                        " border: 1px solid rgba(255, 255, 255, 0.08);"
                        " border-radius: 10px;"
                        "}"
                    )

        if card is not None and hasattr(card, "lbl_active_agent_target"):
            mode_hint = "（並排模式：點擊上方任一對話框即可切換輸入對象）" if getattr(main_win, "is_split_view", False) else ""
            card.lbl_active_agent_target.setText(
                f"🎯 正在輸入至：<b style='color:#60a5fa;'>{html.escape(active_name)}</b> "
                f"<span style='color:#64748b;font-weight:normal;'>{mode_hint}</span>"
            )
            if hasattr(card, "text_edit") and card.text_edit is not None:
                card.text_edit.setPlaceholderText(
                    f"正在輸入給【{active_name}】... (Ask anything, @ to mention, / for actions)"
                )

    _orig_switch = main_win.switch_to_agent

    def _patched_switch_to_agent(agent_id: str, force_tab: bool = False):
        _orig_switch(agent_id, force_tab=force_tab)
        _refresh_active_agent_visuals()

    main_win.switch_to_agent = _patched_switch_to_agent

    _orig_create_slot = main_win.create_agent_slot

    def _patched_create_agent_slot(*args, **kwargs):
        slot = _orig_create_slot(*args, **kwargs)
        attach_chat_browser_enhancements(main_win, slot)
        _refresh_active_agent_visuals()
        return slot

    main_win.create_agent_slot = _patched_create_agent_slot

    _orig_set_view = main_win.set_agent_view

    def _patched_set_agent_view(mode: str):
        _orig_set_view(mode)
        _refresh_active_agent_visuals()

    main_win.set_agent_view = _patched_set_agent_view

    for s in getattr(main_win, "agent_slots", {}).values():
        attach_chat_browser_enhancements(main_win, s)
    _refresh_active_agent_visuals()


def _open_parallel_dispatch_dialog(main_win: Any) -> None:
    text, ok = QInputDialog.getMultiLineText(
        main_win,
        "⚡ 多代理同時實作 (Parallel Multi-Agent Dispatch)",
        "請每行輸入一項要平行實作的子任務（系統將自動建立對應數量的代理並切換為『並排監控』同時執行）：",
        "任務 1：檢查專案架構並整理改進重點\n任務 2：撰寫核心模組單元測試與驗證腳本",
    )
    if not ok or not text.strip():
        return

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return

    slot_ids = list(main_win.agent_slots.keys())
    while len(slot_ids) < len(lines) and len(slot_ids) < 6:
        new_slot = main_win.create_agent_slot(f"🤖 代理 #{len(slot_ids) + 1}", focus=False)
        slot_ids.append(new_slot.agent_id)

    main_win.set_agent_view("split")

    for idx, prompt_line in enumerate(lines[:6]):
        target_aid = slot_ids[idx]
        QTimer.singleShot(idx * 120, lambda aid=target_aid, p=prompt_line: main_win._team_send_now(aid, p))


def _fix_chat_input_card_icons_and_slash_commands(main_win: Any) -> None:
    """
    1. 修復輸入對話框 (`ChatInputCard`) 中：
       - 送出按鈕 (`btn_send`) 圖示因全域 padding 擠壓變形的問題（改用清晰向量上箭頭圖示 + 0 padding）。
       - `+` 按鈕 (`btn_context`) 與截圖按鈕 (`btn_snap_quick`) 圖示清晰化。
    2. 將獨立的「⚡ 指令 (`btn_slash_quick`)」按鈕從底部列移除，整合進 `+ (Add Context)` 選單中（如同檔案、資料夾一樣以選單方式點開即選）。
    3. 修復輸入 `/` 彈出的快速指令庫 (`slash_list`) 文字重疊看不清楚與無法點擊的問題。
    """
    card = getattr(main_win, "chat_input_card", None)
    if card is None:
        return

    # 1. 隱藏底部獨立的 `⚡ 指令` 按鈕，將其整合進 `+` 選單
    if hasattr(card, "btn_slash_quick") and card.btn_slash_quick is not None:
        card.btn_slash_quick.hide()

    # 2. 修復 `+` 按鈕、截圖按鈕與送出按鈕 (`btn_send`) 的圖示與 padding: 0px
    if hasattr(card, "btn_context") and card.btn_context is not None:
        card.btn_context.setText("")
        card.btn_context.setIcon(make_ui_vector_icon("plus"))
        card.btn_context.setIconSize(QSize(18, 18))
        card.btn_context.setFixedSize(28, 28)
        card.btn_context.setToolTip("Add Context & Commands (附加檔案、資料夾、視窗提及或開啟快捷指令庫)")
        card.btn_context.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 7px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.22);
                border-color: #38bdf8;
            }
        """)

    if hasattr(card, "btn_snap_quick") and card.btn_snap_quick is not None:
        card.btn_snap_quick.setText("")
        card.btn_snap_quick.setIcon(make_ui_vector_icon("camera"))
        card.btn_snap_quick.setIconSize(QSize(18, 18))
        card.btn_snap_quick.setFixedSize(28, 28)
        card.btn_snap_quick.setToolTip("Screenshot (即時擷取視窗畫面附加到此對話)")
        card.btn_snap_quick.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 7px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background: rgba(56, 189, 248, 0.18);
                border-color: #38bdf8;
            }
        """)

    if hasattr(card, "btn_send") and card.btn_send is not None:
        card.btn_send.setText("")
        card.btn_send.setIcon(make_ui_vector_icon("send"))
        card.btn_send.setIconSize(QSize(18, 18))
        card.btn_send.setFixedSize(32, 32)
        card.btn_send.setToolTip("Send (送出指令 Enter)")
        card.btn_send.setStyleSheet("""
            QPushButton {
                background: #0284c7;
                color: #ffffff;
                border: 1px solid rgba(125, 211, 252, 0.35);
                border-radius: 16px;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                background: #0369a1;
                border-color: #38bdf8;
            }
            QPushButton:pressed {
                background: #075985;
            }
        """)

    # 3. 升級 `+ (Add Context)` 選單：把「⚡ 快捷指令庫 (Slash Commands)」整合進選單裡，跟檔案、資料夾一樣點擊即用！
    def _enhanced_show_add_context_menu():
        menu = QMenu(card)
        menu.setStyleSheet("""
            QMenu {
                background: #161b26;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
                color: #e2e8f0;
            }
            QMenu::item {
                padding: 7px 18px;
                border-radius: 5px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background: #0284c7;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #334155;
                margin: 4px 8px;
            }
        """)

        act_files = QAction("📎 Files (附加多個檔案)", menu)
        act_files.triggered.connect(card.sig_request_files.emit)
        menu.addAction(act_files)

        act_folder = QAction("📁 Folder (指定工作資料夾)", menu)
        act_folder.triggered.connect(card.sig_request_folder.emit)
        menu.addAction(act_folder)

        act_mentions = QAction("@ Mentions (提及監控視窗)", menu)
        act_mentions.triggered.connect(card.sig_request_mentions.emit)
        menu.addAction(act_mentions)

        act_snap = QAction("📸 Screenshot (即時螢幕截圖)", menu)
        act_snap.triggered.connect(card.sig_request_snap.emit)
        menu.addAction(act_snap)

        act_browser = QAction("🌐 Browser (深度網頁瀏覽與分析)", menu)
        act_browser.triggered.connect(card.sig_request_browser.emit)
        menu.addAction(act_browser)

        menu.addSeparator()

        # ⚡ 快捷指令庫子選單（跟檔案選單一樣直覺好點、字體清晰）
        cmd_menu = menu.addMenu("⚡ Commands (快捷指令庫 / Slash Actions)")
        cmd_menu.setStyleSheet(menu.styleSheet())
        for item in getattr(card, "_all_commands", []):
            cmd_str = item.get("cmd", "")
            title_str = item.get("title", "")
            desc_str = item.get("desc", "")
            act_cmd = QAction(f"{cmd_str}  —  {title_str} ({desc_str})", cmd_menu)
            act_cmd.triggered.connect(lambda _=False, c=cmd_str: card.text_edit.replace_slash_command(c))
            cmd_menu.addAction(act_cmd)

        pos = card.btn_context.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        menu.exec_(pos)

    card._show_add_context_menu = _enhanced_show_add_context_menu
    try:
        card.btn_context.clicked.disconnect()
    except Exception:
        pass
    card.btn_context.clicked.connect(_enhanced_show_add_context_menu)

    # 4. 修復輸入 `/` 時內嵌快速指令面板 (`slash_list`) 看不清楚與無法點擊的問題
    card.slash_container.setMinimumHeight(210)
    card.slash_container.setMaximumHeight(240)
    card.slash_list.setStyleSheet("""
        QListWidget {
            border: none;
            background: #0f172a;
            outline: none;
            font-size: 13px;
        }
        QListWidget::item {
            background: rgba(30, 41, 59, 0.45);
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 6px;
            padding: 8px 10px;
            margin-bottom: 3px;
            color: #f1f5f9;
        }
        QListWidget::item:hover {
            background: rgba(56, 189, 248, 0.22);
            border-color: #38bdf8;
        }
        QListWidget::item:selected {
            background: #0284c7;
            color: #ffffff;
        }
    """)

    def _clear_and_clickable_filter_slash(query: str):
        q = (query or "").lower().strip()
        matched = []
        for item in getattr(card, "_all_commands", []):
            cmd = item.get("cmd", "")
            title = item.get("title", "")
            desc = item.get("desc", "")
            badge = item.get("badge", "")
            if not q or cmd.lower().startswith("/" + q) or cmd.lower().startswith(q):
                matched.append((0, item))
            elif q in title.lower() or q in desc.lower() or q in badge.lower():
                matched.append((1, item))

        matched.sort(key=lambda x: x[0])
        card.slash_list.clear()
        if not matched:
            card.hide_slash_panel()
            return

        for _, item in matched:
            cmd_str = item.get("cmd", "")
            title_str = item.get("title", "")
            desc_str = item.get("desc", "")
            # 直接使用原生 QListWidgetItem 文字呈現（杜絕雙層 QLabel 重疊與滑鼠點擊事件被吞掉的問題！）
            list_item = QListWidgetItem(f"{cmd_str}   【{title_str}】 — {desc_str}")
            list_item.setSizeHint(QSize(420, 38))
            list_item.setData(Qt.UserRole, cmd_str)
            list_item.setToolTip(f"點擊或按 Enter 帶入指令：{cmd_str}\n功能：{title_str}\n說明：{desc_str}")
            card.slash_list.addItem(list_item)

        card.slash_list.setCurrentRow(0)
        card.slash_container.show()
        card.text_edit.set_popup_active(True)

    card._filter_and_show_slash = _clear_and_clickable_filter_slash
    try:
        card.text_edit.sig_slash_query.disconnect()
    except Exception:
        pass
    card.text_edit.sig_slash_query.connect(_clear_and_clickable_filter_slash)


def _upgrade_security_center_ui(main_win: Any) -> None:
    """
    全面升級防毒與資安中心三大區塊：
    1. 🌐 網路防護與白名單：互動式連線清單 + 「➕ 一鍵加入白名單」。
    2. 🪤 勒索病毒防護：拆分為「🔍 1. 掃描可疑程序」與「🛑 2. 終止可疑程序」。
    3. 🔒 檔案防竄改：精簡主畫面按鈕 + 「📄 重要文件防篡改快照 (Word/Excel/PDF)」+ 收納「⚙️ 進階防篡改設定 ▾」。
    """
    if hasattr(main_win, "txt_net_output"):
        net_parent = main_win.txt_net_output.parentWidget()
        net_lay = net_parent.layout() if net_parent else None
        if net_lay is not None and not hasattr(main_win, "list_scanned_conns"):
            lbl_scan_title = QLabel("<b>🔎 掃描到的對外連線（點擊右側按鈕可一鍵將該軟體或 IP 加入白名單）：</b>")
            lbl_scan_title.setStyleSheet("color: #cbd5e1; font-size: 11.5px;")
            net_lay.addWidget(lbl_scan_title)

            list_conns = QListWidget()
            list_conns.setMinimumHeight(110)
            list_conns.setStyleSheet("""
                QListWidget {
                    background: #0f131d;
                    border: 1px solid rgba(148, 163, 184, 0.2);
                    border-radius: 6px;
                }
            """)
            main_win.list_scanned_conns = list_conns
            net_lay.addWidget(list_conns)

            quick_wl_row = QHBoxLayout()
            btn_wl_selected = QPushButton("➕ 一鍵將選取連線加入白名單")
            btn_wl_selected.setStyleSheet("background-color: #059669; color: white; font-weight: bold; padding: 5px 10px;")
            btn_wl_all = QPushButton("➕ 全部加入白名單")
            btn_wl_all.setStyleSheet("padding: 5px 10px;")
            quick_wl_row.addWidget(btn_wl_selected)
            quick_wl_row.addWidget(btn_wl_all)
            net_lay.addLayout(quick_wl_row)

            def _whitelist_conn_entry(conn_dict: Dict[str, Any]):
                proc = (conn_dict.get("process") or "").strip().lower()
                ip = (conn_dict.get("remote_ip") or "").strip()
                added_items = []
                if proc and proc != "unknown" and proc not in main_win.security_guard.network_guard.SUSPICIOUS_OUTBOUND_PROCESSES:
                    main_win.security_guard.network_guard.add_process_to_whitelist(proc)
                    added_items.append(f"認證軟體 `{proc}`")
                if ip:
                    main_win.security_guard.add_whitelist_domain(ip)
                    added_items.append(f"IP `{ip}`")
                main_win._refresh_whitelist_ui()
                main_win._scan_active_connections_ui()
                if added_items:
                    main_win.statusBar().showMessage(f"✅ 已一鍵加入白名單：{', '.join(added_items)}", 4000)

            def _on_wl_selected():
                it = list_conns.currentItem()
                if not it:
                    QMessageBox.information(main_win, "提示", "請先在清單中點選一筆連線，或直接點擊該列右側的「➕ 加入白名單」按鈕。")
                    return
                data = it.data(Qt.UserRole) or {}
                _whitelist_conn_entry(data)

            def _on_wl_all():
                count = list_conns.count()
                if count == 0:
                    return
                for i in range(count):
                    it = list_conns.item(i)
                    data = (it.data(Qt.UserRole) if it else None) or {}
                    if not data.get("is_lolbin"):
                        proc = (data.get("process") or "").strip().lower()
                        ip = (data.get("remote_ip") or "").strip()
                        if proc and proc != "unknown":
                            main_win.security_guard.network_guard.add_process_to_whitelist(proc)
                        if ip:
                            main_win.security_guard.add_whitelist_domain(ip)
                main_win._refresh_whitelist_ui()
                main_win._scan_active_connections_ui()
                QMessageBox.information(main_win, "白名單已更新", "✅ 已將所有一般外連軟體與 IP 一鍵加入白名單！")

            btn_wl_selected.clicked.connect(_on_wl_selected)
            btn_wl_all.clicked.connect(_on_wl_all)

            def _enhanced_scan_active_connections_ui():
                list_conns.clear()
                conns = main_win.security_guard.network_guard.inspect_active_system_connections()
                if not conns:
                    main_win.txt_net_output.setPlainText(
                        "✅ 目前所有本機活躍連線皆符合白名單或已通過合法軟體認證（Spotify、Claude、ChatGPT、Google 等已自動認證放行），未發現可疑外連。"
                    )
                    return

                lines = [f"⚠️ 發現 {len(conns)} 筆未在白名單的外連（可直接點擊下方按鈕一鍵加入白名單）："]
                for c in conns:
                    tag = "[🚨 高危 LOLBin]" if c.get("is_lolbin") else "[未認證外連]"
                    desc = f"{tag} {c.get('process')} (PID:{c.get('pid')}) → {c.get('remote_ip')}:{c.get('remote_port')}"
                    lines.append("• " + desc)

                    item = QListWidgetItem()
                    item.setSizeHint(QSize(260, 34))
                    item.setData(Qt.UserRole, c)
                    list_conns.addItem(item)

                    row_w = QWidget()
                    r_lay = QHBoxLayout(row_w)
                    r_lay.setContentsMargins(6, 2, 6, 2)
                    r_lay.setSpacing(6)
                    lbl = QLabel(desc)
                    lbl.setStyleSheet("color: #f87171;" if c.get("is_lolbin") else "color: #e2e8f0; font-size: 11.5px;")
                    r_lay.addWidget(lbl, stretch=1)

                    btn_one = QPushButton("➕ 一鍵加入白名單")
                    btn_one.setCursor(Qt.PointingHandCursor)
                    btn_one.setFixedHeight(24)
                    btn_one.setStyleSheet("""
                        QPushButton {
                            background: #059669; color: white; border: none; border-radius: 4px;
                            padding: 2px 8px; font-size: 11px; font-weight: 600;
                        }
                        QPushButton:hover { background: #10b981; }
                    """)
                    btn_one.clicked.connect(lambda _, cd=c: _whitelist_conn_entry(cd))
                    r_lay.addWidget(btn_one)
                    list_conns.setItemWidget(item, row_w)

                main_win.txt_net_output.setPlainText("\n".join(lines))

            main_win._scan_active_connections_ui = _enhanced_scan_active_connections_ui
            for b in net_parent.findChildren(QPushButton):
                if "檢查對外連線" in b.text() or "排查本機外連" in b.text():
                    try:
                        b.clicked.disconnect()
                    except Exception:
                        pass
                    b.clicked.connect(_enhanced_scan_active_connections_ui)

    if hasattr(main_win, "txt_hyper_output"):
        hyp_parent = main_win.txt_hyper_output.parentWidget()
        if hyp_parent is not None and not getattr(main_win, "_hyper_split_buttons_done", False):
            main_win._hyper_split_buttons_done = True
            main_win._pending_suspicious_procs = []

            for btn in hyp_parent.findChildren(QPushButton):
                t_str = btn.text()
                if "終止可疑" in t_str or "LOLBins" in t_str:
                    btn.setText("🔍 1. 掃描可疑程序")
                    btn.setToolTip("Scan Suspicious Processes (僅執行記憶體與命令列掃描並列出清單，不會立即終止程序)")
                    btn.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 12px;")
                    try:
                        btn.clicked.disconnect()
                    except Exception:
                        pass

                    btn_terminate = QPushButton("🛑 2. 終止可疑程序 (0)")
                    btn_terminate.setToolTip("Terminate Scanned Suspicious Processes (檢視掃描結果後，點擊此鈕終止可疑程序)")
                    btn_terminate.setStyleSheet("background-color: #dc2626; color: white; font-weight: bold; padding: 6px 12px;")
                    btn_terminate.setEnabled(False)
                    main_win.btn_terminate_suspicious = btn_terminate

                    parent_holder = btn.parentWidget()
                    if parent_holder and parent_holder.layout():
                        parent_holder.layout().addWidget(btn_terminate)

                    def _do_scan_only():
                        detected = main_win.security_guard.hyper_sentinel.scan_only_processes_for_lolbins()
                        main_win._pending_suspicious_procs = detected
                        if not detected:
                            btn_terminate.setText("🛑 2. 終止可疑程序 (0)")
                            btn_terminate.setEnabled(False)
                            main_win.txt_hyper_output.setPlainText(
                                "✅ 【第 1 步：記憶體與命令列掃描完成】\n"
                                "目前未發現帶有惡意無檔案攻擊特徵 (-enc / IEX / bypass / shadowcopy delete) 的可疑程序。"
                            )
                        else:
                            btn_terminate.setText(f"🛑 2. 終止可疑程序 ({len(detected)})")
                            btn_terminate.setEnabled(True)
                            lines = [
                                f"⚠️ 【第 1 步：掃描發現 {len(detected)} 個可疑程序】（尚未終止，請確認後點擊『🛑 2. 終止可疑程序』）："
                            ]
                            for d in detected:
                                lines.append(
                                    f"• PID {d.get('pid')} ({d.get('process_name')}) | 特徵: {d.get('matched_pattern')}\n"
                                    f"  指令: {d.get('command_line')}"
                                )
                            main_win.txt_hyper_output.setPlainText("\n".join(lines))

                    def _do_terminate_scanned():
                        pending = getattr(main_win, "_pending_suspicious_procs", [])
                        if not pending:
                            QMessageBox.information(main_win, "提示", "目前沒有待終止的可疑程序，請先點擊「🔍 1. 掃描可疑程序」。")
                            return
                        killed = main_win.security_guard.hyper_sentinel.terminate_scanned_lolbins(pending)
                        main_win._pending_suspicious_procs = []
                        btn_terminate.setText("🛑 2. 終止可疑程序 (0)")
                        btn_terminate.setEnabled(False)
                        lines = [f"🛑 【第 2 步：已成功終止 {len(killed)} 個可疑程序】："]
                        for k in killed:
                            lines.append(f"• 已處決 PID {k.get('pid')} ({k.get('process_name')}): {k.get('matched_pattern')}")
                        main_win.txt_hyper_output.setPlainText("\n".join(lines))

                    btn.clicked.connect(_do_scan_only)
                    btn_terminate.clicked.connect(_do_terminate_scanned)
                    break

    if hasattr(main_win, "txt_tamper_output"):
        tamp_parent = main_win.txt_tamper_output.parentWidget()
        tamp_lay = tamp_parent.layout() if tamp_parent else None
        if tamp_parent is not None and tamp_lay is not None and not getattr(main_win, "_tamper_ui_simplified", False):
            main_win._tamper_ui_simplified = True

            if hasattr(main_win, "txt_tamper_path"):
                main_win.txt_tamper_path.setText(str(main_win.current_workspace_dir))

            advanced_btns: List[QPushButton] = []
            for b in tamp_parent.findChildren(QPushButton):
                txt = b.text()
                if any(k in txt for k in ("禁止刪改", "NTFS", "資料夾保護", "CFA")):
                    advanced_btns.append(b)
                    b.hide()

            doc_shield_row = QHBoxLayout()
            btn_doc_vault = QPushButton("📄 重要文件防篡改快照 (保護 Word / Excel / PDF)")
            btn_doc_vault.setCursor(Qt.PointingHandCursor)
            btn_doc_vault.setToolTip(
                "自動為桌面、文件夾與工作區的 Word (.docx)、Excel (.xlsx)、PDF 等機密文件建立加密快照；\n"
                "平時可正常編輯且絕不影響 Windows 更新，一旦遭病毒篡改可點『💊 檢查並自動修復』秒級還原！"
            )
            btn_doc_vault.setStyleSheet("background-color: #0284c7; color: white; font-weight: bold; padding: 6px 12px;")

            btn_toggle_adv = QPushButton("⚙️ 進階防篡改設定 (NTFS / Windows CFA) ▸")
            btn_toggle_adv.setCheckable(True)
            btn_toggle_adv.setCursor(Qt.PointingHandCursor)
            btn_toggle_adv.setStyleSheet("padding: 6px 10px; color: #94a3b8;")

            doc_shield_row.addWidget(btn_doc_vault)
            doc_shield_row.addWidget(btn_toggle_adv)

            adv_box = QGroupBox("⚙️ 進階核心權限與 Windows 原生受控資料夾設定")
            adv_box.setStyleSheet("QGroupBox { border: 1px solid rgba(148,163,184,0.2); border-radius: 6px; margin-top: 6px; padding-top: 8px; }")
            adv_lay = QHBoxLayout(adv_box)
            adv_lay.setContentsMargins(8, 6, 8, 6)
            adv_lay.setSpacing(6)
            for ab in advanced_btns:
                ab.setParent(adv_box)
                ab.show()
                adv_lay.addWidget(ab)
            adv_box.hide()

            idx_out = tamp_lay.indexOf(main_win.txt_tamper_output)
            insert_pos = max(0, idx_out)
            tamp_lay.insertLayout(insert_pos, doc_shield_row)
            tamp_lay.insertWidget(insert_pos + 1, adv_box)

            def _on_toggle_adv(checked: bool):
                adv_box.setVisible(checked)
                btn_toggle_adv.setText(
                    "⚙️ 進階防篡改設定 (NTFS / Windows CFA) ▾" if checked else "⚙️ 進階防篡改設定 (NTFS / Windows CFA) ▸"
                )

            # 快照要掃檔案、複製備份，一律在背景執行緒跑，完成後經 signal 回 UI 執行緒更新畫面
            # （原本直接在 UI 執行緒執行，桌面檔案一多整個視窗就「沒有回應」）
            doc_bridge = _DocSnapshotBridge(main_win)

            def _run_doc_snapshot_bg(dirs=None, report: bool = False):
                def _work():
                    try:
                        res = main_win.security_guard.integrity_guard.protect_important_documents_snapshot(dirs)
                    except Exception as e:  # noqa: BLE001
                        res = {"ok": False, "error": str(e)}
                    if report:
                        doc_bridge.done.emit(res)
                threading.Thread(target=_work, name="DocSnapshot", daemon=True).start()

            def _on_protect_docs():
                target = main_win.txt_tamper_path.text().strip()
                dirs = [target] if target and os.path.exists(target) else None
                btn_doc_vault.setEnabled(False)
                main_win.txt_tamper_output.setPlainText("⏳ 正在背景建立重要文件防篡改快照，完成後會顯示結果…")
                _run_doc_snapshot_bg(dirs, report=True)

            def _on_doc_snapshot_done(res: Dict[str, Any]):
                btn_doc_vault.setEnabled(True)
                if not res.get("ok", True):
                    main_win.txt_tamper_output.setPlainText(f"❌ 文件快照失敗：{res.get('error')}")
                    return
                samples = "、".join(res.get("sample_files", [])[:8]) or "（無新增檔案）"
                msg = (
                    f"✅ 重要機密文件防篡改快照已完成！\n"
                    f"• 本次納入保護文件數：{res.get('protected_count')} 份（累計保險庫守護：{res.get('total_vault_files')} 份）\n"
                    f"• 涵蓋格式：Word (.docx/.doc)、Excel (.xlsx)、PPT (.pptx)、PDF、Markdown、JSON 等\n"
                    f"• 保護範例：{samples}\n"
                    f"• 系統相容性：已開啟 Windows Update 智慧白名單，絕不影響系統更新或正常編輯存檔；若遭病毒竄改，點選「💊 檢查並自動修復」即可 0 秒原位還原！"
                )
                main_win.txt_tamper_output.setPlainText(msg)

            btn_toggle_adv.toggled.connect(_on_toggle_adv)
            btn_doc_vault.clicked.connect(_on_protect_docs)
            doc_bridge.done.connect(_on_doc_snapshot_done)

            QTimer.singleShot(2500, lambda: _run_doc_snapshot_bg())


# ==============================================================================
# 8. 對話框直接詢問本地功能教學 (`query_syntra_user_guide`) + 技能/MCP 表格窄視窗優化 + 模組化 CDR 分頁
# ==============================================================================

def _install_local_guide_chat_qa_tool(main_win: Any) -> None:
    """
    讓使用者直接在對話框詢問「這個功能怎麼用 / 如何調整畫布大小 / 怎麼整理桌面並還原 / CDR 防毒在哪裡」時，
    代理能精準查詢內建教學資料庫並直接回答本地功能的操作步驟！
    """
    try:
        from core.agent_brain import AgentBrain
        from core.tools import registry, ToolParameter

        def query_syntra_user_guide(query: str = "") -> str:
            q = (query or "").strip().lower()
            tokens = [t for t in re.split(r"[\s,，、/]+", q) if t]
            matched_blocks: List[str] = []
            for sec_key, sec_title, sec_html in USER_GUIDE_SECTIONS:
                plain = re.sub(r"<[^>]+>", " ", sec_html)
                plain = re.sub(r"\s+", " ", plain).strip()
                if not tokens or any(tok in sec_title.lower() or tok in plain.lower() for tok in tokens):
                    matched_blocks.append(f"【{sec_title}】\n{plain}")
            if not matched_blocks:
                for _, sec_title, sec_html in USER_GUIDE_SECTIONS:
                    plain = re.sub(r"<[^>]+>", " ", sec_html)
                    plain = re.sub(r"\s+", " ", plain).strip()
                    matched_blocks.append(f"【{sec_title}】\n{plain}")
            return "\n\n".join(matched_blocks)

        registry.register(
            name="query_syntra_user_guide",
            description=(
                "查詢 Syntra (星樞) 軟體本身的本地功能使用指南與操作說明。"
                "當使用者在對話中詢問本軟體任何功能（例如：如何調整代理畫布卡片大小、如何多代理並排、如何整理桌面與一鍵還原、"
                "用機報告、快速指令庫、字體大小設定、防毒與 CDR 模組、MCP 與技能表格、跨專案修改等）該怎麼操作時，請優先呼叫此工具取得精確步驟。"
            ),
            parameters=[
                ToolParameter(
                    "query",
                    "string",
                    "想查詢的功能關鍵字（例如：畫布大小、桌面整理還原、字體大小、快速指令、CDR 防毒、並排監控），留空則回傳完整指南",
                    required=False,
                ),
            ],
            func=query_syntra_user_guide,
            category="system",
        )

        guide_summary = (
            "\n\n【Syntra 星樞本地軟體操作內建知識庫（當使用者詢問本軟體怎麼用時，請直接精確回答或呼叫 `query_syntra_user_guide`）】：\n"
            "1. 代理畫布與個別大小調整：點選上方『🕸 代理畫布』，每張代理卡片或工具卡片右下角皆有『◢』縮放控制角，滑鼠按住右下角即可自由拉寬、拉高單一代理對話框（範圍 240×175 ~ 780×640），卡片高度拉大時會自動顯示更多對話與終端機輸出；右鍵點擊卡片可選『📐 重設卡片預設大小』。\n"
            "2. 多代理並排與同時實作：點擊輸入框右上角『⚡ 多代理同時實作』或呼叫 `parallel_dispatch_tasks`，可同時分派任務給多個代理；並排模式下點擊任一對話框會呈現亮藍框 (`#38bdf8`) 代表目前輸入焦點。\n"
            "3. 快速指令庫 (`/` 與 `+` 選單)：點擊輸入框左下角『+』按鈕 →『⚡ Commands (快捷指令庫)』，或在輸入框打 `/` 即可點選執行快捷指令。\n"
            "4. 桌面/下載自動整理與一鍵還原：在右側『🌐 Google & 習慣』分頁點擊『🧹 整理桌面』或『📥 整理下載』；若不喜歡整理結果，點擊旁邊的『↩️ 還原整理』即可根據 `organize_manifest.json` 100% 原位復原所有檔案。\n"
            "5. 用機報告：在右側『🌐 Google & 習慣』點擊『📊 用機報告』，系統會即時掃描本機開發工具（VS Code / PyCharm / Cursor / Python / Node）、瀏覽器與資料庫紀錄，真實呈現開發與各分類分鐘數。\n"
            "6. 字體大小設定：位於上方選單『⚙️ 設定 → 一般設定 → 🔤 全介面文字大小調節』（提供下拉字級、A+/A- 及防卡頓滑桿）。\n"
            "7. 模組化 CDR / 防毒資安中心與技能/MCP 表格：右側『🛡️ 防毒與資安』支援模組化動態載入（可在設定或選單切換啟用/卸載）；『🛠️ 技能與 MCP』表格支援自動換行、懸停完整提示與點擊下方詳情預覽框，不必拉全螢幕也能看清楚。\n"
            "8. 跨專案開發：Syntra 支援直接跨目錄讀寫電腦上任何專案（例如同時維護 `my_agent` 與 `idea_studiio` / Keli 專案），也可在左側檔案總管或畫布『🖥 讀取電腦』掛載任意專案路徑。\n"
        )
        if "【Syntra 星樞本地軟體操作內建知識庫" not in AgentBrain.SYSTEM_PROMPT:
            AgentBrain.SYSTEM_PROMPT = AgentBrain.SYSTEM_PROMPT + guide_summary
        brain = getattr(main_win, "agent_brain", None)
        if brain is not None and "【Syntra 星樞本地軟體操作內建知識庫" not in getattr(brain, "SYSTEM_PROMPT", ""):
            brain.SYSTEM_PROMPT = AgentBrain.SYSTEM_PROMPT
    except Exception as e:
        print(f"[EvolutionHub] _install_local_guide_chat_qa_tool error: {e}")


def _enhance_mcp_and_skills_tables(main_win: Any) -> None:
    """
    優化右側『🛠️ 技能與 MCP』分頁中的 `table_skills` 與 `table_mcp`：
    解決在非全螢幕/窄視窗下文字被截斷看不清楚要做什麼的問題：
    1. 開啟自動換行 (`setWordWrap(True)`) 與多行自適應列高 (`ResizeToContents`)。
    2. 為每個儲存格補上完整的多行 Tooltip。
    3. 在表格下方新增「🔎 點選項目完整說明預覽框」，點選任一列即可在不拉全螢幕的情況下看清楚該技能或 MCP 伺服器的完整用途與參數！
    """
    from PyQt5.QtWidgets import QHeaderView, QTableWidget

    detail_label = None
    if hasattr(main_win, "table_mcp"):
        mcp_parent = main_win.table_mcp.parentWidget()
        mcp_lay = mcp_parent.layout() if mcp_parent else None
        if mcp_lay is not None and not hasattr(main_win, "lbl_skill_mcp_detail_box"):
            detail_label = QLabel(
                "💡 <b>項目詳情預覽</b>：直接點選上方「內建技能」或「MCP 工具」表格中的任一列，即可在此查看完整功能說明（無須拉大視窗）。"
            )
            detail_label.setWordWrap(True)
            detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_label.setStyleSheet("""
                QLabel {
                    background: #141926;
                    color: #e2e8f0;
                    border: 1px solid rgba(56, 189, 248, 0.35);
                    border-radius: 8px;
                    padding: 8px 10px;
                    font-size: 12px;
                }
            """)
            mcp_lay.addWidget(detail_label)
            main_win.lbl_skill_mcp_detail_box = detail_label

    def _polish_table(tbl: Optional[QTableWidget], kind_title: str):
        if tbl is None:
            return
        tbl.setWordWrap(True)
        tbl.setTextElideMode(Qt.ElideNone)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionBehavior(QTableWidget.SelectRows)
        tbl.setSelectionMode(QTableWidget.SingleSelection)
        tbl.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        tbl.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        tbl.setMinimumHeight(185)
        tbl.setStyleSheet("""
            QTableWidget {
                background: #0f1420;
                alternate-background-color: #151c2c;
                color: #f1f5f9;
                gridline-color: rgba(148, 163, 184, 0.16);
                border: 1px solid rgba(148, 163, 184, 0.24);
                border-radius: 8px;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
            }
            QTableWidget::item:selected {
                background: rgba(2, 132, 199, 0.38);
                color: #ffffff;
            }
            QHeaderView::section {
                background: #1e293b;
                color: #38bdf8;
                font-weight: 700;
                font-size: 12px;
                padding: 5px 6px;
                border: none;
                border-bottom: 1px solid rgba(56, 189, 248, 0.3);
            }
        """)
        hh = tbl.horizontalHeader()
        vh = tbl.verticalHeader()
        if hh is not None:
            hh.setSectionResizeMode(0, QHeaderView.Interactive)
            hh.resizeSection(0, 125)
            if tbl.columnCount() >= 3:
                hh.setSectionResizeMode(1, QHeaderView.Interactive)
                hh.resizeSection(1, 78)
                hh.setSectionResizeMode(2, QHeaderView.Stretch)
            elif tbl.columnCount() == 2:
                hh.setSectionResizeMode(1, QHeaderView.Stretch)
        if vh is not None:
            vh.setSectionResizeMode(QHeaderView.ResizeToContents)

        def _refresh_tooltips():
            rows = tbl.rowCount()
            cols = tbl.columnCount()
            for r in range(rows):
                row_texts = []
                for c in range(cols):
                    it = tbl.item(r, c)
                    if it and it.text():
                        row_texts.append(it.text())
                full_tip = " | ".join(row_texts)
                for c in range(cols):
                    it = tbl.item(r, c)
                    if it:
                        it.setToolTip(
                            f"【{kind_title}】\n" + "\n".join(
                                f"• {tbl.horizontalHeaderItem(i).text() if tbl.horizontalHeaderItem(i) else f'欄位{i+1}'}: "
                                f"{tbl.item(r, i).text() if tbl.item(r, i) else ''}"
                                for i in range(cols)
                            )
                        )
            tbl.resizeRowsToContents()

        def _on_cell_clicked(row: int, _col: int):
            box = getattr(main_win, "lbl_skill_mcp_detail_box", None)
            if box is None or row < 0 or row >= tbl.rowCount():
                return
            cols = tbl.columnCount()
            parts = []
            for i in range(cols):
                h_txt = tbl.horizontalHeaderItem(i).text() if tbl.horizontalHeaderItem(i) else f"欄位 {i+1}"
                v_txt = tbl.item(row, i).text() if tbl.item(row, i) else ""
                parts.append(f"<b>{html.escape(h_txt)}</b>：{html.escape(v_txt)}")
            box.setText(f"🔎 <b>【{html.escape(kind_title)} 詳細資訊】</b><br>" + "<br>".join(parts))

        _refresh_tooltips()
        tbl.cellClicked.connect(_on_cell_clicked)
        return _refresh_tooltips

    refresh_skills_tips = _polish_table(getattr(main_win, "table_skills", None), "內建技能 (Skill)")
    refresh_mcp_tips = _polish_table(getattr(main_win, "table_mcp", None), "MCP 擴充與 CDR 工具")

    if hasattr(main_win, "_refresh_skills_and_mcp_tables") and not getattr(main_win, "_skills_mcp_wrapped", False):
        main_win._skills_mcp_wrapped = True
        _orig_refresh_tables = main_win._refresh_skills_and_mcp_tables

        def _patched_refresh_skills_and_mcp_tables():
            _orig_refresh_tables()
            if refresh_skills_tips:
                refresh_skills_tips()
            if refresh_mcp_tips:
                refresh_mcp_tips()

        main_win._refresh_skills_and_mcp_tables = _patched_refresh_skills_and_mcp_tables


def _install_modular_cdr_tab_switch(main_win: Any) -> None:
    """
    將原本寫死在右側分頁的『🛡️ 防毒與資安 (CDR)』改為可動態載入/卸載的模組化架構：
    - 依據 `settings.permissions.features.security_guard` 與 DLC 模組狀態動態顯示或卸載『🛡️ 防毒與資安』分頁。
    - 在上方『設定 (Settings)』選單提供『🧩 動態掛載 / 卸載 CDR 防毒與資安模組』一鍵開關，需要時秒開、不需要時可隨時收納不佔空間！
    """
    right_tabs = getattr(main_win, "right_tabs", None)
    tab_sec = getattr(main_win, "tab_security", None)
    if right_tabs is None or tab_sec is None:
        return

    def _sync_cdr_module_tab(enabled: bool):
        idx = right_tabs.indexOf(tab_sec)
        if enabled and idx == -1:
            right_tabs.insertTab(1, tab_sec, "🛡️ 防毒與資安 (模組)")
        elif not enabled and idx != -1:
            right_tabs.removeTab(idx)

    # 讀取目前設定中的 security_guard 模組開關（預設啟用）
    raw = main_win.settings_manager.get_raw() if hasattr(main_win, "settings_manager") else {}
    sec_enabled = (
        raw.get("permissions", {})
        .get("features", {})
        .get("security_guard", True)
    )
    idx_now = right_tabs.indexOf(tab_sec)
    if idx_now != -1:
        right_tabs.setTabText(idx_now, "🛡️ 防毒與資安 (模組)")
    _sync_cdr_module_tab(bool(sec_enabled))

    # 在上方『設定』選單加入模組化動態開關
    menubar = main_win.menuBar()
    if menubar is not None:
        for act in menubar.actions():
            menu = act.menu()
            if menu is not None and ("設定" in act.text() or "Settings" in act.text()):
                menu.addSeparator()
                act_mod_cdr = QAction("🧩 啟用『CDR 防毒與資安』動態模組分頁", main_win)
                act_mod_cdr.setCheckable(True)
                act_mod_cdr.setChecked(bool(sec_enabled))

                def _on_toggle_cdr_mod(checked: bool):
                    _sync_cdr_module_tab(checked)
                    try:
                        r = main_win.settings_manager.get_raw()
                        perms = r.setdefault("permissions", {})
                        feats = perms.setdefault("features", {})
                        feats["security_guard"] = bool(checked)
                        main_win.settings_manager.update_settings({"permissions": perms})
                    except Exception:
                        pass
                    state_txt = "已動態載入『🛡️ 防毒與資安』模組分頁" if checked else "已動態卸載並隱藏『🛡️ 防毒與資安』模組分頁（背景基礎防護仍可於設定管理）"
                    main_win.statusBar().showMessage(f"🧩 {state_txt}", 4500)

                act_mod_cdr.toggled.connect(_on_toggle_cdr_mod)
                menu.addAction(act_mod_cdr)
                main_win.act_modular_cdr_toggle = act_mod_cdr
                break

