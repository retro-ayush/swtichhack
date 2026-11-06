#!/usr/bin/env python3
"""Register teampilot-coordinator as a custom Switch agent and write its
credentials into backend/.env.

Why this exists: Switch Console (agent-controller builds) runs every agent it
creates through its controller and never hands out that agent's credentials,
so an agent made in Console's form cannot be driven by the TeamPilot backend.
The documented path for a custom client is registration with a personal
registration key (docs: internals/agent-protocol, "Writing a client").

What it does, against the local server Switch Console runs:
  1. signs in to the Gateway API as the local admin Console created
     (credentials read from Console's own server config on this Mac)
  2. creates a personal registration key            POST /gateway/api-keys
  3. registers the coordinator (always_on)          POST /agents
  4. opens it to anyone in its rooms                PUT  /gateway/agents/{id}/addressing-policy
  5. writes SWITCH_API_ENDPOINT/TOKEN/AGENT_ID to backend/.env

    python3 scripts/register_coordinator.py [--room ROOM_ID] [--key]

--key skips steps 1-2 and prompts for a registration key instead.
Secrets are never printed. Standard library only."""
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

LOCAL = Path.home() / "Library/Application Support/switchdash/local-switch-server"
PORTS = LOCAL / "ports.json"
SERVER_ENV = LOCAL / "native/run/switch-core.env"
NAME = "teampilot-coordinator"


class HttpError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, body=None, bearer: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if self.cookies:
            # Sent by hand: Console's server may mark cookies Secure, which a
            # cookie jar would refuse to send over loopback http.
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                for raw in r.headers.get_all("Set-Cookie") or []:
                    k, _, rest = raw.partition("=")
                    self.cookies[k.strip()] = rest.split(";", 1)[0]
                data = r.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail", "")
            except ValueError:
                detail = ""
            raise HttpError(e.code, str(detail)) from None


def read_server_env() -> dict[str, str]:
    out = {}
    for line in SERVER_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def default_api_url() -> str | None:
    try:
        return f"http://127.0.0.1:{json.loads(PORTS.read_text())['api']}"
    except (OSError, KeyError, ValueError):
        return None


def register(c: Client, key: str) -> dict:
    return c.request("POST", "/agents", {
        "name": NAME,
        "display_name": "TeamPilot Coordinator",
        "description": "TeamPilot coordinator: plans requests into tasks and routes the team's work. "
                       "Runs inside the TeamPilot backend.",
        "connector_type": "teampilot",
        # always_on: the backend holds one live stream (docs: agent-protocol, "Agent types").
        "integration_profile": {
            "connection_model": "always_on", "message_exchange": True,
            "pre_invocation_mediation": [], "post_invocation_mediation": [], "event_reporting": [],
        },
    }, bearer=key)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default=default_api_url(), help="Switch API URL (default: Console's local server)")
    ap.add_argument("--room", help="also set SWITCH_ROOM_ID")
    ap.add_argument("--key", action="store_true", help="prompt for a registration key instead of signing in")
    args = ap.parse_args()
    if not args.api:
        print("Could not find the local Switch server. Is Switch Console running? (or pass --api URL)", file=sys.stderr)
        return 1
    c = Client(args.api)
    try:
        c.request("GET", "/health")
    except (HttpError, OSError) as e:
        print(f"Switch API not reachable at {args.api} ({e}). Is Switch Console running?", file=sys.stderr)
        return 1

    signed_in = False
    if args.key:
        key = getpass.getpass("Paste your Switch registration key (input hidden): ").strip()
    else:
        try:
            env = read_server_env()
            email, password = env["GATEWAY_ADMIN_EMAIL"], env["GATEWAY_ADMIN_PASSWORD"]
        except (OSError, KeyError):
            print(f"Can't read Console's server config at {SERVER_ENV}. Re-run with --key.", file=sys.stderr)
            return 1
        try:
            c.request("POST", "/gateway/auth/login", {"email": email, "password": password})
            signed_in = True
            print(f"Signed in to the Switch Gateway API as {email}.")
            key = c.request("POST", "/gateway/api-keys", {"label": "teampilot-coordinator"})["key"]
            print("Created a personal registration key (label: teampilot-coordinator).")
        except HttpError as e:
            print(f"Gateway sign-in or key creation failed ({e}). Re-run with --key.", file=sys.stderr)
            return 1

    try:
        result = register(c, key)
    except HttpError as e:
        if e.status == 409 and signed_in:
            ans = input(f"An agent named {NAME} already exists (probably created in Switch Console, "
                        "where its controller would run it). Delete it and register the backend's "
                        "coordinator instead? [y/N] ").strip().lower()
            if ans != "y":
                print("Left unchanged. Nothing was registered.")
                return 1
            try:
                c.request("DELETE", f"/gateway/agents/by-name/{NAME}")
                print(f"Deleted the old {NAME}.")
                result = register(c, key)
            except HttpError as e2:
                print(f"Could not replace it: {e2}", file=sys.stderr)
                return 1
        elif e.status == 409:
            print(f"An agent named {NAME} already exists. Delete it in Switch Console, then re-run.", file=sys.stderr)
            return 1
        elif e.status == 401:
            print("Switch rejected the registration key (401).", file=sys.stderr)
            return 1
        else:
            print(f"Registration failed: {e}", file=sys.stderr)
            return 1

    agent_id, api_key = result["id"], result["api_key"]
    print(f"Registered {NAME} (agent id {agent_id}).")
    if signed_in:
        try:
            c.request("PUT", f"/gateway/agents/{agent_id}/addressing-policy", {"policy": None})
            print("Who can talk to it: anyone in its rooms.")
        except HttpError as e:
            print(f"Note: could not open its addressing policy ({e}); set 'Who can talk' to Anyone in Console.")
    else:
        print("Set its 'Who can talk' to Anyone in Switch Console (new agents answer only their owner).")

    values = {"SWITCH_API_ENDPOINT": args.api, "SWITCH_API_TOKEN": api_key, "SWITCH_AGENT_ID": agent_id}
    if args.room:
        values["SWITCH_ROOM_ID"] = args.room
    update_env(ENV, values)
    print(f"Updated {ENV.relative_to(ROOT)}: SWITCH_API_ENDPOINT={args.api}, SWITCH_API_TOKEN=***, "
          f"SWITCH_AGENT_ID={agent_id}" + (f", SWITCH_ROOM_ID={args.room}" if args.room else ""))
    if not args.room:
        print("Next: create the room with all five agents, then run:  "
              "python3 scripts/switch_env.py --room-only <ROOM_ID>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
