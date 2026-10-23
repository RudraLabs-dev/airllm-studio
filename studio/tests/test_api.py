import json

import pytest

from conftest import BASE_URL


def ndjson(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


# --- Ollama-compatible -------------------------------------------------------------------
def test_version_and_tags(client):
    assert client.get("/api/version").json()["version"]
    tags = client.get("/api/tags").json()["models"]
    assert [m["name"] for m in tags] == ["org/ready-model"]       # error models are hidden
    assert tags[0]["details"]["parameter_size"] == "7.2B"


def test_chat_streaming(client, studio):
    resp = client.post("/api/chat", json={"model": "org/ready-model",
                                          "messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    lines = ndjson(resp)
    text = "".join(line["message"]["content"] for line in lines)
    assert text == studio.engine.reply
    assert lines[-1]["done"] is True and lines[-1]["eval_count"] > 0
    assert not any("progress" in line for line in lines)            # only when asked for


def test_chat_progress_opt_in(client):
    lines = ndjson(client.post("/api/chat", json={
        "model": "org/ready-model", "messages": [{"role": "user", "content": "hi"}],
        "airllm_progress": True}))
    progress = [line["progress"] for line in lines if "progress" in line]
    assert progress and progress[0]["layers"] == 12


def test_chat_non_streaming_and_options(client, studio):
    resp = client.post("/api/chat", json={"model": "org/ready-model", "stream": False,
                                          "messages": [{"role": "user", "content": "hi"}],
                                          "options": {"num_predict": 2}})
    body = resp.json()
    assert body["done"] is True and body["done_reason"] == "length"
    assert body["message"]["content"] == "Hello from"


def test_system_prompt_default_is_applied(client, studio):
    studio.settings.update({"defaults": {"system_prompt": "Be brief."}})
    client.post("/api/chat", json={"model": "org/ready-model", "stream": False,
                                   "messages": [{"role": "user", "content": "hi"}]})
    assert studio.engine.last_messages[0] == {"role": "system", "content": "Be brief."}


def test_generate(client):
    lines = ndjson(client.post("/api/generate", json={"model": "org/ready-model", "prompt": "hi"}))
    assert lines[-1]["done"] and "".join(line["response"] for line in lines).startswith("Hello")


def test_errors(client):
    assert client.post("/api/chat", json={"model": "nope/nope", "messages": []}).status_code == 404
    r = client.post("/api/chat", json={"model": "org/broken-model",
                                       "messages": [{"role": "user", "content": "x"}], "stream": False})
    assert r.status_code == 400 and "not ready" in r.json()["error"]


def test_load_unload_ps(client, studio):
    assert client.get("/api/ps").json() == {"models": []}
    client.post("/api/studio/models/load", json={"name": "org/ready-model"})
    assert client.get("/api/ps").json()["models"][0]["name"] == "org/ready-model"
    client.post("/api/generate", json={"model": "org/ready-model", "keep_alive": 0})
    assert studio.engine.model_name is None


def test_delete(client, studio):
    assert client.request("DELETE", "/api/delete", json={"model": "org/ready-model"}).status_code == 200
    assert studio.store.get("org/ready-model") is None


# --- OpenAI-compatible -------------------------------------------------------------------
def test_openai_models(client):
    data = client.get("/v1/models").json()["data"]
    assert data[0]["id"] == "org/ready-model" and data[0]["object"] == "model"


def test_openai_chat(client, studio):
    r = client.post("/v1/chat/completions", json={
        "model": "org/ready-model", "max_tokens": 3,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]})
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello from **AirLLM**."
    assert body["choices"][0]["finish_reason"] == "length"
    assert body["usage"]["completion_tokens"] == 3


def test_openai_chat_stream(client):
    r = client.post("/v1/chat/completions", json={
        "model": "org/ready-model", "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "hi"}]})
    events = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert chunks[-1]["usage"]["completion_tokens"] > 0
    assert any(c["choices"] and c["choices"][0]["finish_reason"] == "stop" for c in chunks)


def test_openai_stop_and_unknown_model(client):
    assert client.post("/v1/chat/completions", json={"model": "x/y", "messages": []}).status_code == 404


def test_openai_completions(client):
    body = client.post("/v1/completions", json={"model": "org/ready-model", "prompt": "hi"}).json()
    assert body["object"] == "text_completion" and body["choices"][0]["text"]


# --- Studio ------------------------------------------------------------------------------
def test_status_and_models(client):
    status = client.get("/api/studio/status").json()
    assert status["engine"]["state"] == "idle" and status["models_dir"]
    names = [m["name"] for m in client.get("/api/studio/models").json()["models"]]
    assert set(names) == {"org/ready-model", "org/broken-model"}


def test_settings_roundtrip_hides_token(client, studio, home):
    r = client.put("/api/studio/settings", json={"hf_token": "hf_secret", "defaults": {"temperature": 0.2}})
    body = r.json()
    assert body["hf_token"] == "" and body["hf_token_set"] is True
    assert body["defaults"]["temperature"] == 0.2
    assert studio.settings.hf_token() == "hf_secret"
    # an empty token in a later save keeps the stored one; clear_hf_token removes it
    client.put("/api/studio/settings", json={"hf_token": ""})
    assert studio.settings.hf_token() == "hf_secret"
    client.put("/api/studio/settings", json={"clear_hf_token": True})
    assert studio.settings.hf_token() is None
    assert client.put("/api/studio/settings", json={"compression": "2bit"}).status_code == 400


def test_chats_crud(client):
    chat = client.post("/api/studio/chats", json={"title": "First", "model": "org/ready-model",
                                                  "messages": [{"role": "user", "content": "hi"}]}).json()
    assert client.get("/api/studio/chats").json()["chats"][0]["id"] == chat["id"]
    updated = client.patch(f"/api/studio/chats/{chat['id']}", json={"title": "Renamed"}).json()
    assert updated["title"] == "Renamed" and updated["messages"][0]["content"] == "hi"
    assert client.delete(f"/api/studio/chats/{chat['id']}").json()["deleted"]
    assert client.get(f"/api/studio/chats/{chat['id']}").status_code == 404


def test_catalog_marks_installed(client, studio):
    from airllm_studio.store import Manifest

    studio.store.save(Manifest(name="Qwen/Qwen3-8B", status="ready"))
    items = {c["name"]: c for c in client.get("/api/studio/catalog").json()["models"]}
    assert items["Qwen/Qwen3-8B"]["installed"] == "ready"


def test_web_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>AirLLM" in r.text
    assert client.get("/app.js").status_code == 200


def test_api_key_blocks_remote_only(studio, monkeypatch):
    from fastapi.testclient import TestClient

    from airllm_studio.server import create_app

    monkeypatch.setenv("AIRLLM_HOST", "0.0.0.0:11435")       # serving other machines, as documented
    studio.api_key = "s3cret"
    app = create_app(studio, keepalive=False)
    local = TestClient(app, base_url=BASE_URL)              # TestClient host counts as local
    assert local.get("/api/tags").status_code == 200
    remote = TestClient(app, base_url=BASE_URL, client=("203.0.113.9", 5000))
    assert remote.get("/api/tags").status_code == 401
    assert remote.get("/api/tags", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    # a valid key still cannot stop the server from another machine
    assert remote.post("/api/shutdown", headers={"Authorization": "Bearer s3cret"}).status_code == 403


@pytest.mark.parametrize("value,expected", [
    ("", ("127.0.0.1", 11435)), ("0.0.0.0", ("0.0.0.0", 11435)), (":8080", ("127.0.0.1", 8080)),
    ("example.com:99", ("example.com", 99)), ("http://[::1]:7000", ("::1", 7000)),
])
def test_parse_host(value, expected):
    from airllm_studio.config import parse_host

    assert parse_host(value) == expected
