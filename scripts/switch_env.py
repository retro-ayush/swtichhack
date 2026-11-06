#!/usr/bin/env python3
"""Copy the coordinator's Switch credentials into backend/.env.

Switch Console writes an agent's credentials to
<agent directory>/.switch/agents/<name>.json as
{"env": {"SWITCH_API_ENDPOINT", "SWITCH_API_TOKEN", "SWITCH_AGENT_ID"}}
(docs: switch-rooms/internals/connectors-and-runtime).

    python3 scripts/switch_env.py [--room ROOM_ID] [--json PATH]

Existing keys in backend/.env are updated in place; other lines are kept.
The token is never printed. Standard library only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "backend" / ".switch" / "agents" / "teampilot-coordinator.json"
ENV = ROOT / "backend" / ".env"
KEYS = ("SWITCH_API_ENDPOINT", "SWITCH_API_TOKEN", "SWITCH_AGENT_ID")


def update_env(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].lstrip("# ").strip()
        if key in values and "=" in line:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--room", help="Switch room id to bind (SWITCH_ROOM_ID)")
    ap.add_argument("--room-only", metavar="ROOM_ID",
                    help="only set SWITCH_ROOM_ID (credentials came from register_coordinator.py)")
    args = ap.parse_args()

    if args.room_only:
        update_env(ENV, {"SWITCH_ROOM_ID": args.room_only})
        print(f"updated {ENV.relative_to(ROOT)}: SWITCH_ROOM_ID={args.room_only}")
        return 0

    if not args.json.exists():
        print(f"not found: {args.json}\nRegister teampilot-coordinator in Switch Console with directory "
              f"{ROOT / 'backend'} first (TODO_NOV4.txt step A3), or pass --json.", file=sys.stderr)
        return 1
    env = json.loads(args.json.read_text(encoding="utf-8")).get("env", {})
    missing = [k for k in KEYS if not env.get(k)]
    if missing:
        print(f"{args.json} is missing {', '.join(missing)}", file=sys.stderr)
        return 1
    values = {k: env[k] for k in KEYS}
    if args.room:
        values["SWITCH_ROOM_ID"] = args.room
    update_env(ENV, values)
    print(f"updated {ENV.relative_to(ROOT)}: " + ", ".join(
        f"{k}={'***' if k == 'SWITCH_API_TOKEN' else v}" for k, v in values.items()))
    if not args.room:
        print("next: re-run with --room <SWITCH_ROOM_ID> once the room exists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
