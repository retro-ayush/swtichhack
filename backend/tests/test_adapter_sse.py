import asyncio

from app.switchbridge.adapter import SwitchAdapter


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def test_sse_frames_parsed():
    lines = [
        ": keepalive",
        "event: connection_state",
        'data: {"connection_id": "c", "cursor": 41, "rooms": ["r1"]}',
        "",
        "id: 42",
        "event: message",
        'data: {"type": "message", "room_id": "r1", "sequence": 42,',
        'data:  "payload": {"addressed": true, "body": "hi"}}',
        "",
    ]

    async def collect():
        out = []
        async for frame in SwitchAdapter._iter_sse(FakeResponse(lines)):
            out.append(frame)
        return out

    frames = asyncio.run(collect())
    assert frames[0]["event"] == "connection_state"
    assert frames[1]["event"] == "message"
    assert frames[1]["id"] == "42"
    # multi-line data joins per SSE spec
    import json
    data = json.loads("\n".join(frames[1]["data"]))
    assert data["sequence"] == 42 and data["payload"]["addressed"] is True
