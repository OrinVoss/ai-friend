import asyncio
import glob
import json
import logging
import os
import random
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import load_config
from web.session import SessionManager
from web.schemas import ChatRequest, ChatResponse, StatusResponse, HistoryResponse
from web.rate_limit import RateLimiter, RateLimitMiddleware

logger = logging.getLogger(__name__)

config = load_config()
session_manager = SessionManager(config)
rate_limiter = RateLimiter()
_ws_connections: list[dict] = []  # #158: track active WebSocket connections for rate limiting


def ensure_session():
    """Synchronous guard — call before first request if lifespan didn't run."""
    if session_manager.db is None:
        logger.warning("[server] lifespan missed, synchronously opening session manager")
        import asyncio
        asyncio.run(session_manager.open())


# WS-028: Content-Security-Policy — restrict fetch/script origins to block inline
# injection from any WebSocket-delivered content. Local dev allows self + localhost.
# script-src no longer allows 'unsafe-inline' since all JS lives in external files.
CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' ws://localhost:* http://localhost:* http://127.0.0.1:*; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "frame-ancestors 'none'"
)
# WS-027: X-Frame-Options DENY — defense-in-depth against clickjacking alongside CSP frame-ancestors
XFO_HEADER = "DENY"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Re-setup file logging — uvicorn resets root handlers on startup
        try:
            from core.logging_setup import setup_logging as _re_setup
            _re_setup(getattr(load_config(), 'log_level', 'INFO'))
        except Exception:
            pass
        logger.info("Server starting...")
        await session_manager.open()
        # #148: periodic session cleanup every 5 minutes
        async def _periodic_cleanup():
            while True:
                await asyncio.sleep(300)
                session_manager.cleanup_old()
        cleanup_task = asyncio.create_task(_periodic_cleanup())
        yield
        # #212: graceful shutdown — also evict stale sessions via cleanup_old
        logger.info("Server shutting down...")
        cleanup_task.cancel()
        session_manager.cleanup_old()
        await session_manager.shutdown()
    except Exception as e:
        logger.exception(f"Lifespan startup error: {e}")
        raise


# WS-003: CORS — localhost origins are always allowed; users may add extra origins
# via config.allowed_origins. WebSocket Origin validation lives in the endpoint.
_default_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
_allowed_origins = list(dict.fromkeys(_default_origins + getattr(config, 'allowed_origins', [])))

# WS-003: WebSocket Origin 白名单 —— localhost/127.0.0.1 始终放行；其余来源通过
# config.allowed_origins 扩展（按 hostname 匹配，忽略 scheme/port，便于内网穿透域名）。
from urllib.parse import urlparse as _urlparse
_ws_allowed_hosts = {"localhost", "127.0.0.1"}
for _o in getattr(config, 'allowed_origins', []):
    _h = _urlparse(_o).hostname or _o
    if _h:
        _ws_allowed_hosts.add(_h)

app = FastAPI(
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=_allowed_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        ),
        Middleware(RateLimitMiddleware, limiter=rate_limiter),
    ],
)


@app.middleware("http")
async def _add_security_headers(request: Request, call_next):
    """Add CSP + X-Frame-Options + no-sniff on every response. (#WS-027/#WS-028)"""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP_HEADER
    response.headers["X-Frame-Options"] = XFO_HEADER
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


app.mount("/static", StaticFiles(directory="web/static"), name="static")


@app.get("/")
async def index():
    ensure_session()
    from fastapi.responses import FileResponse
    return FileResponse("web/static/index.html")


# WS-029: silence favicon 404s without weakening CSP
@app.get("/favicon.ico")
@app.head("/favicon.ico")
async def favicon():
    """Silence 404s for browsers requesting a favicon."""
    return Response(status_code=204)


@app.post("/api/chat", response_model=ChatResponse)
async def chat_api(req: ChatRequest):
    ensure_session()
    logger.info(f"[rest] chat session={req.session_id} len={len(req.message)}")
    _, agent = session_manager.get_or_create(req.session_id)
    response = agent.process_message(req.message)
    logger.info(f"[rest] chat_done session={req.session_id} turn={agent.turn_count} emotion={agent.emotion} resp_len={len(response)}")
    return ChatResponse(
        response=response,
        emotion=agent.emotion,
        turn=agent.turn_count,
        session_id=req.session_id,
    )


@app.get("/api/status", response_model=StatusResponse)
async def status_api(session_id: str = "default"):
    """Return relationship metrics + history (#132)."""
    logger.info(f"[rest] status session={session_id}")
    _, agent = session_manager.get_or_create(session_id)
    raw_rel = agent.agent.ltm.get_relationship()
    raw_history = agent.agent.ltm.get_relationship_history(days=7)

    # Normalize dimensions for UI: trust/familiarity/intimacy/fun
    # The DB uses 'playfulness' for the fun dimension.
    def _normalize_rel(dims: dict) -> dict:
        rel = {}
        for k, v in dims.items():
            if k == "playfulness":
                rel["fun"] = v
            else:
                rel[k] = v
        return rel

    def _normalize_history(rows: list[dict]) -> list[dict]:
        # Group flat rows by timestamp and aggregate into one record per timestamp
        groups: dict[str, dict] = {}
        for row in rows:
            ts = row.get("created_at") or row.get("timestamp")
            dim = row.get("dimension", "")
            val = row.get("value")
            if not ts:
                continue
            # Convert UTC timestamps stored in SQLite to Beijing time (UTC+8)
            try:
                dt = datetime.fromisoformat(str(ts).replace(" ", "T"))
                dt = dt + timedelta(hours=8)
                ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
            if ts not in groups:
                groups[ts] = {"timestamp": ts}
            if dim == "playfulness":
                groups[ts]["fun"] = val
            else:
                groups[ts][dim] = val
        result = []
        for ts in sorted(groups.keys()):
            result.append(groups[ts])
        return result

    relationship = _normalize_rel(raw_rel)
    relationship_history = _normalize_history(raw_history)

    return StatusResponse(
        turn=agent.turn_count,
        emotion=agent.emotion,
        relationship=relationship,
        relationship_history=relationship_history,
    )


@app.get("/api/roles")
async def roles_api():
    """List available roles from personalities/*.json."""
    ensure_session()
    logger.info("[rest] roles")
    roles = []
    for path in sorted(glob.glob("personalities/*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            cfg = data.get("personality", data)
            role_id = data.get("id") or os.path.splitext(os.path.basename(path))[0]
            roles.append({"id": role_id, "name": cfg.get("name", role_id)})
        except Exception as e:
            logger.warning(f"[api/roles] failed to read {path}: {e}")
    return {"roles": roles}


@app.get("/api/sessions")
async def sessions_api(role_id: str):
    """Return session IDs previously created for a given role."""
    ensure_session()
    logger.info(f"[rest] sessions role={role_id}")
    sessions = await session_manager.repo.get_sessions_by_role(role_id)
    return {"role_id": role_id, "sessions": sessions}


@app.get("/api/chat/history", response_model=HistoryResponse)
async def chat_history_api(session_id: str = "default"):
    """Return recent conversation turns for UI display on reconnect."""
    logger.info(f"[rest] history session={session_id}")
    _, agent = session_manager.get_or_create(session_id)
    turns = []
    for t in agent.agent.short_term.get_all():
        turns.append({
            "role": t.role,
            "content": t.content,
        })
    return HistoryResponse(turns=turns, session_id=session_id)


@app.get("/api/logs")
async def logs_api(request: Request):
    """SSE stream of today's log file. (#console)"""
    from datetime import datetime

    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"{today}.log")

    async def event_stream():
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                # Send the last 100 lines on connect
                lines = f.readlines()
                for line in lines[-100:]:
                    yield f"data: {line.rstrip()}\n\n"
                # Tail the file for new lines
                while True:
                    if await request.is_disconnected():
                        break
                    line = f.readline()
                    if line:
                        yield f"data: {line.rstrip()}\n\n"
                    else:
                        await asyncio.sleep(0.5)
        else:
            yield "data: [no log file]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _calc_delay(emotion: str, seg_len: int) -> float:
    base = {
        "excited": 0.7, "joyful": 0.9, "trusting": 1.1, "surprised": 0.8,
        "engaged": 1.3, "content": 1.5, "anticipating": 0.9,
        "neutral": 1.7, "anxious": 1.0, "afraid": 1.3,
        "melancholy": 2.2, "sad": 2.5, "frustrated": 1.5, "angry": 1.0, "disgusted": 1.3,
    }.get(emotion, 1.7)
    return base * (1.0 + seg_len / 80) * random.uniform(0.8, 1.3)


# ── LLM API 调用监控 ──


@app.get("/api/monitor")
async def monitor_api(limit: int = 0):
    """Return recent LLM API call records as JSON. limit=0 for all."""
    from core.monitor import get_monitor
    return get_monitor().get_all(limit=limit)


@app.get("/api/monitor/clear")
async def monitor_clear():
    """Clear the monitor buffer."""
    from core.monitor import get_monitor
    get_monitor().clear()
    return {"status": "cleared"}


@app.get("/monitor")
async def monitor_page():
    """Serve the monitor HTML page."""
    return FileResponse("web/static/monitor.html")


def _split_segments(text: str) -> list[str]:
    # Step 1: split on sentence-ending punctuation (handles trailing quotes/brackets)
    parts = re.split(r'(?<=[。！？.!?\n])(?:[」"''）]?\s*)(?=\S)', text)
    segments = [s.strip() for s in parts if s.strip()]

    # Step 2: split long segments on commas / semicolons
    final = []
    for s in segments:
        if len(s) > 40:
            sub = re.split(r'(?<=[，,；;])\s*', s)
            final.extend(x.strip() for x in sub if x.strip())
        else:
            final.append(s)

    # Step 3: if still one big chunk, try whitespace split
    if len(final) == 1 and len(final[0]) > 10:
        sub = re.split(r'\s+', final[0])
        parts2 = [x.strip() for x in sub if x.strip()]
        if len(parts2) > 1:
            final = parts2

    # Step 4: if still one big chunk, try splitting after 语气词
    if len(final) == 1 and len(final[0]) > 10:
        sub = re.split(r'(?<=[啊吗呢了吧么呀哦嘛哇])', final[0])
        parts2 = [x.strip() for x in sub if x.strip()]
        if len(parts2) > 1:
            final = parts2

    # Step 5: last resort — split at natural pauses (连词 / 介词 / 时间词)
    if len(final) == 1 and len(final[0]) > 25:
        s = final[0]
        sub = re.split(r'(?<=[了过完好到])|(?<=然后|但是|不过|所以|因为|而且|或者|只是|于是|接着|还有|另外|虽然|如果|可以|应该)|(?<=\d[年月日号])', s)
        parts2 = [x.strip() for x in sub if x.strip()]
        if len(parts2) > 1:
            final = parts2
        else:
            # absolute fallback: hard-split every ~18 chars
            final = [s[i:i+18] for i in range(0, len(s), 18)]

    # Step 6: merge tiny trailing fragments (only very short ones)
    merged = []
    for s in final:
        if merged and len(s) < 4:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    return merged or [text]


async def _send_segments(websocket: WebSocket, agent, response: str, emotion: str):
    # TODO: re-enable segmentation when markdown streaming is stable
    await websocket.send_text(json.dumps({
        "type": "segment", "content": response,
    }, ensure_ascii=False))
    await websocket.send_text(json.dumps({
        "type": "done", "content": response,
        "emotion": emotion, "turn": agent.turn_count,
    }, ensure_ascii=False))


async def _proactive_loop(websocket: WebSocket, session_id: str):
    cooldown = 0
    sleep_cooldown = 0
    while True:
        try:
            # Use the most recently active WebSocket for this session
            active_ws = session_manager.get_active_ws(session_id) or websocket
            _, agent = session_manager.get_or_create(session_id)

            # Sleep/Wake cycle (only check if not in transition cooldown)
            if sleep_cooldown == 0:
                should_sleep, msg = await agent.get_sleep_state()
                if msg:
                    logger.info(f"Sleep/wake message: sleeping={agent.is_sleeping} msg={msg[:50]}")
                    agent.last_activity_time = time.time()
                    cooldown = 60
                    sleep_cooldown = 120  # 10 min cooldown on sleep transitions
                    await _send_segments(active_ws, agent, msg, agent.emotion)
                    # Store sleep/wake message in history so it survives page refresh
                    agent.add_turn("assistant", msg, metadata={"sleep": True})
                    agent.increment_turn_count()
                    if should_sleep:
                        await agent.generate_dream()
            else:
                sleep_cooldown = max(0, sleep_cooldown - 1)
            if agent.is_sleeping:
                await asyncio.sleep(30)
                continue

            idle = time.time() - agent.last_activity_time
            if idle < 30 or cooldown > 0:
                cooldown = max(0, cooldown - 1)
                await asyncio.sleep(5)
                continue

            score = agent.calculate_proactivity(idle)
            if random.random() < score:
                loop = asyncio.get_event_loop()

                # Agent 1 (InnerDrive) decides what to do
                intent = await loop.run_in_executor(
                    None, agent.decide_proactive_action, idle
                )

                if intent.action == "explore" and agent.check_rate_limit("explore"):
                    response = await loop.run_in_executor(
                        None, agent.process_explore_with_intent, intent
                    )
                elif intent.action == "chat" and agent.check_rate_limit("chat"):
                    response = await loop.run_in_executor(
                        None, agent.process_proactive_with_intent, intent
                    )
                else:
                    if intent.action == "silent":
                        logger.debug(f"[proactive] inner drive chose silent: {intent.reasoning[:80]}")
                    else:
                        logger.debug(f"[proactive] rate limit blocked action={intent.action}")
                    response = None
                if response:
                    agent.last_activity_time = time.time()
                    agent.record_rate_limit(intent.action)
                    cooldown = 12
                    await _send_segments(active_ws, agent, response, agent.emotion)
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Proactive error: {e}")
            await asyncio.sleep(30)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # #158: validate Origin header to prevent cross-origin WebSocket attacks
    origin = websocket.headers.get("origin", "")
    from urllib.parse import urlparse
    allowed = _ws_allowed_hosts  # localhost/127.0.0.1 + config.allowed_origins 的主机名
    if origin and origin != "null":
        parsed = urlparse(origin)
        if parsed.hostname not in allowed:
            logger.warning(f"[ws] rejected origin: {origin}")
            await websocket.close(code=4003)
            return

    # #158: connection limits — max 5 per IP, max 100 global
    client_ip = websocket.client.host if websocket.client else "unknown"
    conn_count = sum(1 for ws in _ws_connections if ws.get("ip") == client_ip)
    if conn_count >= 5:
        logger.warning(f"[ws] too many connections from {client_ip}")
        await websocket.close(code=4004)
        return
    if len(_ws_connections) >= 100:
        logger.warning("[ws] too many global connections")
        await websocket.close(code=4004)
        return

    await websocket.accept()
    _ws_connections.append({"ip": client_ip, "ws": websocket})
    logger.info(f"[ws] accepted: {client_ip}:{websocket.client.port} ({len(_ws_connections)} total)")
    session_id = None

    try:
        while True:
            # WS-021: cap incoming frames at 100KB at the protocol layer so an
            # oversized payload is rejected before json.loads ever runs. The
            # secondary len(raw) check below stays as belt-and-suspenders.
            raw = await websocket.receive_text()
            # #176: message size limit — 100KB
            if len(raw) > 102400:
                await websocket.send_text(json.dumps({"type": "error", "content": "消息过长（最大100KB）"}))
                continue
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "init":
                sid = data.get("session_id")
                role_id = data.get("role_id")
                session_id, agent = session_manager.get_or_create(sid, role_id)
                logger.info(f"[ws] init session={session_id} role={agent.role_id} sid_param={sid}")
                # Register proactive task per-session (replaces old task if exists)
                task = asyncio.create_task(_proactive_loop(websocket, session_id))
                session_manager.register_proactive(session_id, task, websocket)
                await websocket.send_text(json.dumps({
                    "type": "init_ok", "session_id": session_id,
                    "role_id": agent.role_id,
                    "emotion": agent.emotion,
                    "name": agent.personality.config.name,
                }, ensure_ascii=False))

            elif msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue
                # RL-001: apply per-IP rate limit to WebSocket chat messages
                client_ip = websocket.client.host if websocket.client else "unknown"
                if not rate_limiter.is_allowed(client_ip, "/api/chat", 30, 60):
                    logger.warning(f"[ws] rate limited message from {client_ip} session={session_id}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "content": "发送太频繁了，请稍后再试。",
                    }, ensure_ascii=False))
                    continue
                logger.info(f"[ws] message session={session_id} len={len(content)}")
                if not session_id:
                    session_id = "default"
                _, agent = session_manager.get_or_create(session_id)
                agent.last_activity_time = time.time()
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, agent.process_message, content)
                await _send_segments(websocket, agent, response, agent.emotion)

            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "content": str(e)}))
        except (WebSocketDisconnect, ConnectionError, RuntimeError):
            pass  # Client already disconnected, can't send error
    finally:
        # #158: remove from connection tracking
        _ws_connections[:] = [c for c in _ws_connections if c.get("ws") is not websocket]
        if session_id:
            session_manager.remove(session_id)
