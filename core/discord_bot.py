import asyncio
import base64
import json
from typing import Any, Callable, Dict, Optional
import httpx
import websockets


class DiscordBotBridge:
    """
    雙向 Discord Bot 遠端互動與通知中心 (原生支援 Discord Gateway v10 WebSocket + REST API + Webhook)：
    1. 即時推播：上網透明通報、AI 寫程式監督進度/熔斷警報、高風險與交易攔截工單（附帶遮罩後截圖）。
    2. 雙向互動按鈕與指令：
       - 直接在手機/電腦 Discord 點擊按鈕「✅ 批准放行」、「🛑 拒絕攔截」、「▶️ 恢復監督重試」。
       - 涉及金流交易時，可在 Discord 輸入 `!pin <工單ID> <安全PIN碼>` 完成二次驗證放行。
       - 在打遊戲或離開座位時，直接在 Discord 頻道打字下達新任務給 Agent！
    """

    DISCORD_API_BASE = "https://discord.com/api/v10"
    GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

    def __init__(self, settings_manager, security_guard, supervisor, agent_brain):
        self.settings_manager = settings_manager
        self.security_guard = security_guard
        self.supervisor = supervisor
        self.agent_brain = agent_brain

        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._bot_user_id: Optional[str] = None
        self._ui_broadcast_cb: Optional[Callable] = None

    def set_ui_broadcast_callback(self, cb: Callable):
        self._ui_broadcast_cb = cb

    def start(self):
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self._running = True
        self._ws_task = asyncio.create_task(self._gateway_loop())

    def stop(self):
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()

    def _get_cfg(self) -> Dict[str, Any]:
        return self.settings_manager.get_raw().get("discord", {})

    async def send_notification(
        self,
        content: str,
        embed: Optional[Dict[str, Any]] = None,
        components: Optional[list] = None,
        screenshot_b64: Optional[str] = None,
    ) -> bool:
        cfg = self._get_cfg()
        if not cfg.get("enabled", False):
            return False

        # ▼ 嚴密資安過濾：所有推播至 Discord 的訊息均強制進行金鑰脫敏
        content = self.security_guard.sanitize_secrets(content)
        if embed:
            if "description" in embed and isinstance(embed["description"], str):
                embed["description"] = self.security_guard.sanitize_secrets(embed["description"])
            if "title" in embed and isinstance(embed["title"], str):
                embed["title"] = self.security_guard.sanitize_secrets(embed["title"])
            for f in embed.get("fields", []):
                if "value" in f and isinstance(f["value"], str):
                    f["value"] = self.security_guard.sanitize_secrets(f["value"])

        bot_token = (cfg.get("bot_token") or "").strip()
        channel_id = (cfg.get("channel_id") or "").strip()
        webhook_url = (cfg.get("webhook_url") or "").strip()

        # 1. 優先使用雙向 Bot Token 發送至指定 Channel (支援互動按鈕 Components)
        if bot_token and channel_id:
            url = f"{self.DISCORD_API_BASE}/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {bot_token}"}
            payload: Dict[str, Any] = {"content": content[:1900]}
            if embed:
                payload["embeds"] = [embed]
            if components:
                payload["components"] = components

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    if screenshot_b64:
                        img_bytes = base64.b64decode(screenshot_b64)
                        files = {"files[0]": ("screenshot.jpg", img_bytes, "image/jpeg")}
                        data = {"payload_json": json.dumps(payload, ensure_ascii=False)}
                        resp = await client.post(url, headers=headers, data=data, files=files)
                    else:
                        headers["Content-Type"] = "application/json"
                        resp = await client.post(url, headers=headers, json=payload)
                    return resp.status_code < 300
            except Exception:
                return False

        # 2. 備援：若僅設定 Webhook URL
        if webhook_url:
            payload = {"content": content[:1900]}
            if embed:
                payload["embeds"] = [embed]
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(webhook_url, json=payload)
                    return resp.status_code < 300
            except Exception:
                return False

        return False

    async def notify_security_ticket(self, ticket: Dict[str, Any]):
        cfg = self._get_cfg()
        if not cfg.get("notify_on_security", True):
            return

        tid = ticket["id"]
        is_tx = ticket.get("requires_pin", False)
        color = 0xEF4444 if is_tx else 0xF59E0B
        badge = "🚨 【金流/交易攔截】需 PIN 碼二次確認" if is_tx else "🛡️ 【高風險操作攔截】待批准"

        embed = {
            "title": f"{badge} ({tid})",
            "description": (
                f"**操作項目**：{ticket['title']}\n"
                f"**攔截原因**：{ticket['reason']}\n\n"
                + (
                    f"🔐 **放行方式**：請在 Discord 直接輸入：\n`!pin {tid} 你的PIN碼`\n或點擊下方拒絕按鈕攔截。"
                    if is_tx
                    else "請直接點擊下方按鈕 **批准** 或 **拒絕**，或輸入 `!approve " + tid + "`"
                )
            ),
            "color": color,
        }

        buttons = []
        if not is_tx:
            buttons.append({
                "type": 2,
                "style": 3,  # Success Green
                "label": "✅ 批准執行",
                "custom_id": f"sec_approve:{tid}",
            })
        buttons.append({
            "type": 2,
            "style": 4,  # Danger Red
            "label": "🛑 拒絕並攔截",
            "custom_id": f"sec_reject:{tid}",
        })
        components = [{"type": 1, "components": buttons}]

        await self.send_notification(
            content=f"⚠️ **資安防護閘門觸發** (`{tid}`)",
            embed=embed,
            components=components,
            screenshot_b64=ticket.get("screenshot_b64"),
        )

    async def notify_web_activity(self, record: Dict[str, Any]):
        cfg = self._get_cfg()
        if not cfg.get("notify_on_web", True):
            return
        embed = {
            "title": f"🌐 上網內容透明回報：{record.get('title', '')[:80]}",
            "url": record.get("url", ""),
            "description": (
                f"**連線目的**：{record.get('purpose', '')}\n"
                f"**網址**：{record.get('url', '')}\n"
                f"**內容重點摘要**：\n{record.get('summary', '')[:600]}"
            ),
            "color": 0x38BDF8,
        }
        await self.send_notification(content="", embed=embed)

    async def notify_supervisor_event(self, entry: Dict[str, Any]):
        cfg = self._get_cfg()
        if not cfg.get("notify_on_supervision", True):
            return
        ev = entry.get("event", "")
        if ev not in (
            "SUPERVISION_COMPLETED",
            "SUPERVISION_CIRCUIT_BREAK",
            "SUPERVISION_FEEDBACK_SENT",
            "SUPERVISION_DEFERRED_DND",
        ):
            return

        color = 0x22C55E if ev == "SUPERVISION_COMPLETED" else (0xEF4444 if ev == "SUPERVISION_CIRCUIT_BREAK" else 0x818CF8)
        components = None
        if ev == "SUPERVISION_CIRCUIT_BREAK":
            components = [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "style": 1,
                            "label": "▶️ 重置熔斷並繼續重試 3 次",
                            "custom_id": "sup_resume",
                        },
                        {
                            "type": 2,
                            "style": 4,
                            "label": "⏹️ 停止監督",
                            "custom_id": "sup_stop",
                        },
                    ],
                }
            ]

        embed = {
            "title": f"🔭 AI 寫程式監督回報 ({ev})",
            "description": entry.get("message", ""),
            "color": color,
        }
        await self.send_notification(
            content="",
            embed=embed,
            components=components,
            screenshot_b64=entry.get("screenshot_b64"),
        )

    async def _gateway_loop(self):
        """原生 Discord Gateway v10 WebSocket 常駐連線：接收手機/遠端指令與按鈕互動"""
        while self._running:
            cfg = self._get_cfg()
            bot_token = (cfg.get("bot_token") or "").strip()
            target_channel = (cfg.get("channel_id") or "").strip()

            if not cfg.get("enabled") or not bot_token:
                await asyncio.sleep(5.0)
                continue

            try:
                async with websockets.connect(self.GATEWAY_URL, max_size=16 * 1024 * 1024) as ws:
                    hello_raw = await ws.recv()
                    hello = json.loads(hello_raw)
                    heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000.0

                    # Identify (Intents: GUILDS=1 | GUILD_MESSAGES=512 | DIRECT_MESSAGES=4096 | MESSAGE_CONTENT=32768 -> 37377)
                    identify_payload = {
                        "op": 2,
                        "d": {
                            "token": bot_token,
                            "intents": 37377,
                            "properties": {"os": "windows", "browser": "gemini_desktop_agent", "device": "gemini_desktop_agent"},
                        },
                    }
                    await ws.send(json.dumps(identify_payload))

                    async def _heartbeat():
                        while self._running:
                            await asyncio.sleep(heartbeat_interval)
                            try:
                                await ws.send(json.dumps({"op": 1, "d": None}))
                            except Exception:
                                break

                    hb_task = asyncio.create_task(_heartbeat())
                    try:
                        async for raw_msg in ws:
                            packet = json.loads(raw_msg)
                            op = packet.get("op")
                            t = packet.get("t")
                            d = packet.get("d") or {}

                            if op == 11:
                                continue
                            if t == "READY":
                                user_obj = d.get("user") or {}
                                self._bot_user_id = user_obj.get("id")
                            elif t == "INTERACTION_CREATE":
                                asyncio.create_task(self._handle_interaction(d, bot_token))
                            elif t == "MESSAGE_CREATE":
                                asyncio.create_task(self._handle_message(d, target_channel))
                    finally:
                        hb_task.cancel()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(8.0)

    async def _handle_interaction(self, d: Dict[str, Any], bot_token: str):
        """處理使用者在 Discord 點擊互動按鈕 (批准/拒絕/恢復監督)"""
        cfg = self._get_cfg()
        user_info = d.get("user") or d.get("member", {}).get("user") or {}
        author_id = str(user_info.get("id", ""))
        allowed_users = cfg.get("allowed_user_ids") or []
        if isinstance(allowed_users, str):
            allowed_users = [u.strip() for u in allowed_users.split(",") if u.strip()]

        interaction_id = d.get("id")
        interaction_token = d.get("token")

        if allowed_users and author_id not in allowed_users:
            cb_url = f"{self.DISCORD_API_BASE}/interactions/{interaction_id}/{interaction_token}/callback"
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        cb_url,
                        json={"type": 4, "data": {"content": f"⛔ 存取拒絕：你的 Discord 帳號 (ID: {author_id}) 未在授權白名單內！"}},
                    )
            except Exception:
                pass
            return

        data = d.get("data") or {}
        custom_id = data.get("custom_id", "")

        reply_text = "已收到操作。"
        if custom_id.startswith("sec_approve:"):
            tid = custom_id.split(":", 1)[1]
            _, msg = self.security_guard.resolve_approval(tid, approved=True, source="Discord Button")
            reply_text = msg
        elif custom_id.startswith("sec_reject:"):
            tid = custom_id.split(":", 1)[1]
            _, msg = self.security_guard.resolve_approval(tid, approved=False, source="Discord Button")
            reply_text = msg
        elif custom_id == "sup_resume":
            self.supervisor.resume_after_circuit_break()
            reply_text = "▶️ 已從 Discord 重置智慧熔斷計數，繼續自動監督 AI 寫程式！"
        elif custom_id == "sup_stop":
            self.supervisor.stop_supervision("由 Discord 按鈕停止監督")
            reply_text = "⏹️ 已從 Discord 停止 AI 監督循環。"

        # 回應 Discord Interaction Callback
        cb_url = f"{self.DISCORD_API_BASE}/interactions/{interaction_id}/{interaction_token}/callback"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    cb_url,
                    json={"type": 4, "data": {"content": reply_text}},
                )
        except Exception:
            pass

        if self._ui_broadcast_cb:
            await self._ui_broadcast_cb({"type": "DISCORD_ACTION", "message": reply_text})

    async def _handle_message(self, d: Dict[str, Any], target_channel: str):
        """處理使用者在 Discord 頻道輸入的文字指令或遠端對話"""
        author = d.get("author") or {}
        if author.get("bot") or (self._bot_user_id and author.get("id") == self._bot_user_id):
            return

        ch_id = str(d.get("channel_id", ""))
        if target_channel and ch_id != target_channel:
            return

        cfg = self._get_cfg()
        author_id = str(author.get("id", ""))
        allowed_users = cfg.get("allowed_user_ids") or []
        if isinstance(allowed_users, str):
            allowed_users = [u.strip() for u in allowed_users.split(",") if u.strip()]

        if allowed_users and author_id not in allowed_users:
            await self.send_notification(
                f"⛔ **【遠端操控存取拒絕】** 來自 Discord 使用者 `{author.get('username')}` (ID: `{author_id}`) 的指令已被阻斷。\n"
                f"該帳號未在系統授權白名單內，嚴禁外部未授權人員遠端操控本機！"
            )
            return

        content = (d.get("content") or "").strip()
        if not content:
            return

        # 1. 支援 `!pin <ticket_id> <PIN碼>` 放行交易
        if content.lower().startswith("!pin "):
            parts = content.split()
            if len(parts) >= 3:
                tid, pin = parts[1], parts[2]
                _, msg = self.security_guard.resolve_approval(tid, approved=True, pin_code=pin, source="Discord PIN")
                await self.send_notification(msg)
                if self._ui_broadcast_cb:
                    await self._ui_broadcast_cb({"type": "SECURITY_RESOLVED", "ticket_id": tid, "message": msg})
            else:
                await self.send_notification("用法：`!pin <工單ID> <安全PIN碼>`")
            return

        # 2. 支援 `!approve <ticket_id>` 與 `!reject <ticket_id>`
        if content.lower().startswith("!approve "):
            tid = content.split(maxsplit=1)[1].strip()
            _, msg = self.security_guard.resolve_approval(tid, approved=True, source="Discord Command")
            await self.send_notification(msg)
            return

        if content.lower().startswith("!reject "):
            tid = content.split(maxsplit=1)[1].strip()
            _, msg = self.security_guard.resolve_approval(tid, approved=False, source="Discord Command")
            await self.send_notification(msg)
            return

        # 3. 支援 `!stop` 緊急剎車
        if content.lower() in ("!stop", "!kill"):
            self.security_guard.emergency_stop_triggered = True
            self.supervisor.stop_supervision("Discord !stop 緊急停止")
            await self.send_notification("🛑 已執行緊急停止 (Kill Switch)，所有桌面操作與監督已暫停！")
            return

        # 4. 一般遠端任務指令：直接交給 AgentBrain 執行並將結果回傳 Discord + 同步至桌面 Gemini UI
        if self._ui_broadcast_cb:
            await self._ui_broadcast_cb({
                "type": "DISCORD_USER_MSG",
                "user": author.get("username", "DiscordUser"),
                "content": content,
            })

        await self.send_notification(f"🤖 收到你的遠端指令，正在背景處理：`{content[:80]}`...")
        res = await self.agent_brain.run_chat_turn(
            session_id="discord_remote",
            user_message=f"[來自使用者 Discord 遠端指令]: {content}",
        )
        reply = res.get("reply", "已完成處理。")
        await self.send_notification(
            content=f"💬 **Agent 回覆**：\n{reply[:1800]}",
            screenshot_b64=res.get("screenshot_b64"),
        )
        if self._ui_broadcast_cb:
            await self._ui_broadcast_cb({
                "type": "DISCORD_AGENT_REPLY",
                "reply": reply,
                "model_used": res.get("model_used", ""),
            })
