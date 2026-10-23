"""Other websites must not be able to drive the local API through the user's browser, and a model's
own Python code only runs when the user allowed it."""
import json
import time

import pytest
from conftest import BASE_URL

from airllm_studio import store as store_mod
from airllm_studio.engine import Engine, EngineError
from airllm_studio.security import host_allowed, host_name, origin_allowed
from airllm_studio.store import Manifest, ModelStore, remote_code_refs, select_files

EVIL = "https://evil.example"
LOCAL = frozenset({"localhost", "127.0.0.1", "::1"})


# --- header rules ------------------------------------------------------------------------
@pytest.mark.parametrize("header,name", [
    ("127.0.0.1:11435", "127.0.0.1"), ("LocalHost:11435", "localhost"), ("[::1]:11435", "::1"),
    ("::1", "::1"), ("gpu-box.lan", "gpu-box.lan"),
])
def test_host_name(header, name):
    assert host_name(header) == name


def test_host_rules():
    assert host_allowed("127.0.0.1:11435", LOCAL) and host_allowed("localhost:11435", LOCAL)
    assert host_allowed("192.168.1.20:11435", LOCAL)          # IP literals cannot be rebound
    assert host_allowed("[fe80::1]:11435", LOCAL)
    assert not host_allowed("evil.example:11435", LOCAL)       # DNS rebinding
    assert not host_allowed("localhost.evil.example", LOCAL)
    assert host_allowed("gpu-box.lan:11435", LOCAL | {"gpu-box.lan"})


def test_origin_rules():
    host = "127.0.0.1:11435"
    assert origin_allowed(None, host, frozenset())                         # curl, SDKs, CLI
    assert origin_allowed("http://127.0.0.1:11435", host, frozenset())     # the Studio UI itself
    assert not origin_allowed("http://localhost:11435", host, frozenset())  # another origin
    assert not origin_allowed(EVIL, host, frozenset())
    assert not origin_allowed("null", host, frozenset())
    assert origin_allowed("http://localhost:3000/", host, frozenset({"http://localhost:3000"}))
    assert origin_allowed(EVIL, host, frozenset({"*"}))


# --- through the API ---------------------------------------------------------------------
@pytest.fixture
def pulled(studio, monkeypatch):
    names = []
    monkeypatch.setattr(ModelStore, "_run_hf_pull", lambda self, job, manifest, repo: names.append(repo))
    return names


def test_cross_site_simple_post_is_refused(client, studio, pulled):
    # What a hostile page can send without a CORS preflight: text/plain body, its own Origin.
    resp = client.post("/api/studio/models/pull", content=b'{"name": "attacker/evil-model"}',
                       headers={"Origin": EVIL, "Content-Type": "text/plain"})
    assert resp.status_code == 403 and "AIRLLM_ORIGINS" in resp.json()["error"]
    assert pulled == [] and "attacker/evil-model" not in studio.store.jobs
    for path in ("/api/shutdown", "/api/studio/chats", "/api/pull", "/v1/chat/completions"):
        assert client.post(path, content=b"{}", headers={"Origin": EVIL}).status_code == 403, path
    assert client.put("/api/studio/settings", json={"models_dir": "/tmp/x"},
                      headers={"Origin": EVIL}).status_code == 403


def test_cross_site_get_is_refused(client):
    assert client.get("/api/studio/chats", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/studio/chats", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.get("/api/studio/chats", headers={"Sec-Fetch-Site": "none"}).status_code == 200


def test_dns_rebinding_host_is_refused(client, studio):
    studio.chats.create("private", "m", [{"role": "user", "content": "secret"}])
    for path in ("/api/studio/chats", "/api/studio/settings", "/v1/models", "/"):
        resp = client.get(path, headers={"Host": "evil.example:11435"})
        assert resp.status_code == 400 and "secret" not in resp.text, path
    assert client.put("/api/studio/settings", json={"models_dir": "/tmp/x"},
                      headers={"Host": "evil.example:11435"}).status_code == 400


def test_own_ui_and_plain_clients_still_work(client, studio, pulled):
    own = {"Origin": BASE_URL, "Sec-Fetch-Site": "same-origin"}
    assert client.post("/api/studio/models/pull", json={"name": "org/new-model"}, headers=own).status_code == 200
    assert client.post("/api/studio/chats", json={"title": "t"}).status_code == 200    # no Origin: CLI/SDK
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200  # a link to the UI
    assert client.get("/api/tags", headers={"Host": "192.168.1.20:11435"}).status_code == 200
    for _ in range(50):                                    # the pull runs in its own thread
        if pulled:
            break
        time.sleep(0.02)
    assert pulled == ["org/new-model"]


def test_configured_origins_and_hosts(studio, monkeypatch):
    from fastapi.testclient import TestClient

    from airllm_studio.server import create_app

    monkeypatch.setenv("AIRLLM_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("AIRLLM_ALLOWED_HOSTS", "gpu-box.lan")
    c = TestClient(create_app(studio, keepalive=False, bind_host="studio.internal"), base_url=BASE_URL)
    assert c.get("/api/tags", headers={"Origin": "http://localhost:3000"}).status_code == 200
    assert c.get("/api/tags", headers={"Origin": EVIL}).status_code == 403
    assert c.get("/api/tags", headers={"Host": "gpu-box.lan:11435"}).status_code == 200
    assert c.get("/api/tags", headers={"Host": "studio.internal:11435"}).status_code == 200
    assert c.get("/api/tags", headers={"Host": "other.lan:11435"}).status_code == 400


def test_remote_clients_cannot_import_local_folders(studio, tmp_path):
    from fastapi.testclient import TestClient

    from airllm_studio.server import create_app

    remote = TestClient(create_app(studio, keepalive=False), base_url=BASE_URL, client=("203.0.113.9", 5000))
    resp = remote.post("/api/studio/models/pull", json={"name": str(tmp_path)})
    assert resp.status_code == 400 and "only allowed from this computer" in resp.json()["error"]


# --- model code is opt-in ------------------------------------------------------------------
def _code_model(tmp_path, where="config.json"):
    folder = tmp_path / "code-model"
    folder.mkdir()
    config = {"architectures": ["EvilForCausalLM"], "model_type": "llama", "num_hidden_layers": 1}
    auto_map = {"AutoConfig": "configuration_evil.EvilConfig",
                "AutoTokenizer": ["other/repo--tokenization_evil.EvilTokenizer", None]}
    if where == "config.json":
        config["auto_map"] = auto_map
    else:
        (folder / where).write_text(json.dumps({"auto_map": auto_map}))
    (folder / "config.json").write_text(json.dumps(config))
    (folder / "configuration_evil.py").write_text("raise SystemExit('model code ran')\n")
    (folder / "model.safetensors").write_bytes(b"\0" * 64)
    return folder


@pytest.mark.parametrize("where", ["config.json", "tokenizer_config.json", "preprocessor_config.json",
                                   "processor_config.json"])
def test_remote_code_refs(tmp_path, where):
    refs = remote_code_refs(_code_model(tmp_path, where))
    assert refs == ["configuration_evil.EvilConfig", "other/repo--tokenization_evil.EvilTokenizer"]


def test_select_files_skips_model_code_unless_allowed():
    files = [("config.json", 1), ("configuration_evil.py", 1), ("model.safetensors", 5)]
    assert "configuration_evil.py" not in [n for n, _ in select_files(files)]
    assert "configuration_evil.py" in [n for n, _ in select_files(files, include_code=True)]


def test_code_model_needs_explicit_trust(home, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(store_mod, "split_layers", lambda *a, **k: calls.append(a))
    st = ModelStore(lambda: tmp_path / "models", lambda: None)
    folder = str(_code_model(tmp_path))

    final = list(st.pull(folder).events(timeout=0.1))[-1]
    assert final["phase"] == "error" and "--trust-remote-code" in final["error"]
    m = st.get("local/code-model")
    assert m.status == "error" and m.needs_remote_code and not m.trust_remote_code
    assert calls == []                                     # AirLLM never saw the model

    final = list(st.pull(folder, trust_remote_code=True).events(timeout=0.1))[-1]
    assert final["phase"] == "success", final
    m = st.get("local/code-model")
    assert m.trust_remote_code and not m.needs_remote_code and len(calls) == 1

    final = list(st.pull(folder).events(timeout=0.1))[-1]   # "Retry" keeps the user's choice
    assert final["phase"] == "success" and st.get("local/code-model").trust_remote_code


def test_engine_refuses_untrusted_code_model(home, tmp_path):
    from airllm_studio.config import SettingsStore

    settings = SettingsStore()
    st = ModelStore(lambda: tmp_path / "models", lambda: None)
    folder = _code_model(tmp_path)
    st.save(Manifest(name="org/evil", repo="org/evil", status="ready", snapshot_path=str(folder)))
    with pytest.raises(EngineError, match="trust-remote-code"):
        Engine(st, settings)._load("org/evil")
