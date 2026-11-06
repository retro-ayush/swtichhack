#!/usr/bin/env python3
"""Compose paste-ready agent instructions for Switch Console.

    python3 scripts/build_agent_prompts.py

Writes agents/dist/teampilot-<role>.txt = agents/_common.md + agents/<role>.md
and agents/dist/room-instructions.txt = docs/PROTOCOL.md + room preamble.
Cross-platform, standard library only."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"
DIST = AGENTS / "dist"
ROLES = ["frontend", "backend", "testing", "reviewer"]

ROOM_PREAMBLE = """This room is a TeamPilot team. The coordinator is teampilot-coordinator.
Humans start work by addressing it; specialists act only on TASK_ASSIGNED
cards and targeted messages, and reply in the same thread.
Demo repository: {demo_repo}

"""


def main() -> int:
    demo_repo = sys.argv[1] if len(sys.argv) > 1 else "<set the demo repo URL: build_agent_prompts.py <url>>"
    common = (AGENTS / "_common.md").read_text(encoding="utf-8")
    DIST.mkdir(exist_ok=True)
    for role in ROLES:
        text = common.rstrip() + "\n\n" + (AGENTS / f"{role}.md").read_text(encoding="utf-8")
        text = text.replace("<your agent name>", f"teampilot-{role}")
        text = text.replace("the room instructions name it", f"it is {demo_repo}")
        out = DIST / f"teampilot-{role}.txt"
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)} ({len(text)} chars)")
    room = ROOM_PREAMBLE.format(demo_repo=demo_repo) + (ROOT / "docs" / "PROTOCOL.md").read_text(encoding="utf-8")
    (DIST / "room-instructions.txt").write_text(room, encoding="utf-8")
    print(f"wrote agents/dist/room-instructions.txt ({len(room)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
