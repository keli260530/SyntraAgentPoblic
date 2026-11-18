"""
智慧模型路由器 (Intelligent Model Router)
職責：
1. 模型特徵與能力庫：識別視覺 (Vision)、深度推理 (Reasoning)、程式碼研發 (Coding)、高速輕量 (Fast)。
2. 任務意圖路由：根據是否有圖片、任務類型（視覺定位、代碼審查、一般對話、輕量工具）自動分配最優模型。
3. 故障容錯與自動降級 (Failover)：當首選模型遭遇 429 速率限制、404 模型失效、500 伺服器錯誤或未開通權限時，自動切換至備援模型。
4. 提供自動路由 ("auto_router") 模式，與使用者手動指定模型無縫相容。
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("model_router")


class ModelRouter:
    # 關鍵字特徵庫
    VISION_KEYWORDS = [
        "vision", "vl", "gemini", "gpt-4o", "gpt-4-turbo", "claude-3",
        "omni", "llava", "pixtral", "qwen-vl", "qwen2-vl", "qwen2.5-vl",
        "deepseek-vl", "11b-vision", "90b-vision", "gemma3", "mistral-small3"
    ]

    REASONING_KEYWORDS = [
        "reasoner", "r1", "o1", "o3", "thinking", "gemini-2.5-pro",
        "claude-3-7", "qwq", "deepseek-r1", "nemotron", "gpt-oss"
    ]

    CODING_KEYWORDS = [
        "coder", "codestral", "claude-3-7", "claude-3-5", "gpt-4o",
        "gemini-2.5-pro", "deepseek-coder", "deepseek-v3", "starcoder",
        "deepseek-reasoner", "gpt-oss", "gemma3"
    ]

    FAST_KEYWORDS = [
        "flash", "mini", "haiku", "8b", "7b", "12b", "3b", "1.5b", "qwen2.5-3b", "syntra-3b",
        "gemma3", "versatile", "fast", "deepseek-chat"
    ]

    def __init__(self, api_manager):
        self.api_manager = api_manager
        self.routing_logs: List[Dict[str, Any]] = []
        self._node_cooldowns: Dict[str, float] = {}

    def report_node_failure(self, full_id: str, cooldown_sec: float = 45.0) -> None:
        """Pathways 風格節點故障冷卻：標記異常節點，後續調度自動重映射至健康節點。"""
        if full_id:
            self._node_cooldowns[full_id] = time.time() + max(1.0, float(cooldown_sec))

    def report_node_success(self, full_id: str) -> None:
        if full_id:
            self._node_cooldowns.pop(full_id, None)

    def is_node_healthy(self, full_id: str) -> bool:
        until = self._node_cooldowns.get(full_id)
        if until is None:
            return True
        if time.time() >= until:
            self._node_cooldowns.pop(full_id, None)
            return True
        return False

    @staticmethod
    def is_local_item(item: Dict[str, Any]) -> bool:
        """判斷該候選模型是否為本機 Ollama / Localhost 零成本端點"""
        burl = (item.get("base_url") or "").lower()
        pid = (item.get("provider_id") or "").lower()
        return "127.0.0.1" in burl or "localhost" in burl or "ollama" in pid

    def classify_model(self, model_id: str) -> Dict[str, bool]:
        """判斷特定模型具備之能力特徵"""
        m_lower = model_id.lower()
        return {
            "vision": any(k in m_lower for k in self.VISION_KEYWORDS),
            "reasoning": any(k in m_lower for k in self.REASONING_KEYWORDS),
            "coding": any(k in m_lower for k in self.CODING_KEYWORDS),
            "fast": any(k in m_lower for k in self.FAST_KEYWORDS),
        }

    def infer_task_type(
        self,
        messages: List[Dict[str, Any]],
        has_image: bool = False,
        explicit_type: Optional[str] = None,
    ) -> str:
        """推論任務類型：vision | reasoning | coding | fast | general"""
        if has_image:
            return "vision"
        if explicit_type:
            return explicit_type

        # 檢視最後一則 user 訊息特徵
        last_user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, str):
                    last_user_content = c
                elif isinstance(c, list):
                    for part in c:
                        if isinstance(part, dict) and part.get("type") == "text":
                            last_user_content += part.get("text", "")
                break

        u_lower = last_user_content.lower()

        # 代碼與報錯特徵
        code_markers = [
            "def ", "class ", "import ", "traceback", "error", "exception",
            "bug", "git", "docker", "```", "function", "fix", "修復",
            "代碼", "程式碼", "語法", "script", "py"
        ]
        if any(m in u_lower for m in code_markers):
            return "coding"

        # 推理思考特徵
        reason_markers = [
            "為什麼", "分析", "架構", "方案", "比較", "理由",
            "步驟", "規劃", "審查", "audit", "plan", "why", "compare", "思考"
        ]
        if any(m in u_lower for m in reason_markers):
            return "reasoning"

        if len(last_user_content) < 40 and not any(k in u_lower for k in ["請", "幫我", "寫"]):
            return "fast"

        return "general"

    def resolve_candidates(
        self,
        task_type: str = "general",
        has_image: bool = False,
        preferred: Optional[str] = None,
        difficulty: str = "LOCAL_CAPABLE",
    ) -> List[Dict[str, Any]]:
        """
        依據任務需求、任務難度 (LOCAL_CAPABLE vs CLOUD_API_REQUIRED)、圖片限制與可用 API Key，生成有序的候選連線清單
        """
        catalog = self.api_manager.get_models_catalog()

        # 1. 篩選有填 API Key 的可用項目
        keyed_catalog = [item for item in catalog if item.get("has_key")]
        if not keyed_catalog:
            keyed_catalog = catalog  # 若都沒有 Key，退回全部以給出明確的未填 Key 提示

        is_auto_mode = not preferred or preferred in ["auto", "auto_router", "default"]

        candidates: List[Dict[str, Any]] = []
        seen_full_ids = set()

        def add_candidate(item: Dict[str, Any], reason: str):
            fid = item["full_id"]
            if fid in seen_full_ids:
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
            })

        # 難度加權排序器：
        # - CLOUD_API_REQUIRED (高難度): 雲端強模 API 排最前 (score +100)，本地模型作斷網備援
        # - LOCAL_CAPABLE (一般對話/輕中度任務): 本地 Ollama 模型排最前 (score +100，省 API 額度且免外傳)，雲端作備援
        def tier_sort_key(m: Dict[str, Any], extra_score: int = 0) -> int:
            local = self.is_local_item(m)
            mid = m["model_id"].lower()
            base = extra_score
            if difficulty == "CLOUD_API_REQUIRED":
                base += (0 if local else 100)
                if any(k in mid for k in ("pro", "gpt-4o", "claude-3-7", "claude-3-5", "r1", "nemotron")):
                    base += 30
            else:
                base += (100 if local else 0)
                if "gpt-oss" in mid and not has_image and task_type != "fast":
                    base += 20
                elif ("3b" in mid or "syntra-3b" in mid or "1.5b" in mid) and not has_image and task_type == "fast":
                    base += 25
                elif "gemma3" in mid and (has_image or task_type == "fast"):
                    base += 20
            return base

        if not is_auto_mode:
            # 使用者明確指定了模型，但若任務難度被判定為 CLOUD_API_REQUIRED 且使用者指定的是本地小模型，可把雲端 API 放備援或升級
            target_item = next((m for m in catalog if m["full_id"] == preferred or m["model_id"] == preferred), None)
            if target_item:
                target_caps = self.classify_model(target_item["model_id"])
                if has_image and not target_caps["vision"]:
                    vision_fallback = next((m for m in keyed_catalog if self.classify_model(m["model_id"])["vision"]), None)
                    if vision_fallback:
                        add_candidate(
                            vision_fallback,
                            f"⚠️ 檢測到圖片任務，但指定模型 [{target_item['model_id']}] 不支援視覺，智慧路由優先分派至視覺模型 [{vision_fallback['display_name']}]"
                        )
                if difficulty == "CLOUD_API_REQUIRED" and self.is_local_item(target_item):
                    cloud_heavy = next(
                        (m for m in keyed_catalog if not self.is_local_item(m) and (self.classify_model(m["model_id"])["reasoning"] or self.classify_model(m["model_id"])["coding"])),
                        None,
                    )
                    if cloud_heavy:
                        add_candidate(
                            cloud_heavy,
                            f"☁️ 檢測到高難度任務 ({difficulty})，自動升級調用雲端強模 API [{cloud_heavy['display_name']}]"
                        )
                add_candidate(target_item, f"🎯 使用者指定模型：{target_item['display_name']}")

        tier_label = "☁️ 高難度調用雲端 API" if difficulty == "CLOUD_API_REQUIRED" else "🏠 本機模型優先"

        # 2. 依據任務類型與難度分層進行智慧排序
        if has_image or task_type == "vision":
            vision_models = [m for m in keyed_catalog if self.classify_model(m["model_id"])["vision"]]
            def vision_score(m):
                mid = m["model_id"].lower()
                s = 10 if ("gemini-2.5" in mid or "gpt-4o" in mid or "claude-3-5" in mid) else (8 if ("gemini" in mid or "gemma3" in mid or "vision" in mid or "vl" in mid) else 5)
                return tier_sort_key(m, s)
            vision_models.sort(key=vision_score, reverse=True)
            for vm in vision_models:
                add_candidate(vm, f"👁️ 視覺辨識任務 ({tier_label}) -> [{vm['display_name']}]")

        elif task_type == "reasoning":
            reasoning_models = [m for m in keyed_catalog if self.classify_model(m["model_id"])["reasoning"]]
            reasoning_models.sort(key=lambda m: tier_sort_key(m, 10), reverse=True)
            for rm in reasoning_models:
                add_candidate(rm, f"🧠 深度推理任務 ({tier_label}) -> [{rm['display_name']}]")

        elif task_type == "coding":
            coding_models = [m for m in keyed_catalog if self.classify_model(m["model_id"])["coding"]]
            coding_models.sort(key=lambda m: tier_sort_key(m, 10), reverse=True)
            for cm in coding_models:
                add_candidate(cm, f"💻 程式研發任務 ({tier_label}) -> [{cm['display_name']}]")

        elif task_type == "fast":
            fast_models = [m for m in keyed_catalog if self.classify_model(m["model_id"])["fast"]]
            fast_models.sort(key=lambda m: tier_sort_key(m, 10), reverse=True)
            for fm in fast_models:
                add_candidate(fm, f"⚡ 輕量快速對話 ({tier_label}) -> [{fm['display_name']}]")

        # 3. 一般對話與備援池（同樣遵循 LOCAL_CAPABLE 本地優先 / CLOUD_API_REQUIRED 雲端優先）
        sorted_pool = sorted(keyed_catalog, key=lambda m: tier_sort_key(m, 0), reverse=True)
        for item in sorted_pool:
            add_candidate(item, f"🛡️ 智慧分流 ({tier_label}) -> [{item['display_name']}]")

        # 若仍為空，補充所有 catalog 項目
        for item in catalog:
            add_candidate(item, f"🛡️ 基礎備援 [{item['display_name']}]")

        # 4. Pathways 彈性重映射：將健康節點排在冷卻中節點之前，避免重複踩雷
        healthy = [c for c in candidates if self.is_node_healthy(c["item"]["full_id"])]
        cooling = [c for c in candidates if not self.is_node_healthy(c["item"]["full_id"])]
        for c in cooling:
            c["routing_reason"] = f"⏳ 冷卻降權（已彈性重映射優先使用健康節點） | {c['routing_reason']}"
        return healthy + cooling

    def log_routing_event(self, event: Dict[str, Any]):
        """記錄路由調度與切換歷史"""
        self.routing_logs.append(event)
        if len(self.routing_logs) > 100:
            self.routing_logs.pop(0)
