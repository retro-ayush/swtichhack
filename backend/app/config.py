"""Environment-driven settings. Everything optional has a safe default."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./teampilot.db"))
    # Switch agent-protocol credentials (written by Switch Console on registration).
    switch_endpoint: str = field(default_factory=lambda: _env("SWITCH_API_ENDPOINT"))
    switch_token: str = field(default_factory=lambda: _env("SWITCH_API_TOKEN"))
    switch_agent_id: str = field(default_factory=lambda: _env("SWITCH_AGENT_ID"))
    switch_room_id: str = field(default_factory=lambda: _env("SWITCH_ROOM_ID"))
    # LLM decomposition (optional; rule-based fallback without it).
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5-5"))
    # Optional bearer token protecting mutating routes.
    api_token: str = field(default_factory=lambda: _env("TEAMPILOT_API_TOKEN"))
    seed_demo: bool = field(default_factory=lambda: _env("SEED_DEMO", "1") != "0")
    # Loop/retry guards.
    max_agent_messages_per_task: int = 12
    max_task_attempts: int = 3
    # Time guards (housekeeping sweep): a task with no activity for this long
    # is blocked and escalated; an agent silent this long is shown offline.
    stale_task_minutes: int = field(default_factory=lambda: int(_env("STALE_TASK_MINUTES", "20")))
    agent_offline_minutes: int = field(default_factory=lambda: int(_env("AGENT_OFFLINE_MINUTES", "10")))

    @property
    def switch_configured(self) -> bool:
        return bool(self.switch_endpoint and self.switch_token and self.switch_agent_id)


settings = Settings()
