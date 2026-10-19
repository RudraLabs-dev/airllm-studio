"""Test fixtures: a fake engine so the API can be tested without torch, AirLLM or a model."""
from __future__ import annotations

import time

import pytest

from airllm_studio.config import SettingsStore
from airllm_studio.engine import Engine
from airllm_studio.store import Manifest, ModelStore


BASE_URL = "http://127.0.0.1:11435"


class FakeEngine(Engine):
    """Behaves like Engine but 'generates' a fixed reply, reporting layer progress on the way."""

    reply = "Hello from **AirLLM**. Here is some code:\n\n```python\nprint('hi')\n```\nDone."
    layers = 12
    delay = 0.0

    def hardware(self) -> dict:
        self._torch_info = {"torch": "test", "cuda": None, "gpus": [], "bitsandbytes": False}
        return self._torch_info

    def _load(self, name: str) -> None:
        if self.model_name == name:
            return
        self._manifest(name)
        self.state = "loading"
        self.model = object()
        self.model_name, self.device, self.loaded_at = name, "cpu", time.time()
        self.layer_total = self.layers
        self.state = "ready"

    def _unload(self) -> None:
        self.model, self.model_name, self.device, self.state = None, None, None, "idle"

    def _generate(self, messages, options, cancel, raw_prompt, started, load_duration):
        self.last_messages = messages
        words = self.reply.split(" ")[: options.max_new_tokens]
        count = 0
        for i, word in enumerate(words):
            for layer in range(1, self.layers + 1, 4):
                if self.delay:
                    time.sleep(self.delay / 3)
                yield {"type": "progress", "layer": layer, "layers": self.layers, "tokens": i}
            if cancel.is_set():
                break
            count += 1
            yield {"type": "token", "text": word if i == 0 else " " + word}
        reason = "cancelled" if cancel.is_set() else ("length" if count >= options.max_new_tokens else "stop")
        stats = {"prompt_tokens": sum(len(m["content"].split()) for m in messages),
                 "completion_tokens": count, "load_duration": load_duration,
                 "prompt_duration": 0.01, "eval_duration": 0.1, "total_duration": time.time() - started,
                 "tokens_per_second": count / 0.1}
        self.last_stats = stats
        yield {"type": "done", "done_reason": reason, "stats": stats}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRLLM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AIRLLM_MODELS", raising=False)
    monkeypatch.delenv("AIRLLM_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return tmp_path / "home"


@pytest.fixture
def studio(home):
    from airllm_studio.chats import ChatStore
    from airllm_studio.server import Studio

    settings = SettingsStore()
    store = ModelStore(settings.models_dir, settings.hf_token)
    engine = FakeEngine(store, settings)
    st = Studio(settings=settings, store=store, engine=engine, chats=ChatStore(home / "chats.db"))
    store.save(Manifest(name="org/ready-model", repo="org/ready-model", status="ready",
                        parameter_size="7.2B", model_type="llama", size_on_disk=123))
    store.save(Manifest(name="org/broken-model", repo="org/broken-model", status="error", error="boom"))
    return st


@pytest.fixture
def client(studio):
    from fastapi.testclient import TestClient

    from airllm_studio.server import create_app

    # The server only answers to loopback / IP / allowlisted Host names (DNS-rebinding guard),
    # so talk to it the way the desktop app does.
    with TestClient(create_app(studio, keepalive=False), base_url=BASE_URL) as c:
        yield c
