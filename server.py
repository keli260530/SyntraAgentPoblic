import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import urllib.parse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.agent_brain import AgentBrain
from core.api_manager import ApiManager
from core.context_guard import ContextGuard
from core.desktop_controller import DesktopController
from core.discord_bot import DiscordBotBridge
from core.security_guard import SecurityGuard
from core.settings_manager import SettingsManager
from core.supervisor import AICodingSupervisor
from core.web_auditor import WebAuditor
from scripts.setup_startup_and_shortcut import configure_windows_autostart


BASE_DIR = Path(__file__).resolve().parent
UI_HTML_PATH = BASE_DIR / "ui" / "index.html"

settings_manager = SettingsManager()
api_manager = ApiManager()

context_guard = ContextGuard(settings_manager)
security_guard = SecurityGuard(settings_manager, api_manager=api_manager)
api_manager.set_security_guard(security_guard)
desktop_controller = DesktopController(context_guard, security_guard)
web_auditor = WebAuditor(settings_manager, security_guard)
agent_brain = AgentBrain(
    settings_manager=settings_manager,
    api_manager=api_manager,
    context_guard=context_guard,
    security_guard=security_guard,
    desktop_controller=desktop_controller,
    web_auditor=web_auditor,
)
supervisor = AICodingSupervisor(
    settings_manager=settings_manager,
    context_guard=context_guard,
    desktop_controller=desktop_controller,
    agent_brain=agent_brain,
)
discord_bridge = DiscordBotBridge(
    settings_manager=settings_manager,
    security_guard=security_guard,
    supervisor=supervisor,
    agent_brain=agent_brain,
)
agent_brain.set_discord_notifier(discord_bridge.send_notification)


class WSConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, payload: Dict[str, Any]):
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = WSConnectionManager()


# 綁定即時事件推播至 Gemini UI WebSocket 與 Discord Bot
async def _on_security_ticket(ticket: Dict[str, Any]):
    await ws_manager.broadcast({"type": "SECURITY_TICKET", "ticket": ticket})
    await discord_bridge.notify_security_ticket(ticket)


async def _on_web_activity(record: Dict[str, Any]):
    await ws_manager.broadcast({"type": "WEB_ACTIVITY", "record": record})
    await discord_bridge.notify_web_activity(record)


async def _on_supervisor_event(entry: Dict[str, Any]):
    await ws_manager.broadcast({"type": "SUPERVISOR_EVENT", "entry": entry})
    await discord_bridge.notify_supervisor_event(entry)


security_guard.register_approval_callback(_on_security_ticket)
web_auditor.register_callback(_on_web_activity)
supervisor.register_callback(_on_supervisor_event)
discord_bridge.set_ui_broadcast_callback(ws_manager.broadcast)

async def _on_api_provider_mutation(event_type: str, info: Dict[str, Any], source: str, message: str):
    await discord_bridge.send_notification(message)
    await ws_manager.broadcast({
        "type": "API_PROVIDER_MUTATION",
        "event_type": event_type,
        "info": info,
        "source": source,
        "message": message,
    })
    settings_manager.append_audit_log(f"API_PROVIDER_{event_type}", {
        "event_type": event_type,
        "provider_id": info.get("id"),
        "name": info.get("name"),
        "base_url": info.get("base_url"),
        "source": source,
        "changes": info.get("changes"),
    })

api_manager.register_change_callback(_on_api_provider_mutation)


def _setup_global_killswitch_hotkey():
    """註冊全域緊急剎車熱鍵 Ctrl+Alt+Q"""
    try:
        from pynput import keyboard

        def _on_kill():
            security_guard.emergency_stop_triggered = True
            supervisor.stop_supervision("使用者按下全域緊急停止熱鍵 Ctrl+Alt+Q")

        listener = keyboard.GlobalHotKeys({"<ctrl>+<alt>+q": _on_kill})
        listener.daemon = True
        listener.start()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_global_killswitch_hotkey()
    discord_bridge.start()

    async def _context_ticker():
        while True:
            await asyncio.sleep(3.0)
            if ws_manager.active:
                await ws_manager.broadcast({
                    "type": "CONTEXT_STATE",
                    "state": context_guard.evaluate_state(),
                    "emergency_stop": security_guard.emergency_stop_triggered,
                })

    ticker_task = asyncio.create_task(_context_ticker())
    try:
        yield
    finally:
        ticker_task.cancel()
        discord_bridge.stop()


app = FastAPI(title="Gemini Desktop Agent", lifespan=lifespan)

@app.middleware("http")
async def security_origin_check_middleware(request, call_next):
    # 防禦外部網站透過瀏覽器 Drive-By 操縱本地 127.0.0.1 服務 (Anti-Localhost Hijacking / Anti-CSRF)
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed_origin = urllib.parse.urlparse(origin)
            if parsed_origin.hostname not in ("localhost", "127.0.0.1"):
                return JSONResponse(
                    status_code=403,
                    content={"ok": False, "error": "❌ [資安阻斷] 偵測到未授權之外部跨來源請求 (Drive-By Attack Blocked)！禁止外部網站操縱本地 Agent。"}
                )
        except Exception:
            return JSONResponse(status_code=403, content={"ok": False, "error": "Invalid origin"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response

ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


class ChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: str = "default"
    message: str
    model_id: Optional[str] = None
    image_b64: Optional[str] = None


class SupervisorStartRequest(BaseModel):
    hwnd: int
    window_title: str
    goal: str
    workspace_dir: str = ""
    verify_command: str = ""
    input_coords: Optional[List[int]] = None
    max_failures: int = 3


class SecurityResolveRequest(BaseModel):
    ticket_id: str
    approved: bool
    pin_code: Optional[str] = None


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "syntra-local-agent"}


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    if UI_HTML_PATH.exists():
        return HTMLResponse(UI_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>UI file missing</h1>", status_code=404)


@app.get("/api/status")
async def get_status():
    return {
        "models_catalog": api_manager.get_models_catalog(),
        "providers": api_manager.get_providers(mask_keys=True),
        "context": context_guard.evaluate_state(),
        "supervisor": supervisor.get_status(),
        "pending_approvals": list(security_guard.pending_approvals.values()),
        "web_history": web_auditor.history[:30],
        "settings": settings_manager.get_all(mask_secrets=True),
        "emergency_stop": security_guard.emergency_stop_triggered,
    }


@app.get("/api/providers")
async def get_providers_api():
    return {
        "providers": api_manager.get_providers(mask_keys=True),
        "models_catalog": api_manager.get_models_catalog(),
    }


@app.post("/api/providers/upsert")
async def upsert_provider_api(payload: Dict[str, Any]):
    try:
        saved = api_manager.upsert_provider(payload, source="Web 管理介面")
        return {
            "ok": True,
            "saved": saved,
            "providers": api_manager.get_providers(mask_keys=True),
            "models_catalog": api_manager.get_models_catalog(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/providers/delete")
async def delete_provider_api(payload: Dict[str, Any]):
    pid = str(payload.get("id", ""))
    ok = api_manager.delete_provider(pid, source="Web 管理介面")
    return {
        "ok": ok,
        "providers": api_manager.get_providers(mask_keys=True),
        "models_catalog": api_manager.get_models_catalog(),
    }


@app.post("/api/providers/test")
async def test_provider_api(payload: Dict[str, Any]):
    pid = str(payload.get("id", ""))
    res = await api_manager.test_connection(pid)
    return res


@app.get("/api/windows")
async def get_windows():
    return {"windows": desktop_controller.list_open_windows()}


@app.post("/api/window/preview")
async def preview_window(payload: Dict[str, Any]):
    hwnd = int(payload.get("hwnd", 0))
    img, meta = desktop_controller.capture_window_background(hwnd, draw_grid=bool(payload.get("grid", False)))
    if not img:
        return JSONResponse({"ok": False, **meta}, status_code=400)
    b64 = desktop_controller.image_to_base64(img)
    return {"ok": True, "image_b64": b64, "meta": meta}


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    async def _step_cb(step_info: Dict[str, Any]):
        await ws_manager.broadcast({"type": "TOOL_STEP", "step": step_info})

    result = await agent_brain.run_chat_turn(
        session_id=req.session_id,
        user_message=req.message,
        model_full_id=req.model_id,
        attached_image_b64=req.image_b64,
        step_callback=_step_cb,
    )
    return result


@app.post("/api/supervisor/start")
async def start_supervisor_api(req: SupervisorStartRequest):
    status = supervisor.start_supervision(
        hwnd=req.hwnd,
        window_title=req.window_title,
        goal=req.goal,
        workspace_dir=req.workspace_dir,
        verify_command=req.verify_command,
        input_coords=req.input_coords,
        max_failures=req.max_failures,
    )
    return {"ok": True, "supervisor": status}


@app.post("/api/supervisor/stop")
async def stop_supervisor_api():
    status = supervisor.stop_supervision("使用者於 Gemini 介面手動停止")
    return {"ok": True, "supervisor": status}


@app.post("/api/supervisor/resume")
async def resume_supervisor_api():
    status = supervisor.resume_after_circuit_break()
    return {"ok": True, "supervisor": status}


@app.post("/api/security/resolve")
async def resolve_security_api(req: SecurityResolveRequest):
    ok, msg = security_guard.resolve_approval(
        ticket_id=req.ticket_id,
        approved=req.approved,
        pin_code=req.pin_code,
        source="Gemini UI",
    )
    await ws_manager.broadcast({
        "type": "SECURITY_RESOLVED",
        "ticket_id": req.ticket_id,
        "ok": ok,
        "message": msg,
    })
    return {"ok": ok, "message": msg}


@app.post("/api/security/killswitch")
async def toggle_killswitch(payload: Dict[str, Any]):
    reset = bool(payload.get("reset", False))
    if reset:
        security_guard.emergency_stop_triggered = False
        return {"ok": True, "emergency_stop": False, "message": "✅ 已解除緊急停止鎖定，恢復正常運作。"}
    else:
        security_guard.emergency_stop_triggered = True
        supervisor.stop_supervision("手動觸發緊急停止開關")
        return {"ok": True, "emergency_stop": True, "message": "🛑 已啟動緊急停止開關，所有自動操作已立即凍結！"}


@app.get("/api/settings")
async def get_settings_api():
    return {
        "settings": settings_manager.get_all(mask_secrets=True),
        "providers": api_manager.get_providers(mask_keys=True),
        "models_catalog": api_manager.get_models_catalog(),
    }


@app.post("/api/settings")
async def update_settings_api(payload: Dict[str, Any]):
    updated = settings_manager.update_settings(payload)
    if "autostart_enabled" in payload:
        configure_windows_autostart(bool(payload["autostart_enabled"]))

    return {
        "ok": True,
        "settings": updated,
        "providers": api_manager.get_providers(mask_keys=True),
        "models_catalog": api_manager.get_models_catalog(),
    }


@app.get("/api/google/status")
async def get_google_status():
    from core.google_workspace_suite import google_suite
    from core.habit_sync_engine import habit_sync_engine
    return {
        "is_authenticated": google_suite.is_authenticated(),
        "has_credentials": os.path.exists(google_suite.creds_path),
        "has_synced_habits": os.path.exists(habit_sync_engine.profile_path),
        "habit_context": habit_sync_engine.load_prompt_context(),
    }


@app.post("/api/google/sync-habits")
async def sync_google_habits():
    from core.habit_sync_engine import habit_sync_engine
    res = habit_sync_engine.sync_from_local_browser("chrome")
    return res


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    if origin:
        try:
            parsed = urllib.parse.urlparse(origin)
            if parsed.hostname not in ("localhost", "127.0.0.1"):
                await ws.close(code=1008, reason="Cross-site WebSocket Hijacking Blocked")
                return
        except Exception:
            await ws.close(code=1008, reason="Invalid origin")
            return

    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)
