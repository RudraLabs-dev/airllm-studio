"""End-to-end test of AirLLM Studio against a real AirLLM model, fully offline.

    airllm-python studio_e2e.py [--airllm CMD] [--model HF_ID]

1. Builds a tiny random Llama model (2 layers, tied embeddings, chat template) in a temp dir,
   unless --model is given (then it pulls that Hugging Face model, which needs network).
2. Starts `airllm serve` on a free port with a throwaway AIRLLM_HOME.
3. Pulls (imports + AirLLM layer split), then exercises the Ollama API (/api/chat, /api/tags),
   the OpenAI API (/v1/chat/completions, streaming and not), the CLI (`airllm list`, `airllm run`)
   and the web UI (GET /).
4. Offline mode also checks projects (instructions + a text file become the chat's context) and
   image input on a tiny random Qwen3.5 vision-language model, the architecture AirLLM streams
   with its vision tower kept resident.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def make_tiny_model(path: Path) -> str:
    import torch
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

    text = ["AirLLM runs large language models on small GPUs by streaming layers from disk.",
            "The quick brown fox jumps over the lazy dog.", "Hello, how are you today?"] * 20
    tok = Tokenizer(models.BPE(unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    tok.train_from_iterator(text, trainers.BpeTrainer(vocab_size=300, special_tokens=["<unk>", "<s>", "</s>"]))
    hf_tok = PreTrainedTokenizerFast(tokenizer_object=tok, bos_token="<s>", eos_token="</s>",
                                     unk_token="<unk>", pad_token="</s>")
    hf_tok.chat_template = ("{% for m in messages %}<s>{{ m['role'] }}: {{ m['content'] }}</s>{% endfor %}"
                            "{% if add_generation_prompt %}<s>assistant: {% endif %}")
    hf_tok.save_pretrained(path)

    torch.manual_seed(0)
    config = LlamaConfig(vocab_size=len(hf_tok), hidden_size=64, intermediate_size=128,
                         num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
                         max_position_embeddings=256, tie_word_embeddings=True,
                         bos_token_id=hf_tok.bos_token_id, eos_token_id=hf_tok.eos_token_id)
    model = LlamaForCausalLM(config).to(torch.bfloat16)
    model.save_pretrained(path, safe_serialization=True)
    return str(path)


def make_tiny_vl_model(path: Path) -> str:
    """Tiny random Qwen3.5 VL (Qwen3_5ForConditionalGeneration) with a processor and chat template."""
    import torch
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import (AutoImageProcessor, AutoVideoProcessor, PreTrainedTokenizerFast,
                              Qwen3_5Config, Qwen3_5ForConditionalGeneration, Qwen3VLProcessor)

    path.mkdir(parents=True, exist_ok=True)
    specials = ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<|vision_start|>", "<|vision_end|>",
                "<|image_pad|>", "<|video_pad|>"]
    tok = Tokenizer(models.BPE(unk_token=None))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok.decoder = decoders.ByteLevel()
    tok.train_from_iterator(["describe the picture please", "a small red square", "hello"] * 40,
                            trainers.BpeTrainer(vocab_size=320, special_tokens=specials,
                                                initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    hf_tok = PreTrainedTokenizerFast(tokenizer_object=tok, eos_token="<|im_end|>", pad_token="<|endoftext|>")
    hf_tok.add_special_tokens({"additional_special_tokens": specials[1:]})
    ids = {t: hf_tok.convert_tokens_to_ids(t) for t in specials}
    template = ("{% for m in messages %}<|im_start|>{{ m['role'] }}\n{% if m['content'] is string %}"
                "{{ m['content'] }}{% else %}{% for c in m['content'] %}{% if c['type'] == 'image' %}"
                "<|vision_start|><|image_pad|><|vision_end|>{% elif c['type'] == 'text' %}{{ c['text'] }}"
                "{% endif %}{% endfor %}{% endif %}<|im_end|>\n{% endfor %}"
                "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")
    hf_tok.chat_template = template
    config = Qwen3_5Config(
        text_config=dict(vocab_size=len(hf_tok), hidden_size=64, intermediate_size=128, num_hidden_layers=2,
                         num_attention_heads=4, num_key_value_heads=2, head_dim=16, max_position_embeddings=512,
                         linear_key_head_dim=16, linear_value_head_dim=16, linear_num_key_heads=2,
                         linear_num_value_heads=4, layer_types=["linear_attention", "full_attention"],
                         eos_token_id=ids["<|im_end|>"], pad_token_id=ids["<|endoftext|>"]),
        vision_config=dict(depth=1, hidden_size=32, intermediate_size=64, num_heads=2, patch_size=16,
                           spatial_merge_size=2, temporal_patch_size=2, out_hidden_size=64,
                           num_position_embeddings=64),
        image_token_id=ids["<|image_pad|>"], video_token_id=ids["<|video_pad|>"],
        vision_start_token_id=ids["<|vision_start|>"], vision_end_token_id=ids["<|vision_end|>"],
        tie_word_embeddings=False)
    config.architectures = ["Qwen3_5ForConditionalGeneration"]
    torch.manual_seed(0)
    Qwen3_5ForConditionalGeneration(config).save_pretrained(path, safe_serialization=True)
    hf_tok.save_pretrained(path)
    (path / "preprocessor_config.json").write_text(json.dumps({
        "image_processor_type": "Qwen2VLImageProcessorFast", "patch_size": 16, "temporal_patch_size": 2,
        "merge_size": 2, "size": {"shortest_edge": 1024, "longest_edge": 4096},
        "image_mean": [0.5, 0.5, 0.5], "image_std": [0.5, 0.5, 0.5]}))
    Qwen3VLProcessor(image_processor=AutoImageProcessor.from_pretrained(path), tokenizer=hf_tok,
                     video_processor=AutoVideoProcessor.from_pretrained(path),
                     chat_template=template).save_pretrained(path)
    return str(path)


def png_base64(width=48, height=32) -> str:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(url: str, path: str, body: dict | None = None, method: str | None = None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def call_json(url: str, path: str, body: dict | None = None, method: str | None = None) -> dict:
    return json.loads(call(url, path, body, method).read())


def upload(url: str, path: str, data: bytes) -> dict:
    req = urllib.request.Request(url + path, data=data, method="POST",
                                 headers={"Content-Type": "application/octet-stream"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def annotate(message: str) -> None:
    """Surface a failure as a GitHub Actions annotation (readable through the checks API)."""
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("AIRLLM_E2E_ANNOTATE"):
        text = message.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title=AirLLM Studio E2E::{text}", flush=True)


def check(cond: bool, what: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + what, flush=True)
    if not cond:
        raise SystemExit(f"FAIL: {what}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--airllm", default="airllm", help="command that runs the airllm CLI")
    ap.add_argument("--model", help="Hugging Face model id to pull instead of the tiny local model")
    args = ap.parse_args()
    # A path to the launcher (may contain spaces), or a command line such as "python -m airllm_studio".
    cli = [args.airllm] if os.path.isfile(args.airllm) else shlex.split(args.airllm, posix=os.name != "nt")

    work = Path(tempfile.mkdtemp(prefix="airllm-e2e-"))
    port = free_port()
    env = {**os.environ, "AIRLLM_HOME": str(work / "home"), "AIRLLM_HOST": f"127.0.0.1:{port}"}
    os.environ.update({k: env[k] for k in ("AIRLLM_HOME", "AIRLLM_HOST")})
    url = f"http://127.0.0.1:{port}"
    model = args.model or make_tiny_model(work / "tiny-llama")
    log = open(work / "server.log", "wb")
    server = subprocess.Popen(cli + ["serve"], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            try:
                call(url, "/api/version", timeout=2)
                break
            except OSError:
                if server.poll() is not None:
                    break
                time.sleep(0.5)
        check(server.poll() is None, "server started")
        print("      version:", json.loads(call(url, "/api/version").read()))

        # pull: Ollama-style NDJSON progress
        events = [json.loads(line) for line in call(url, "/api/pull", {"model": model}) if line.strip()]
        check(events[-1].get("status") == "success", f"pull {model} -> {events[-1]}")
        name = json.loads(call(url, "/api/tags").read())["models"][0]["name"]
        check(bool(name), f"model listed in /api/tags as {name}")

        # Ollama chat, streaming
        lines = [json.loads(line) for line in call(url, "/api/chat", {
            "model": name, "messages": [{"role": "user", "content": "Hello"}],
            "options": {"num_predict": 8, "temperature": 0}}) if line.strip()]
        final = lines[-1]
        text = "".join(item.get("message", {}).get("content", "") for item in lines)
        check(final.get("done") is True and final.get("eval_count", 0) > 0,
              f"/api/chat streamed {final.get('eval_count')} tokens: {text!r}")

        # OpenAI chat, non-streaming
        resp = json.loads(call(url, "/v1/chat/completions", {
            "model": name, "messages": [{"role": "user", "content": "Hi there"}],
            "max_tokens": 6, "temperature": 0}).read())
        check(resp["object"] == "chat.completion" and resp["usage"]["completion_tokens"] > 0,
              f"/v1/chat/completions usage={resp['usage']}")

        # OpenAI chat, streaming SSE
        chunks = [line.decode().strip() for line in call(url, "/v1/chat/completions", {
            "model": name, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 4,
            "stream": True}) if line.strip()]
        check(chunks[-1] == "data: [DONE]" and len(chunks) >= 3, f"/v1 streaming sent {len(chunks)} events")

        # CLI against the running server
        out = subprocess.run(cli + ["list"], env=env, capture_output=True, text=True, timeout=120)
        check(out.returncode == 0 and name in out.stdout, "airllm list shows the model")
        out = subprocess.run(cli + ["run", name, "Say hi", "--max-tokens", "4"], env=env,
                             capture_output=True, text=True, timeout=600)
        check(out.returncode == 0, f"airllm run answered: {out.stdout.strip()!r}")

        if not args.model:
            # Projects: instructions + a text file reach the model as the system prompt
            plain = call_json(url, "/api/chat", {"model": name, "stream": False, "options": {"num_predict": 2},
                                                 "messages": [{"role": "user", "content": "Hello"}]})
            project = call_json(url, "/api/studio/projects", {"name": "E2E", "instructions": "Be brief."})
            upload(url, f"/api/studio/projects/{project['id']}/files?name=notes.md",
                   b"# Notes\nAirLLM streams one layer at a time.\n")
            in_project = call_json(url, "/api/chat", {"model": name, "stream": False, "airllm_project": project["id"],
                                                      "options": {"num_predict": 2},
                                                      "messages": [{"role": "user", "content": "Hello"}]})
            check(in_project.get("done") and in_project["prompt_eval_count"] > plain["prompt_eval_count"] + 10,
                  f"project context reached the model ({plain['prompt_eval_count']} -> "
                  f"{in_project['prompt_eval_count']} prompt tokens)")
            chat = call_json(url, "/api/studio/chats", {"title": "e2e", "project_id": project["id"]})
            check(chat["project_id"] == project["id"], "chat saved inside the project")

            # Images on a vision-language model (and refused for a text-only one)
            vl = make_tiny_vl_model(work / "tiny-vl")
            events = [json.loads(line) for line in call(url, "/api/pull", {"model": vl}) if line.strip()]
            check(events[-1].get("status") == "success", f"pull tiny VL -> {events[-1]}")
            models = {m["name"]: m for m in call_json(url, "/api/studio/models")["models"]}
            vl_name = next(n for n in models if n.endswith("tiny-vl"))
            check(models[vl_name]["capabilities"] == ["completion", "vision"]
                  and models[name]["capabilities"] == ["completion"],
                  f"capabilities: {vl_name}={models[vl_name]['capabilities']} {name}={models[name]['capabilities']}")
            image = png_base64()
            ask = [{"role": "user", "content": "Describe", "images": [image]}]
            seen = call_json(url, "/api/chat", {"model": vl_name, "stream": False, "options": {"num_predict": 3},
                                                "messages": ask})
            check(seen.get("done") and seen["prompt_eval_count"] > 10,
                  f"vision model answered about an image ({seen['prompt_eval_count']} prompt tokens incl. image)")
            try:
                call(url, "/api/chat", {"model": name, "stream": False,
                                        "messages": [{"role": "user", "content": "x", "images": [image]}]})
                refused = False
            except urllib.error.HTTPError as exc:
                refused = exc.code == 400
            check(refused, "text-only model refuses images")

        html = call(url, "/").read().decode()
        check("<title>AirLLM" in html, "web UI served at /")
        status = json.loads(call(url, "/api/studio/status").read())
        print("      device:", status.get("device"), "| engine:", status["engine"]["state"])

        out = subprocess.run(cli + ["stop"], env=env, capture_output=True, text=True, timeout=60)
        server.wait(timeout=30)
        check(server.returncode is not None, "airllm stop shut the server down")
        print("STUDIO E2E PASSED")
        return 0
    except BaseException as exc:
        log.flush()
        tail = (work / "server.log").read_text(errors="replace")[-2500:]
        annotate(f"{type(exc).__name__}: {exc}\n--- server log tail ---\n{tail}")
        raise
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        log.close()
        sys.stdout.write("\n--- server log (tail) ---\n")
        sys.stdout.write((work / "server.log").read_text(errors="replace")[-4000:])


if __name__ == "__main__":
    sys.exit(main())
