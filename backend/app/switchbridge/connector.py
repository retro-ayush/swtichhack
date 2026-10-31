"""Wires Switch room events into the coordination engine.

Every room message is mirrored into the DB (that's what the dashboard chat
shows). Validated JSON cards from known agents drive the engine; an addressed
human message becomes a user request."""
from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select

from ..db import SessionLocal
from ..engine import coordinator
from ..models import Agent, Project

log = logging.getLogger(__name__)

_MENTION = re.compile(r"@[\w.\-]+")


async def on_domain_event(evt: dict) -> None:
    if evt.get("type") != "message":
        return
    payload = evt.get("payload") or {}
    if payload.get("sender_name") == coordinator.COORDINATOR_NAME:
        return  # our own posts echo back on filter=all
    # DB work runs sync; keep it off the event loop.
    await asyncio.to_thread(_process_message, payload)


def _process_message(payload: dict) -> None:
    db = SessionLocal()
    try:
        project = db.execute(select(Project).order_by(Project.id)).scalars().first()
        if project is None:
            return
        sender_name = payload.get("sender_name") or payload.get("sender") or "unknown"
        body = payload.get("body") or ""
        agent_names = set(db.execute(
            select(Agent.name).where(Agent.project_id == project.id)
        ).scalars().all())
        sender_type = "agent" if sender_name in agent_names else "human"

        card = coordinator.extract_card(body) if sender_type == "agent" else None
        msg = coordinator._persist_message(
            db, project.id, sender_type=sender_type, sender_name=sender_name,
            content=body, message_type=(card.type if card else "CHAT"),
            structured=card.model_dump(by_alias=True) if card else None,
            delivered_via="switch",
            thread_id=payload.get("thread_id") or "",
            switch_message_id=payload.get("message_id") or "",
        )
        if card is not None:
            coordinator.handle_card(db, project, card, msg)
        elif sender_type == "human" and payload.get("addressed"):
            text = _MENTION.sub("", body).strip()
            if text:
                coordinator.handle_user_request(db, project, text, sender_name)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("failed to process Switch message")
    finally:
        db.close()
