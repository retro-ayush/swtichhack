#!/usr/bin/env python3
"""Register teampilot-coordinator as a custom Switch agent and write its
credentials into backend/.env.

Why this exists: Switch Console (agent-controller builds) runs every agent it
creates through its controller and never hands out that agent's credentials,
so an agent made in Console cannot be driven by the TeamPilot backend. The
documented path for a custom client is registration with a personal
registration key (docs: internals/agent-protocol, "Writing a client"):

    POST <api>/agents   Authorization: Bearer <registration key>
    -> {"id", "api_key"}          (the api_key is returned once)

Usage:
    python3 scripts/register_coordinator.py              # prompts for the key (hidden)
    python3 scripts/register_coordinator.py --room ID    # also bind the room

The registration key is created in the Switch Gateway (API keys page); it
makes the coordinator owned by you, like your other agents. Neither the key
nor the agent's API key is ever printed. Standard library only."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from switch_env import ENV, ROOT, update_env  # noqa: E402

PORTS = Path.home() / "Library/Application Support/switchdash/local-switch-server/ports.json"
NAME = "teampilot-coordinator"


def default_api_url() -> str | None:
    try:
        return f"http://127.0.0.1:{json.loads(PORTS.read_text())['api']}"
    except (OSError, KeyError, ValueError):
        return None


def post(url: str, token: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {"detail": "(non-JSON error body)"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=default_api_url(),
                    help="Switch agent-bridge API URL (default: the local server Console runs)")
    ap.add_argument("--room", help="also set SWITCH_ROOM_ID")
    args = ap.parse_args()
    if not args.api:
        print("Could not find the local Switch server. Pass --api http://127.0.0.1:<api port>.", file=sys.stderr)
        return 1

    try:
        with urllib.request.urlopen(f"{args.api}/health", timeout=5) as r:
            r.read()
    except OSError as e:
        print(f"Switch API not reachable at {args.api} ({e}). Is Switch Console running?", file=sys.stderr)
        return 1

    key = getpass.getpass("Paste your Switch registration key (input hidden): ").strip()
    if not key:
        print("No key given.", file=sys.stderr)
        return 1

    status, body = post(f"{args.api}/agents", key, {
        "name": NAME,
        "display_name": "TeamPilot Coordinator",
        "description": "TeamPilot coordinator: plans requests into tasks and routes the team's work. "
                       "Runs inside the TeamPilot backend.",
        "connector_type": "teampilot",
        # always_on: the backend holds one live stream; Switch reports it live
        # whenever it is connected (docs: agent-protocol, "Agent types").
        "integration_profile": {
            "connection_model": "always_on",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    })
    if status == 409:
        print(f"An agent named {NAME} already exists. Delete it in Switch Console "
              "(Your Agents -> teampilot-coordinator -> delete), then run this again.", file=sys.stderr)
        return 1
    if status == 401:
        print("Switch rejected the key (401). Create a new one on the Gateway's API keys page "
              "and paste the full key.", file=sys.stderr)
        return 1
    if status != 200 or "api_key" not in body:
        print(f"Registration failed: HTTP {status}: {body.get('detail', body)}", file=sys.stderr)
        return 1

    values = {"SWITCH_API_ENDPOINT": args.api, "SWITCH_API_TOKEN": body["api_key"],
              "SWITCH_AGENT_ID": body["id"]}
    if args.room:
        values["SWITCH_ROOM_ID"] = args.room
    update_env(ENV, values)
    print(f"Registered {NAME} (agent id {body['id']}).")
    print(f"Updated {ENV.relative_to(ROOT)}: SWITCH_API_ENDPOINT={args.api}, SWITCH_API_TOKEN=***, "
          f"SWITCH_AGENT_ID={body['id']}" + (f", SWITCH_ROOM_ID={args.room}" if args.room else ""))
    if not args.room:
        print("Next: create the room with this agent in it, then run:  "
              "python3 scripts/switch_env.py --room-only <ROOM_ID>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
