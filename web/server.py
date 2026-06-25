import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from config import load_config
from web.session import SessionManager

logger = logging.getLogger(__name__)

config = load_config()
session_manager = SessionManager(config)


# WS-028: Content-Security-Policy — restrict fetch/script origins to block inline
# injection from any WebSocket-delivered content. Local dev allows self + localhost.
CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' ws://localhost:* http://localhost:* http://127.0.0.1:*; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "frame-ancestors 'none'"
)
# WS-027: X-Frame-Options DENY — defense-in-depth against clickjacking alongside CSP frame-ancestors
XFO_HEADER = "DENY"


async def _add_security_headers(request: Request, call_next):
    """Add CSP + X-Frame-Options + no-sniff on every response. (#WS-027/#WS-028)"""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP_HEADER
    response.headers["X-Frame-Options"] = XFO_HEADER
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-setup file logging — uvicorn resets root handlers on startup
    try:
        from core.logging_setup import setup_logging as _re_setup
        _re_setup(getattr(load_config(), 'log_level', 'INFO'))
    except Exception:
        pass
    logger.info("Server starting...")
    await session_manager.open()
    yield
    # #212: graceful shutdown — also evict stale sessions via cleanup_old
    logger.info("Server shutting down...")
    session_manager.cleanup_old()
    await session_manager.shutdown()


# WS-003: CORS — only localhost origins may browse the API; cross-origin reads
# are blocked by default, WebSocket Origin validation lives in the endpoint.
app = FastAPI(
    lifespan=lifespan,
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ],
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
        ),
        Middleware(_add_security_headers),
    ],
)
app.mount("/static", StaticFiles(directory="web/static"), name="static")


@app.get("/")
async def index():
    from fastapi.responses import FileResponse
    return FileResponse("web/static/index.html")


@app.post("/api/chat")
async def chat_api(body: dict):
    session_id = body.get("session_id", "default")
    message = body.get("message", "")
    if not message.strip():
        return {"error": "empty message"}
    logger.info(f"[rest] chat session={session_id} len={len(message)}")
    _, agent = session_manager.get_or_create(session_id)
    response = agent.process_message(message)
    logger.info(f"[rest] chat_done session={session_id} turn={agent.turn_count} emotion={agent.emotion} resp_len={len(response)}")
    return {
        "response": response,
        "emotion": agent.emotion,
        "turn": agent.turn_count,
        "session_id": session_id,
    }


@app.get("/api/status")
async def status_api(session_id: str = "default"):
    """Return relationship metrics + history (#132)."""
    _, agent = session_manager.get_or_create(session_id)
    ag = agent.agent
    rel = ag.ltm.get_relationship()
    history = ag.ltm.get_relationship_history(days=7)
    return {
        "turn": ag.turn_count,
        "emotion": agent.emotion,
        "relationship": rel,
        "relationship_history": history,
    }


@app.get("/api/chat/history")
async def chat_history_api(session_id: str = "default"):
    """Return recent conversation turns for UI display on reconnect."""
    _, agent = session_manager.get_or_create(session_id)
    ag = agent.agent
    turns = []
    for t in ag.short_term.get_all():
        turns.append({
            "role": t.role,
            "content": t.content,
        })
    return {"turns": turns, "session_id": session_id}


def _calc_delay(emotion: str, seg_len: int) -> float:
    base = {
        "excited": 0.7, "joyful": 0.9, "trusting": 1.1, "surprised": 0.8,
        "engaged": 1.3, "content": 1.5, "anticipating": 0.9,
        "neutral": 1.7, "anxious": 1.0, "afraid": 1.3,
        "melancholy": 2.2, "sad": 2.5, "frustrated": 1.5, "angry": 1.0, "disgusted": 1.3,
    }.get(emotion, 1.7)
    return base * (1.0 + seg_len / 80) * random.uniform(0.8, 1.3)


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
    segments = _split_segments(response)
    for i, seg in enumerate(segments):
        if i > 0:
            await asyncio.sleep(_calc_delay(emotion, len(seg)))
        await websocket.send_text(json.dumps({
            "type": "segment", "content": seg,
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
            ag = agent.agent

            # Sleep/Wake cycle (only check if not in transition cooldown)
            if sleep_cooldown == 0:
                should_sleep, msg = await ag._get_sleep_state()
                if msg:
                    logger.info(f"Sleep/wake message: sleeping={ag._sleeping} msg={msg[:50]}")
                    ag.last_activity_time = time.time()
                    cooldown = 60
                    sleep_cooldown = 120  # 10 min cooldown on sleep transitions
                    await _send_segments(active_ws, agent, msg, agent.emotion)
                    if should_sleep:
                        await ag._generate_dream()
            else:
                sleep_cooldown = max(0, sleep_cooldown - 1)
            if ag._sleeping:
                await asyncio.sleep(30)
                continue

            idle = time.time() - ag.last_activity_time
            if idle < 30 or cooldown > 0:
                cooldown = max(0, cooldown - 1)
                await asyncio.sleep(5)
                continue

            score = ag._calculate_proactivity(idle)
            if random.random() < score:
                loop = asyncio.get_event_loop()

                # Agent 1 (InnerDrive) decides what to do
                intent = await loop.run_in_executor(
                    None, ag.decide_proactive_action, idle
                )

                if intent.action == "explore" and ag._check_rate_limit("explore"):
                    response = await loop.run_in_executor(
                        None, agent.process_explore_with_intent, intent
                    )
                elif intent.action == "chat" and ag._check_rate_limit("chat"):
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
                    ag.last_activity_time = time.time()
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
    allowed = {"http://localhost:8000", "http://127.0.0.1:8000", "null"}
    if origin and origin not in allowed and not origin.startswith("http://localhost"):
        logger.warning(f"[ws] rejected origin: {origin}")
        await websocket.close(code=4003)
        return

    await websocket.accept()
    logger.info(f"[ws] accepted: {websocket.client.host}:{websocket.client.port}")
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
                session_id, agent = session_manager.get_or_create(sid)
                logger.info(f"[ws] init session={session_id} sid_param={sid}")
                # Register proactive task per-session (replaces old task if exists)
                task = asyncio.create_task(_proactive_loop(websocket, session_id))
                session_manager.register_proactive(session_id, task, websocket)
                await websocket.send_text(json.dumps({
                    "type": "init_ok", "session_id": session_id,
                    "emotion": agent.emotion,
                }, ensure_ascii=False))

            elif msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue
                logger.info(f"[ws] message session={session_id} len={len(content)}")
                if not session_id:
                    session_id = "default"
                _, agent = session_manager.get_or_create(session_id)
                agent.agent.last_activity_time = time.time()
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
        if session_id:
            session_manager.remove(session_id)
