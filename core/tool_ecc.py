"""
ECC (Error-Checking and Correction) 工具調用檢查與自癒引擎
職責：
1. 語法容錯解析：修復 LLM 輸出的破損 JSON（未閉合、單引號、尾隨逗號、Windows 反斜線路徑無跳脫、註解干擾等）。
2. 結構別名正規化：支援 action/function/parameters/params 等各類 LLM 常見欄位別名自動映射。
3. 工具名稱模糊校正 (Tool Alias Resolution)：識別常用工具別名 (如 cmd/shell/screenshot/click)，防止虛構工具 (Hallucination) 導致中斷。
4. 參數型別自癒與邊界校正：自動轉換 HWND（支援十六進位 0x 與十進位字串）、座標型別 (float/str -> int)、布林值強制轉換。
5. 診斷與審計日誌：記錄每次調用的 ECC 校正項目，並在無法修復時生成明確指引的自癒反饋。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("tool_ecc")


class ToolCallECC:
    # 支援的官方工具綱要與型別規範
    TOOL_SCHEMAS = {
        "inspect_accessibility_tree": {
            "required": [],
            "optional": ["hwnd", "max_depth", "max_nodes"],
            "types": {"hwnd": int, "max_depth": int, "max_nodes": int},
            "description": "透過 Windows 無障礙 API (UIA) 提取視窗結構樹與控制項 ID，代替截圖",
        },
        "ui_invoke": {
            "required": ["element_id"],
            "optional": [],
            "types": {"element_id": str},
            "description": "透過無障礙原生 InvokePattern 點擊按鈕或控制項 (零滑鼠干擾)",
        },
        "ui_type": {
            "required": ["element_id", "text"],
            "optional": [],
            "types": {"element_id": str, "text": str},
            "description": "透過無障礙原生 ValuePattern 寫入文字框 (極速無損)",
        },
        "ui_click": {
            "required": ["element_id"],
            "optional": ["button", "double"],
            "types": {"element_id": str, "button": str, "double": bool},
            "description": "計算無障礙元件邊界矩形中心點並點擊",
        },
        "ui_read_text": {
            "required": ["element_id"],
            "optional": [],
            "types": {"element_id": str},
            "description": "透過無障礙 TextPattern 讀取文件純文字",
        },
        "list_windows": {
            "required": [],
            "optional": [],
            "description": "列出目前桌面所有開啟中的視窗清單與 HWND",
        },
        "inspect_window_background": {
            "required": ["hwnd"],
            "optional": ["question"],
            "types": {"hwnd": int, "question": str},
            "description": "Win32 背景截圖並分析指定視窗內容 (不搶焦點)",
        },
        "capture_desktop_screen": {
            "required": [],
            "optional": ["question"],
            "types": {"question": str},
            "description": "主螢幕全螢幕截圖與視覺座標分析 (Set-of-Mark Grid)",
        },
        "click_screen": {
            "required": ["x", "y"],
            "optional": ["button", "double", "target_label"],
            "types": {"x": int, "y": int, "button": str, "double": bool, "target_label": str},
            "description": "擬人滑鼠點擊畫面座標",
        },
        "type_text": {
            "required": ["text"],
            "optional": ["press_enter", "target_label"],
            "types": {"text": str, "press_enter": bool, "target_label": str},
            "description": "文字輸入與中文剪貼簿無損貼上",
        },
        "send_ide_feedback": {
            "required": ["hwnd", "feedback_text"],
            "optional": ["x", "y", "press_enter"],
            "types": {"hwnd": int, "feedback_text": str, "x": int, "y": int, "press_enter": bool},
            "description": "將檢查結果與修正指令回填至寫程式的 IDE 視窗",
        },
        "list_installed_software": {
            "required": [],
            "optional": ["max_items"],
            "types": {"max_items": int},
            "description": "掃描本機登錄檔，列出已安裝軟體清冊（名稱/版本/發行商/安裝路徑），作為可開啟軟體的唯讀地圖，不需使用者同意",
        },
        "launch_application": {
            "required": ["target"],
            "optional": [],
            "types": {"target": str},
            "description": "開啟/啟動指定的本機應用程式；每次呼叫都會先跳出核准卡片要求使用者同意，使用者按下同意後才會真正開啟",
        },
        "dispatch_ai_coding_prompt": {
            "required": ["tool_hint", "prompt_text"],
            "optional": ["press_enter", "read_back_response", "response_wait_seconds"],
            "types": {
                "tool_hint": str,
                "prompt_text": str,
                "press_enter": bool,
                "read_back_response": bool,
                "response_wait_seconds": float,
            },
            "description": "自動尋找本機已開啟的 AI 編碼工具視窗（antigravity|vscode|codex|claude_code|cursor）並送出提示詞，可選擇讀回其結構樹作為回覆快照",
        },
        "run_background_shell": {
            "required": ["command"],
            "optional": ["cwd"],
            "types": {"command": str, "cwd": str},
            "description": "在背景執行系統指令 (PowerShell)",
        },
        "run_linux_shell": {
            "required": ["command"],
            "optional": ["cwd"],
            "types": {"command": str, "cwd": str},
            "description": "用 bash 執行 Linux 指令（Git Bash 或 WSL）",
        },
        "web_search": {
            "required": ["query"],
            "optional": ["purpose"],
            "types": {"query": str, "purpose": str},
            "description": "透過搜尋引擎查詢外部資訊與技術解法",
        },
        "web_fetch": {
            "required": ["url"],
            "optional": ["purpose"],
            "types": {"url": str, "purpose": str},
            "description": "安全擷取指定網頁全文內容",
        },
        "notify_discord": {
            "required": ["message"],
            "optional": [],
            "types": {"message": str},
            "description": "主動發送 Discord 通知給使用者",
        },
        "cdr_sanitize_file": {
            "required": ["file_path"],
            "optional": [],
            "types": {"file_path": str},
            "description": "執行檔案 CDR 內容威脅解除與重構",
        },
        "sandbox_execute": {
            "required": ["command"],
            "optional": ["timeout"],
            "types": {"command": str, "timeout": float},
            "description": "在受隔離的 Job Object 沙箱中執行指令",
        },
        "scan_antivirus": {
            "required": ["target_path"],
            "optional": ["auto_quarantine"],
            "types": {"target_path": str, "auto_quarantine": bool},
            "description": "執行複合式病毒掃描與威脅檢測",
        },
        "audit_system_security": {
            "required": [],
            "optional": [],
            "description": "檢查目前資安閘門狀態與稽核總覽",
        },
        "configure_api_provider": {
            "required": ["name", "base_url"],
            "optional": ["protocol", "api_key", "models"],
            "types": {"name": str, "base_url": str, "protocol": str, "api_key": str},
            "description": "新增或設定 LLM API Provider",
        },
        "install_skill": {
            "required": ["skill_name", "description", "instructions"],
            "optional": ["scripts"],
            "types": {"skill_name": str, "description": str, "instructions": str},
            "description": "動態安裝或建立新 Skill 模組，並可在終端執行 scripts",
        },
        "run_skill_script": {
            "required": ["skill_name", "script_name"],
            "optional": ["args", "cwd"],
            "types": {"skill_name": str, "script_name": str, "cwd": str},
            "description": "在終端安全執行指定 Skill 的腳本 (支援 py/ps1/bat/js)",
        },
        "list_installed_skills": {
            "required": [],
            "optional": [],
            "description": "列出本機所有已載入的技能模組清單",
        },
        "browser_navigate": {
            "required": ["url"],
            "optional": [],
            "types": {"url": str},
            "description": "操控真實無頭/擬人瀏覽器導航至指定網址",
        },
        "browser_screenshot": {
            "required": [],
            "optional": ["full_page"],
            "types": {"full_page": bool},
            "description": "擷取當前瀏覽器畫面真實渲染截圖供視覺大腦分析",
        },
        "browser_extract": {
            "required": [],
            "optional": [],
            "description": "智慧提取當前網頁文字、層級結構與可互動元件",
        },
        "browser_click": {
            "required": ["selector_or_text"],
            "optional": [],
            "types": {"selector_or_text": str},
            "description": "模擬點擊網頁中的元素、按鈕或連結",
        },
        "browser_type": {
            "required": ["selector", "text"],
            "optional": [],
            "types": {"selector": str, "text": str},
            "description": "在網頁輸入框中輸入文字",
        },
        "browser_close": {
            "required": [],
            "optional": [],
            "description": "關閉當前瀏覽器工作階段",
        },
    }

    # 工具名稱常見別名映射庫 (防止模型幻覺)
    TOOL_ALIASES = {
        # 終端與系統指令
        "cmd": "run_background_shell",
        "powershell": "run_background_shell",
        "shell": "run_background_shell",
        "terminal": "run_background_shell",
        "bash": "run_background_shell",
        "exec": "run_background_shell",
        "execute": "run_background_shell",
        "execute_command": "run_background_shell",
        "run_command": "run_background_shell",
        "run_shell": "run_background_shell",
        "run": "run_background_shell",
        # 搜尋與網頁
        "search": "web_search",
        "google": "web_search",
        "bing": "web_search",
        "duckduckgo": "web_search",
        "ddg": "web_search",
        "browse": "web_fetch",
        "fetch": "web_fetch",
        "fetch_url": "web_fetch",
        "open_url": "web_fetch",
        "get_url": "web_fetch",
        "read_url": "web_fetch",
        "web_page": "web_fetch",
        # 深度瀏覽器 (Browser)
        "browser_open": "browser_navigate",
        "goto_url": "browser_navigate",
        "open_browser": "browser_navigate",
        "navigate": "browser_navigate",
        "browser_capture": "browser_screenshot",
        "web_screenshot": "browser_screenshot",
        "browser_dom": "browser_extract",
        "browser_read": "browser_extract",
        "extract_page": "browser_extract",
        "web_click": "browser_click",
        "click_web": "browser_click",
        "web_type": "browser_type",
        "type_web": "browser_type",
        "close_browser": "browser_close",
        # Skill / 技能生態
        "add_skill": "install_skill",
        "create_skill": "install_skill",
        "execute_skill": "run_skill_script",
        "run_skill": "run_skill_script",
        "skill_run": "run_skill_script",
        "list_skills": "list_installed_skills",
        "get_skills": "list_installed_skills",
        # 作業系統無障礙 (Accessibility UI Automation)
        "accessibility": "inspect_accessibility_tree",
        "accessibility_tree": "inspect_accessibility_tree",
        "ui_tree": "inspect_accessibility_tree",
        "get_ui_tree": "inspect_accessibility_tree",
        "uia_tree": "inspect_accessibility_tree",
        "inspect_ui": "inspect_accessibility_tree",
        "uia_invoke": "ui_invoke",
        "invoke_ui": "ui_invoke",
        "invoke": "ui_invoke",
        "uia_type": "ui_type",
        "type_ui": "ui_type",
        "uia_click": "ui_click",
        "click_ui": "ui_click",
        "read_ui_text": "ui_read_text",
        "read_text": "ui_read_text",
        # 桌面與視覺
        "screenshot": "capture_desktop_screen",
        "desktop": "capture_desktop_screen",
        "get_screen": "capture_desktop_screen",
        "capture_screen": "capture_desktop_screen",
        "screen": "capture_desktop_screen",
        "screen_capture": "capture_desktop_screen",
        "inspect": "inspect_window_background",
        "inspect_window": "inspect_window_background",
        "check_window": "inspect_window_background",
        "window_screenshot": "inspect_window_background",
        "view_window": "inspect_window_background",
        "windows": "list_windows",
        "get_windows": "list_windows",
        "list_window": "list_windows",
        "find_windows": "list_windows",
        # 滑鼠與鍵盤
        "click": "click_screen",
        "mouse_click": "click_screen",
        "left_click": "click_screen",
        "right_click": "click_screen",
        "click_mouse": "click_screen",
        "type": "type_text",
        "input_text": "type_text",
        "write_text": "type_text",
        "send_keys": "type_text",
        "keyboard": "type_text",
        "ide_feedback": "send_ide_feedback",
        "feedback": "send_ide_feedback",
        "reply_ide": "send_ide_feedback",
        "send_feedback": "send_ide_feedback",
        "list_software": "list_installed_software",
        "installed_apps": "list_installed_software",
        "list_apps": "list_installed_software",
        "software_map": "list_installed_software",
        "open_app": "launch_application",
        "open_software": "launch_application",
        "start_app": "launch_application",
        "run_app": "launch_application",
        "dispatch_prompt": "dispatch_ai_coding_prompt",
        "send_prompt": "dispatch_ai_coding_prompt",
        "send_to_ai_tool": "dispatch_ai_coding_prompt",
        "ask_antigravity": "dispatch_ai_coding_prompt",
        "ask_vscode": "dispatch_ai_coding_prompt",
        "ask_codex": "dispatch_ai_coding_prompt",
        "ask_claude_code": "dispatch_ai_coding_prompt",
        "ask_cursor": "dispatch_ai_coding_prompt",
        # 資安與通報
        "antivirus": "scan_antivirus",
        "scan": "scan_antivirus",
        "scan_file": "scan_antivirus",
        "defender": "scan_antivirus",
        "cdr": "cdr_sanitize_file",
        "disarm": "cdr_sanitize_file",
        "sanitize": "cdr_sanitize_file",
        "sandbox": "sandbox_execute",
        "discord": "notify_discord",
        "notify": "notify_discord",
    }

    # 欄位別名映射
    TOOL_KEY_ALIASES = ["tool", "name", "action", "function", "tool_name", "call", "command_name"]
    ARGS_KEY_ALIASES = ["args", "parameters", "params", "arguments", "input", "payload", "inputs", "data"]

    @classmethod
    def clean_and_repair_json(cls, raw_str: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """
        ECC 核心：深度修復各類常見的模型輸出 JSON 破損問題
        """
        corrections: List[str] = []
        text = raw_str.strip()

        # 1. 移除 Markdown 區塊包裹 (```tool_call, ```json 等)
        fence_match = re.search(r"```(?:tool_call|json|python)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
            corrections.append("解構 Markdown 程式碼區塊")
        else:
            # 尋找最外層的 { 與 }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start : end + 1].strip()
                corrections.append("擷取最外層 JSON 大括號")

        # 嘗試直接解析
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed, corrections
        except Exception:
            pass

        # 2. 修復 Windows 路徑中的未跳脫單反斜線 (如 C:\Users\User -> C:\\Users\\User)
        orig_text = text
        text = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r"\\\\", text)
        if text != orig_text:
            corrections.append("自動跳脫 Windows 路徑反斜線 (\\ -> \\\\)")

        # 3. 移除 JavaScript/C 風格註解 (// ... 與 /* ... */)
        text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

        # 4. 移除物件與陣列結尾的多餘逗號 (Trailing Commas: e.g. {"a": 1, })
        text = re.sub(r",\s*([\}\]])", r"\1", text)

        # 5. 單引號轉雙引號修復 (將 'key': 'val' 轉為 "key": "val")
        if "'" in text and '"' not in text:
            text = re.sub(r"(?<=[\{\s,])\'([a-zA-Z0-9_\-\.]+)\'\s*:", r'"\1":', text)
            text = re.sub(r":\s*\'([^\']*?)\'", r': "\1"', text)
            corrections.append("單引號自動轉換為標準 JSON 雙引號")

        # 6. 二次嘗試解析修復後文字
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed, corrections
        except Exception:
            pass

        # 7. 暴力容錯：嘗試以正則手動提取 tool 與 args
        tool_m = re.search(r'["\'](?:tool|action|name|function)["\']\s*:\s*["\']([a-zA-Z0-9_\-]+)["\']', raw_str)
        if tool_m:
            recovered_tool = tool_m.group(1)
            recovered_args = {}
            # 嘗試擷取 args 物件
            args_m = re.search(r'["\'](?:args|parameters|params|arguments)["\']\s*:\s*(\{.*?\})', raw_str, re.DOTALL)
            if args_m:
                try:
                    repaired_args_str = re.sub(r",\s*([\}\]])", r"\1", args_m.group(1))
                    repaired_args_str = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r"\\\\", repaired_args_str)
                    recovered_args = json.loads(repaired_args_str)
                except Exception:
                    pass
            corrections.append(f"透過正則救回工具調用 [{recovered_tool}]")
            return {"tool": recovered_tool, "args": recovered_args}, corrections

        return None, corrections

    @classmethod
    def inspect_and_correct(cls, raw_text: str) -> Dict[str, Any]:
        """
        對模型輸出進行完整的 ECC 檢查、校正與型別自癒：
        回傳：
        {
            "is_tool_call": bool,
            "ok": bool,
            "tool": str,
            "args": dict,
            "corrections": list[str],
            "error": str,
            "recovery_guidance": str
        }
        """
        result = {
            "is_tool_call": False,
            "ok": False,
            "tool": "",
            "args": {},
            "corrections": [],
            "error": "",
            "recovery_guidance": "",
        }

        # 判斷是否含有工具調用特徵 (包含 code block 或任何工具欄位別名)
        raw_lower = raw_text.lower()
        has_tool_cue = (
            "```tool_call" in raw_lower
            or any(f'"{alias}"' in raw_lower or f"'{alias}'" in raw_lower for alias in cls.TOOL_KEY_ALIASES)
            or any(t in raw_lower for t in cls.TOOL_SCHEMAS.keys())
        )
        if not has_tool_cue:
            # 純對話回覆，不屬於工具調用
            return result

        result["is_tool_call"] = True

        # 1. 語法解析與 JSON 自癒
        parsed_obj, json_corrections = cls.clean_and_repair_json(raw_text)
        result["corrections"].extend(json_corrections)

        if not parsed_obj:
            result["error"] = "語法無法解析為有效 JSON，請依標準格式 `{\"tool\": \"...\", \"args\": {...}}` 重新輸出。"
            result["recovery_guidance"] = (
                "【ECC 工具調用語法錯誤】未能從文字中解析出有效 JSON。\n"
                "正確格式範例：\n"
                "```tool_call\n"
                '{"tool": "list_windows", "args": {}}\n'
                "```"
            )
            return result

        # 2. 結構別名正規化 (Schema Normalization)
        tool_name = ""
        for alias in cls.TOOL_KEY_ALIASES:
            if alias in parsed_obj and isinstance(parsed_obj[alias], str):
                tool_name = parsed_obj[alias].strip()
                if alias != "tool":
                    result["corrections"].append(f"欄位別名正規化：'{alias}' -> 'tool'")
                break

        args_dict = {}
        for alias in cls.ARGS_KEY_ALIASES:
            if alias in parsed_obj and isinstance(parsed_obj[alias], dict):
                args_dict = parsed_obj[alias]
                if alias != "args":
                    result["corrections"].append(f"參數別名正規化：'{alias}' -> 'args'")
                break

        # 若模型直接把參數打在第一層 (無 args 外皮)
        if not args_dict and tool_name:
            extra_keys = {k: v for k, v in parsed_obj.items() if k not in cls.TOOL_KEY_ALIASES}
            if extra_keys:
                args_dict = extra_keys
                result["corrections"].append("平坦結構轉換：將頂層參數收納至 'args' 物件")

        if not tool_name:
            result["error"] = "未能找到工具名稱欄位 (缺少 'tool' 屬性)。"
            return result

        # 3. 工具別名與幻覺校正 (Tool Name Resolution)
        t_lower = tool_name.lower().strip()
        if t_lower in cls.TOOL_ALIASES:
            canonical_tool = cls.TOOL_ALIASES[t_lower]
            result["corrections"].append(f"工具名稱別名校正：'{tool_name}' -> '{canonical_tool}'")
            tool_name = canonical_tool

        if tool_name not in cls.TOOL_SCHEMAS:
            valid_list = ", ".join(list(cls.TOOL_SCHEMAS.keys())[:8])
            result["error"] = f"未知的工具名稱「{tool_name}」。"
            result["recovery_guidance"] = f"系統中不存在工具 '{tool_name}'。常用支援工具包括：{valid_list} 等。"
            return result

        # 4. 參數型別自癒與約束校正 (Parameter Type Coercion)
        schema = cls.TOOL_SCHEMAS[tool_name]
        type_rules = schema.get("types", {})
        cleaned_args = {}

        for k, v in args_dict.items():
            if k in type_rules:
                expected_type = type_rules[k]
                try:
                    if expected_type is int:
                        # HWND 與座標轉換 (支援 0x12a 十六進位字串、'123' 字串、12.3 浮點數)
                        if isinstance(v, str):
                            v_clean = v.strip()
                            if v_clean.lower().startswith("0x"):
                                cleaned_val = int(v_clean, 16)
                            else:
                                cleaned_val = int(round(float(v_clean)))
                            result["corrections"].append(f"參數 [{k}] 型別強制轉換：'{v}' -> {cleaned_val} (int)")
                        elif isinstance(v, float):
                            cleaned_val = int(round(v))
                            result["corrections"].append(f"參數 [{k}] 四捨五入浮點數：{v} -> {cleaned_val} (int)")
                        else:
                            cleaned_val = int(v)
                        cleaned_args[k] = cleaned_val

                    elif expected_type is bool:
                        if isinstance(v, str):
                            cleaned_val = v.strip().lower() in ("true", "1", "yes", "t", "y")
                            result["corrections"].append(f"參數 [{k}] 布林解析：'{v}' -> {cleaned_val}")
                        else:
                            cleaned_val = bool(v)
                        cleaned_args[k] = cleaned_val

                    elif expected_type is float:
                        cleaned_args[k] = float(v)

                    elif expected_type is str:
                        cleaned_args[k] = str(v)
                    else:
                        cleaned_args[k] = v
                except Exception as e:
                    logger.warning(f"ECC 參數型別轉換失敗 ({k}={v}): {e}")
                    cleaned_args[k] = v
            else:
                cleaned_args[k] = v

        # 5. 必填參數缺失檢查
        missing_required = [req for req in schema.get("required", []) if req not in cleaned_args]
        if missing_required:
            result["error"] = f"工具 [{tool_name}] 缺少必填參數：{', '.join(missing_required)}。"
            result["recovery_guidance"] = (
                f"呼叫工具 [{tool_name}] 時遺漏了必要參數：{missing_required}。\n"
                f"說明：{schema.get('description', '')}\n"
                f"請補齊參數後重新調用。"
            )
            return result

        result["ok"] = True
        result["tool"] = tool_name
        result["args"] = cleaned_args
        return result
