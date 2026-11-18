import asyncio
import datetime
import json
import re
from typing import Any, Callable, Dict, List, Optional
import numpy as np
from PIL import Image


class AICodingSupervisor:
    """
    AI 寫程式自動監督閉環 + 智慧熔斷引擎：
    1. 背景監控目標 IDE / CLI 視窗（如 Antigravity / Cursor / VS Code / OpenCode），透過像素穩定度與 VLM 判斷被監督的 AI 是否已回覆完畢。
    2. 自動在背景執行語法檢查、測試指令 (`verify_command`) 或畫面檢查，絕不干擾使用者打遊戲、看影片或寫功課。
    3. 發現錯誤時，自動整理精準的錯誤報告與修改指示回填給該 AI 繼續修。
    4. 智慧熔斷機制：若連續卡關達 3 次（可調）仍未修好、方向偏離、或全部測試通過時，自動暫停並透過 Discord 與 Gemini 介面通知使用者決定下一步。
    """

    def __init__(self, settings_manager, context_guard, desktop_controller, agent_brain):
        self.settings_manager = settings_manager
        self.context_guard = context_guard
        self.desktop = desktop_controller
        self.brain = agent_brain

        self.active_session: Optional[Dict[str, Any]] = None
        self._task: Optional[asyncio.Task] = None
        self._event_callbacks: List[Callable] = []
        self.logs: List[Dict[str, Any]] = []

    def register_callback(self, cb: Callable):
        self._event_callbacks.append(cb)

    def _emit(self, event_type: str, message: str, extra: Optional[Dict[str, Any]] = None):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "event": event_type,
            "message": message,
            **(extra or {}),
        }
        self.logs.insert(0, entry)
        if len(self.logs) > 100:
            self.logs = self.logs[:100]
        self.settings_manager.append_audit_log("SUPERVISOR_EVENT", entry)

        for cb in self._event_callbacks:
            try:
                res = cb(entry)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "active": bool(self.active_session and self.active_session.get("status") == "RUNNING"),
            "session": self.active_session,
            "recent_logs": self.logs[:25],
        }

    def start_supervision(
        self,
        hwnd: int,
        window_title: str,
        goal: str,
        workspace_dir: str = "",
        verify_command: str = "",
        input_coords: Optional[List[int]] = None,
        max_failures: int = 3,
    ) -> Dict[str, Any]:
        if self._task and not self._task.done():
            self._task.cancel()

        self.active_session = {
            "hwnd": hwnd,
            "window_title": window_title,
            "goal": goal,
            "workspace_dir": workspace_dir,
            "verify_command": verify_command,
            "input_coords": tuple(input_coords) if input_coords and len(input_coords) == 2 else None,
            "max_failures": max_failures,
            "consecutive_failures": 0,
            "rounds_completed": 0,
            "status": "RUNNING",
            "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "last_check_at": None,
        }

        self._emit(
            "SUPERVISION_STARTED",
            f"🔭 開始監督視窗「{window_title}」(HWND={hwnd}) | 目標：{goal}",
            {"session": self.active_session},
        )
        self._task = asyncio.create_task(self._supervision_loop())
        return self.get_status()

    def stop_supervision(self, reason: str = "使用者手動停止監督") -> Dict[str, Any]:
        if self._task and not self._task.done():
            self._task.cancel()
        if self.active_session:
            self.active_session["status"] = "STOPPED"
            self.active_session["stop_reason"] = reason
        self._emit("SUPERVISION_STOPPED", f"⏹️ 已停止 AI 監督：{reason}")
        return self.get_status()

    def resume_after_circuit_break(self) -> Dict[str, Any]:
        """當觸發 3 次熔斷後，使用者在 Discord 或 Gemini 介面點擊「繼續重試」時重置計數並恢復"""
        if not self.active_session:
            return {"ok": False, "error": "目前沒有監督工作階段"}
        self.active_session["consecutive_failures"] = 0
        self.active_session["status"] = "RUNNING"
        self._emit("SUPERVISION_RESUMED", "▶️ 使用者已重置熔斷計數並恢復自動監督閉環！")
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._supervision_loop())
        return self.get_status()

    @staticmethod
    def _images_are_stable(img1: Image.Image, img2: Image.Image, threshold: float = 1.8) -> bool:
        """比較兩張背景截圖的平均像素差異，判斷 IDE 畫面是否已停止滾動/生成完畢"""
        try:
            a1 = np.asarray(img1.resize((320, 180)).convert("L"), dtype=np.float32)
            a2 = np.asarray(img2.resize((320, 180)).convert("L"), dtype=np.float32)
            diff = float(np.mean(np.abs(a1 - a2)))
            return diff < threshold
        except Exception:
            return True

    async def _supervision_loop(self):
        cfg = self.settings_manager.get_raw().get("supervisor", {})
        poll_interval = max(4.0, float(cfg.get("poll_interval_seconds", 6.0)))

        prev_img: Optional[Image.Image] = None
        last_action_hash: str = ""

        try:
            while self.active_session and self.active_session.get("status") == "RUNNING":
                await asyncio.sleep(poll_interval)
                sess = self.active_session
                if not sess or sess.get("status") != "RUNNING":
                    break

                hwnd = sess["hwnd"]
                img1, meta = self.desktop.capture_window_background(hwnd, draw_grid=False)
                if not img1:
                    self._emit("SUPERVISION_WARNING", f"⚠️ 無法擷取目標視窗 (HWND={hwnd})，可能已關閉。")
                    sess["status"] = "PAUSED"
                    break

                # 等待 3 秒再抓一張，確認畫面已穩定（代表被監督的 AI 不在串流打字中）
                await asyncio.sleep(3.0)
                img2, _ = self.desktop.capture_window_background(hwnd, draw_grid=False)
                if not img2 or not self._images_are_stable(img1, img2):
                    # AI 仍在生成文字或畫面變動中，繼續等待
                    prev_img = img2
                    continue

                # 若畫面與上一輪已處理過的完全相同，代表對方還沒產生新變化，不重複消耗 Token
                if prev_img is not None and self._images_are_stable(prev_img, img2, threshold=0.6):
                    continue
                prev_img = img2

                sess["last_check_at"] = datetime.datetime.now().isoformat(timespec="seconds")

                # 1. 若有設定背景驗證指令 (例如 pytest / npm test / git status)，先在背景跑測試
                verify_cmd = (sess.get("verify_command") or "").strip()
                test_report = "（未設定自動測試指令，以視覺與程式碼檢查為主）"
                test_passed: Optional[bool] = None
                if verify_cmd:
                    cmd_res = await self.desktop.run_background_command(
                        command=verify_cmd,
                        cwd=sess.get("workspace_dir") or None,
                        timeout=60.0,
                    )
                    test_passed = cmd_res.get("ok", False)
                    test_report = f"指令 `{verify_cmd}` (ExitCode={cmd_res.get('exit_code')}):\n{cmd_res.get('output', '')[:2000]}"

                # 2. 呼叫 VLM 分析目前 IDE 視窗畫面 + 背景測試結果
                b64 = self.desktop.image_to_base64(img2)
                eval_prompt = f"""你正在監督另一個 AI 寫程式。
【監督目標】：{sess['goal']}
【目標視窗】：{sess['window_title']}
【背景驗證指令結果】：
{test_report}

請根據視窗截圖與背景驗證結果，判斷目前狀態並僅輸出以下 JSON 格式（放在 ```json 區塊內）：
```json
{{
  "ai_state": "GENERATING" | "IDLE_FINISHED" | "WAITING_CONFIRMATION",
  "goal_achieved": true | false,
  "has_error_or_issue": true | false,
  "summary": "一句話總結目前被監督 AI 的回覆與問題狀態",
  "feedback_to_ai": "若還沒完成或有錯，請寫出要直接貼給該 AI 的具體繁體中文修正指令（包含錯誤訊息與修改方向）；若已完成則填空字串"
}}
```"""
                llm_res = await self.brain.call_llm(
                    messages=[
                        {"role": "system", "content": "你是嚴格的資深程式碼審查與 AI 監督專家。只回傳要求的 JSON。"},
                        {"role": "user", "content": eval_prompt},
                    ],
                    image_b64=b64,
                )

                if not llm_res.get("ok"):
                    self._emit("SUPERVISION_ERROR", f"呼叫模型分析監督畫面失敗：{llm_res.get('error')}")
                    continue

                raw_reply = llm_res.get("content", "")
                parsed = self._parse_json_block(raw_reply)
                if not parsed:
                    continue

                if parsed.get("ai_state") == "GENERATING":
                    continue

                sess["rounds_completed"] += 1
                summary = parsed.get("summary", "完成一輪檢查")
                goal_achieved = bool(parsed.get("goal_achieved")) and (test_passed is not False)
                has_issue = bool(parsed.get("has_error_or_issue")) or (test_passed is False)
                feedback_to_ai = (parsed.get("feedback_to_ai") or "").strip()

                if goal_achieved and not has_issue:
                    sess["status"] = "COMPLETED"
                    sess["consecutive_failures"] = 0
                    self._emit(
                        "SUPERVISION_COMPLETED",
                        f"✅ **AI 寫程式監督任務達成！**\n視窗：{sess['window_title']}\n結論：{summary}",
                        {"screenshot_b64": b64, "session": sess},
                    )
                    break

                if has_issue or feedback_to_ai:
                    sess["consecutive_failures"] += 1
                    fail_count = sess["consecutive_failures"]
                    max_fail = int(sess.get("max_failures", 3))

                    # 檢查是否觸發 3 次智慧熔斷
                    if fail_count >= max_fail:
                        sess["status"] = "CIRCUIT_BROKEN"
                        self._emit(
                            "SUPERVISION_CIRCUIT_BREAK",
                            (
                                f"⚠️ **觸發智慧熔斷機制（連續 {fail_count} 次未解決問題）！**\n"
                                f"視窗：{sess['window_title']}\n"
                                f"目前問題：{summary}\n"
                                f"建議回覆指令：`{feedback_to_ai[:250]}`\n"
                                f"已暫停自動重試，請在 Discord 或 Gemini 介面決定是否繼續重試或手動接手。"
                            ),
                            {"screenshot_b64": b64, "session": sess, "feedback_to_ai": feedback_to_ai},
                        )
                        break

                    # 自動將修正建議回填給被監督的 AI 視窗（受 ContextGuard 遊戲/觀影/寫功課免打擾保護）
                    if feedback_to_ai and feedback_to_ai != last_action_hash:
                        last_action_hash = feedback_to_ai
                        send_res = await self.desktop.send_feedback_to_ide_window(
                            hwnd=hwnd,
                            feedback_text=feedback_to_ai,
                            input_coords=sess.get("input_coords"),
                            press_enter=True,
                        )
                        if send_res.get("ok"):
                            self._emit(
                                "SUPERVISION_FEEDBACK_SENT",
                                (
                                    f"🔄 **第 {fail_count}/{max_fail} 次自動回報修正指令給 AI**\n"
                                    f"檢查摘要：{summary}\n"
                                    f"已送出指令：`{feedback_to_ai[:180]}`"
                                ),
                                {"screenshot_b64": b64},
                            )
                            # 送出後等待對方開始生成
                            await asyncio.sleep(6.0)
                        elif send_res.get("deferred_by_dnd"):
                            self._emit(
                                "SUPERVISION_DEFERRED_DND",
                                (
                                    f"🔕 **已檢查出問題，但偵測到你正在遊戲/看影片/操作電腦，暫緩搶畫面貼上**\n"
                                    f"檢查摘要：{summary}\n"
                                    f"擬回報給 AI 的指令：`{feedback_to_ai[:200]}`"
                                ),
                                {"screenshot_b64": b64, "pending_feedback": feedback_to_ai},
                            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._emit("SUPERVISION_EXCEPTION", f"監督循環發生例外：{e}")

    @staticmethod
    def _parse_json_block(text: str) -> Optional[Dict[str, Any]]:
        import re

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        raw = m.group(1) if m else text.strip()
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
