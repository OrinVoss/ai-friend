import asyncio
import json
import logging
import random
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from config import load_config
from web.session import SessionManager

logger = logging.getLogger(__name__)

config = load_config()
session_manager = SessionManager(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Server starting...")
    yield
    logger.info("Server shutting down...")


app = FastAPI(lifespan=lifespan)
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
    _, agent = session_manager.get_or_create(session_id)
    response = agent.process_message(message)
    return {
        "response": response,
        "emotion": agent.emotion,
        "turn": agent.turn_count,
        "session_id": session_id,
    }


def _calc_delay(emotion: str, seg_len: int) -> float:
    base = {
        "excited": 1.8, "joyful": 2.0, "trusting": 2.5, "surprised": 1.8,
        "engaged": 3.0, "content": 3.5, "anticipating": 2.0,
        "neutral": 4.0, "anxious": 2.5, "afraid": 3.0,
        "melancholy": 5.0, "sad": 6.0, "frustrated": 3.5, "angry": 2.5, "disgusted": 3.0,
    }.get(emotion, 4.0)
    return base * (1.0 + seg_len / 80) * random.uniform(0.8, 1.5)


def _split_segments(text: str) -> list[str]:
    parts = re.split(r'(?<=[。！？.!?\n])(?:\s*)(?=\S)', text)
    segments = [s.strip() for s in parts if s.strip()]
    final = []
    for s in segments:
        if len(s) > 40:
            sub = re.split(r'(?<=[，,；;])\s*', s)
            final.extend(x.strip() for x in sub if x.strip())
        else:
            final.append(s)
    merged = []
    for s in final:
        if merged and len(s) < 6:
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
    while True:
        try:
            _, agent = session_manager.get_or_create(session_id)
            idle = time.time() - agent.agent.last_activity_time
            if idle < config.proactive_min_idle:
                await asyncio.sleep(5)
                continue
            score = agent.agent._calculate_proactivity(idle)
            if random.random() < score:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, agent.process_proactive)
                if response:
                    await _send_segments(websocket, agent, response, agent.emotion)
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Proactive error: {e}")
            await asyncio.sleep(30)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = None
    proactive_task = None

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type == "init":
                sid = data.get("session_id")
                session_id, agent = session_manager.get_or_create(sid)
                if proactive_task:
                    proactive_task.cancel()
                proactive_task = asyncio.create_task(
                    _proactive_loop(websocket, session_id)
                )
                await websocket.send_text(json.dumps({
                    "type": "init_ok", "session_id": session_id,
                    "emotion": agent.emotion,
                }, ensure_ascii=False))

            elif msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue
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
        except Exception:
            pass
    finally:
        if proactive_task:
            proactive_task.cancel()
