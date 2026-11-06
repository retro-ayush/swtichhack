from app.config import settings


def test_token_protects_reads_and_writes_when_set(client):
    settings.api_token = "s3cret"
    try:
        assert client.get("/api/projects").status_code == 401
        assert client.post("/api/projects", json={"name": "x"}).status_code == 401
        assert client.get("/api/projects", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = client.get("/api/projects", headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
        assert client.get("/health").status_code == 200  # liveness stays public
    finally:
        settings.api_token = ""


def test_open_when_unset(client):
    assert client.get("/api/projects").status_code == 200


def test_oversized_message_rejected(client):
    pid = client.get("/api/projects").json()[0]["id"]
    r = client.post(f"/api/projects/{pid}/chat", json={"content": "x" * 20_001})
    assert r.status_code == 422
