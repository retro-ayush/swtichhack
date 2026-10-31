from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import events
from .config import settings
from .db import SessionLocal
from .engine.housekeeping import mark_coordinator, run_sweep
from .migrate import upgrade_to_head
from .routers.api import router
from .seed import seed
from .switchbridge import adapter as switch
from .switchbridge.connector import on_domain_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("teampilot")

HOUSEKEEPING_INTERVAL_S = 60


async def _housekeeping_loop() -> None:
    while True:
        await asyncio.sleep(HOUSEKEEPING_INTERVAL_S)
        await asyncio.to_thread(run_sweep)


@asynccontextmanager
async def lifespan(app: FastAPI):
    upgrade_to_head()
    with SessionLocal() as db:
        if settings.seed_demo:
            seed(db)
        mark_coordinator(db, online=True)
    events.set_loop(asyncio.get_running_loop())

    adapter = switch.build_from_settings()
    if adapter is not None:
        adapter.on_event = on_domain_event
        await adapter.start()
        log.info("Switch adapter starting (agent %s, room %s)", adapter.agent_id, adapter.room_id or "-")
    else:
        log.info("Switch not configured — running in local mode (set SWITCH_* env vars)")
    sweeper = asyncio.create_task(_housekeeping_loop(), name="housekeeping")

    yield

    sweeper.cancel()
    if adapter is not None:
        await adapter.stop()
    with SessionLocal() as db:
        mark_coordinator(db, online=False)


app = FastAPI(title="TeamPilot AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health():
    return {"ok": True, "switch": switch.status()["state"]}
