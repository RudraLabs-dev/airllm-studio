"""Run the Studio UI against a fake, slow engine: no torch, GPU or model needed.

    python studio/tools/dev_server.py [port]

Useful for working on the web UI; it seeds a few models (one mid-download) in a temp AIRLLM_HOME.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))
os.environ.setdefault("AIRLLM_HOME", tempfile.mkdtemp(prefix="airllm-dev-"))

import uvicorn  # noqa: E402
from conftest import FakeEngine  # noqa: E402

from airllm_studio.chats import ChatStore  # noqa: E402
from airllm_studio.config import SettingsStore, data_dir  # noqa: E402
from airllm_studio.server import Studio, create_app  # noqa: E402
from airllm_studio.store import Manifest, ModelStore, PullJob  # noqa: E402


class SlowFake(FakeEngine):
    layers = 40
    delay = 0.35
    reply = ("AirLLM keeps only **one layer** in GPU memory at a time, so the memory you need depends on "
             "the size of a layer rather than the whole model.\n\n"
             "1. Each layer is read from disk.\n2. It runs on the GPU.\n3. It is freed before the next one.\n\n"
             "```python\nfrom airllm import AutoModel\nmodel = AutoModel.from_pretrained(\"Qwen/Qwen3-8B\")\n```")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11435
    settings = SettingsStore()
    store = ModelStore(settings.models_dir, settings.hf_token)
    for name, params, size, ctx, caps in [
            ("Qwen/Qwen3-8B", "8.2B", 16_400_000_000, 40960, ["completion"]),
            ("Qwen/Qwen3.8-27B", "27B", 55_000_000_000, 262144, ["completion", "vision"]),
            ("meta-llama/Llama-3.3-70B-Instruct", "70B", 141_000_000_000, 131072, ["completion"])]:
        store.save(Manifest(name=name, repo=name, status="ready", parameter_size=params, capabilities=caps,
                            size_on_disk=size, context_length=ctx, model_type="llama"))
    store.save(Manifest(name="Qwen/Qwen3-32B", repo="Qwen/Qwen3-32B", status="downloading"))
    job = PullJob("Qwen/Qwen3-32B")
    job.update(phase="downloading", message="Downloading", total=65_500_000_000, completed=23_100_000_000)
    store.jobs[job.name] = job
    chats = ChatStore(data_dir() / "chats.db")
    chats.create("How does layer streaming work?", "Qwen/Qwen3-8B", [
        {"role": "user", "content": "How does layer streaming work?"},
        {"role": "assistant", "content": SlowFake.reply, "stats": {"tokens": 64, "tps": 0.42, "seconds": 152}}])
    chats.create("Draft a release note", "Qwen/Qwen3-8B", [])
    project = chats.create_project("AirLLM docs", "You help write AirLLM documentation. Keep answers short.",
                                   "Qwen/Qwen3-8B")
    chats.add_file(project["id"], "README.md", b"# AirLLM\nRuns 70B models on a 4GB GPU by streaming layers.\n")
    chats.add_file(project["id"], "style-guide.md", b"Use British English. Prefer short sentences.\n" * 40)
    chats.create("Outline the install guide", "Qwen/Qwen3-8B", [
        {"role": "user", "content": "Outline the install guide"},
        {"role": "assistant", "content": "1. Download the package\n2. Install it\n3. Pull a model",
         "stats": {"tokens": 18, "tps": 0.5, "seconds": 36}}], project_id=project["id"])
    studio = Studio(settings=settings, store=store, engine=SlowFake(store, settings), chats=chats)
    print(f"dev UI on http://127.0.0.1:{port}  (home {os.environ['AIRLLM_HOME']})", flush=True)
    time.sleep(0)
    uvicorn.run(create_app(studio, keepalive=False), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
