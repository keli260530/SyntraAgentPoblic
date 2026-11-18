import re
from typing import Any, Dict, List, Optional, Tuple


class ApiKeyDetector:
    """
    職責：依據 API Key 的特徵編碼、前綴與長度自動判斷所屬公司/Provider，
    並自動產生格式化的『公司名稱 (金鑰 #N)』與推薦模型清單，同時允許使用者自訂覆寫。
    """

    PATTERNS: List[Tuple[str, str, str, str, List[str]]] = [
        # (識別碼, 公司名稱, 協定, Base URL, 推薦模型)
        (
            r"^AIzaSy[A-Za-z0-9_-]{33}$",
            "Google Gemini",
            "openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
        ),
        (
            r"^sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{80,110}$",
            "Anthropic Claude",
            "anthropic",
            "https://api.anthropic.com/v1",
            ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest"],
        ),
        (
            r"^sk-proj-[A-Za-z0-9_-]{80,180}$",
            "OpenAI 官方",
            "openai",
            "https://api.openai.com/v1",
            ["gpt-4o", "gpt-4.1", "o3-mini"],
        ),
        (
            r"^sk-[a-f0-9]{32,64}$",
            "DeepSeek",
            "openai",
            "https://api.deepseek.com/v1",
            ["deepseek-chat", "deepseek-reasoner"],
        ),
        (
            r"^sk-or-v1-[a-f0-9]{64}$",
            "OpenRouter",
            "openai",
            "https://openrouter.ai/api/v1",
            ["google/gemini-2.5-pro", "anthropic/claude-3.7-sonnet", "openai/gpt-4o"],
        ),
        (
            r"^gsk_[A-Za-z0-9_-]{40,70}$",
            "Groq 高速推理",
            "openai",
            "https://api.groq.com/openai/v1",
            ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
        ),
        (
            r"^nvapi-[A-Za-z0-9_-]{50,110}$",
            "NVIDIA NIM",
            "openai",
            "https://integrate.api.nvidia.com/v1",
            ["deepseek-ai/deepseek-r1", "meta/llama-3.2-11b-vision-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"],
        ),
    ]

    def __init__(self):
        pass

    def detect_and_suggest(
        self,
        api_key: str,
        existing_providers: List[Dict[str, Any]],
        manual_override_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分析 API Key 字串：
        1. 自動判斷公司
        2. 計算該公司已存在幾組 Key，自動產生『公司名 (金鑰 #N)』
        3. 回傳自動辨識結果（包含推薦端點與模型），若使用者有自訂名稱則以自訂為主
        """
        key = api_key.strip()
        matched_company = "自訂 API"
        protocol = "openai"
        base_url = "https://api.openai.com/v1"
        models = ["gpt-4o"]

        # 優先正則精準比對
        for pat, comp_name, proto, url, m_list in self.PATTERNS:
            if re.match(pat, key):
                matched_company = comp_name
                protocol = proto
                base_url = url
                models = m_list
                break
        else:
            # 次級啟發式前綴比對
            if key.startswith("AIzaSy"):
                matched_company = "Google Gemini"
                protocol = "openai"
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                models = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"]
            elif key.startswith("sk-ant"):
                matched_company = "Anthropic Claude"
                protocol = "anthropic"
                base_url = "https://api.anthropic.com/v1"
                models = ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-latest"]
            elif key.startswith("sk-proj-") or (key.startswith("sk-") and len(key) >= 48):
                matched_company = "OpenAI"
                protocol = "openai"
                base_url = "https://api.openai.com/v1"
                models = ["gpt-4o", "gpt-4.1", "o3-mini"]
            elif key.startswith("gsk_"):
                matched_company = "Groq"
                protocol = "openai"
                base_url = "https://api.groq.com/openai/v1"
                models = ["llama-3.3-70b-versatile"]

        # 計算編號：例如目前已有 1 個 Gemini，這組自動命名為『Google Gemini (金鑰 #2)』
        existing_same_company_count = 0
        for p in existing_providers:
            p_name = p.get("name", "")
            if matched_company.lower() in p_name.lower():
                existing_same_company_count += 1

        suggested_index = existing_same_company_count + 1
        auto_name = f"{matched_company} (金鑰 #{suggested_index})"
        final_name = manual_override_name.strip() if manual_override_name and manual_override_name.strip() else auto_name

        return {
            "detected": matched_company != "自訂 API",
            "company": matched_company,
            "auto_name": auto_name,
            "final_name": final_name,
            "protocol": protocol,
            "base_url": base_url,
            "suggested_models": models,
        }
