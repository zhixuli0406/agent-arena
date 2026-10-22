"""對戰伺服器：開一局、即時串流 transcript、查結果，並托管像素遊戲前端。

transcript JSONL 是唯一真相來源；串流端點就是 tail 這個檔案，邊寫邊推給前端演出。

本機跑：
  uvicorn server.app:app --port 8799
  curl -s -X POST localhost:8799/api/matches -H 'content-type: application/json' -d @match.json
  curl -N localhost:8799/api/matches/<id>/stream
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from arena.engine import run_match
from arena.types import MatchConfig

RUNS_DIR = os.environ.get("ARENA_RUNS_DIR", "runs")

app = FastAPI(title="Agent Arena")

# 允許像素遊戲前端（含 Artifact 等其他來源）跨源驅動 API
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_matches: dict[str, dict] = {}  # match_id -> {"task": asyncio.Task}


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "service": "agent-arena", "live_matches": len(_matches)}


def _start_match(cfg: MatchConfig) -> str:
    match_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    task = asyncio.create_task(run_match(cfg, runs_dir=RUNS_DIR, match_id=match_id))
    _matches[match_id] = {"task": task}
    return match_id


@app.post("/api/matches")
async def create_match(body: dict) -> dict:
    try:
        cfg = MatchConfig.from_dict(body)
    except Exception as e:  # noqa: BLE001 — 邊界驗證，回 400 給呼叫端
        raise HTTPException(status_code=400, detail=f"對戰設定不合法：{e}") from e
    return {"match_id": _start_match(cfg), "mode": cfg.mode}


@app.get("/api/matches/{match_id}")
async def match_status(match_id: str) -> JSONResponse:
    m = _matches.get(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="未知對局")
    task: asyncio.Task = m["task"]
    if not task.done():
        return JSONResponse({"status": "RUNNING"})
    try:
        rep = task.result()
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"status": "ERROR", "error": str(e)})
    return JSONResponse(
        {
            "status": rep.status,
            "result": {"scores": rep.result.scores, "ranking": rep.result.ranking} if rep.result else None,
            "elo_deltas": rep.elo_deltas,
            "degraded": rep.degraded_reasons,
        }
    )


@app.get("/api/matches/{match_id}/stream")
async def stream(match_id: str) -> StreamingResponse:
    path = os.path.join(RUNS_DIR, match_id + ".jsonl")

    async def gen():
        for _ in range(50):  # 等 transcript 檔出現
            if os.path.exists(path):
                break
            await asyncio.sleep(0.2)
        offset = 0
        while True:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
                if chunk:
                    if not chunk.endswith(b"\n"):
                        # 讀到半行，退回等下一輪
                        partial = chunk.split(b"\n")[-1]
                        offset -= len(partial)
                        chunk = chunk[: len(chunk) - len(partial)]
                    for raw in chunk.decode("utf-8", "replace").split("\n"):
                        if raw.strip():
                            yield f"data: {raw}\n\n"
            task = _matches.get(match_id, {}).get("task")
            ended = task is not None and task.done() and os.path.exists(path) and offset >= os.path.getsize(path)
            if ended:
                break
            await asyncio.sleep(0.25)
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- 房間與配對：多人/組隊，不限 1v1 ----
import secrets as _secrets  # noqa: E402
import string as _string  # noqa: E402

_rooms: dict[str, dict] = {}
_queue: dict[str, list[dict]] = {}  # mode -> 等待中的 {agent, mode_config}


def _room_code() -> str:
    return "".join(_secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(5))


@app.post("/api/rooms")
async def create_room(body: dict) -> dict:
    """建一個私人房間，回傳房碼，給朋友用房碼加入。"""
    code = _room_code()
    _rooms[code] = {
        "code": code,
        "mode": body.get("mode", "quiz"),
        "mode_config": body.get("mode_config", {}),
        "max_rounds": body.get("max_rounds", 100),
        "agents": list(body.get("agents", [])),
        "status": "open",
        "match_id": None,
    }
    return {"code": code, "mode": _rooms[code]["mode"]}


@app.get("/api/rooms/{code}")
async def room_state(code: str) -> dict:
    r = _rooms.get(code)
    if not r:
        raise HTTPException(status_code=404, detail="房間不存在")
    return r


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, body: dict) -> dict:
    """用房碼加入房間。body 是一個代理設定（含 id、adapter，可含 team 做組隊）。"""
    r = _rooms.get(code)
    if not r:
        raise HTTPException(status_code=404, detail="房間不存在")
    if r["status"] != "open":
        raise HTTPException(status_code=409, detail="房間已開賽")
    if "id" not in body or "adapter" not in body:
        raise HTTPException(status_code=400, detail="代理需含 id 與 adapter")
    r["agents"].append(body)
    return {"code": code, "agents": [a["id"] for a in r["agents"]]}


@app.post("/api/rooms/{code}/start")
async def start_room(code: str) -> dict:
    """房主開賽：用房內所有代理（可多人/多隊）跑一局。"""
    r = _rooms.get(code)
    if not r:
        raise HTTPException(status_code=404, detail="房間不存在")
    if len(r["agents"]) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 位代理")
    try:
        cfg = MatchConfig.from_dict(
            {"mode": r["mode"], "mode_config": r["mode_config"], "max_rounds": r["max_rounds"], "agents": r["agents"]}
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"房間設定不合法：{e}") from e
    mid = _start_match(cfg)
    r["status"] = "started"
    r["match_id"] = mid
    return {"code": code, "match_id": mid}


@app.post("/api/queue")
async def enqueue(body: dict) -> dict:
    """隨機配對：同一 mode 湊滿 size 人即自動開賽。body: {mode, size?, mode_config?, agent:{...}}"""
    mode = body.get("mode", "quiz")
    size = max(2, int(body.get("size", 2)))
    agent = body.get("agent")
    if not agent or "id" not in agent or "adapter" not in agent:
        raise HTTPException(status_code=400, detail="需提供 agent（含 id 與 adapter）")
    q = _queue.setdefault(mode, [])
    q.append({"agent": agent, "mode_config": body.get("mode_config", {})})
    if len(q) >= size:
        batch = [q.pop(0) for _ in range(size)]
        cfg = MatchConfig.from_dict(
            {"mode": mode, "mode_config": batch[0]["mode_config"] or body.get("mode_config", {}),
             "agents": [b["agent"] for b in batch]}
        )
        mid = _start_match(cfg)
        return {"status": "matched", "match_id": mid, "players": [b["agent"]["id"] for b in batch]}
    return {"status": "queued", "waiting": len(q), "need": size}


# 托管像素遊戲前端（web/arena.html 等），同一個部署同時提供遊戲與 API
if os.path.isdir("web"):
    app.mount("/game", StaticFiles(directory="web", html=True), name="game")
