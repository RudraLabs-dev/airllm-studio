"""Images/audio only reach models that take them natively; cross-site and rebinding requests are refused."""
import base64
import io
import json
import struct
import wave
import zlib

import pytest

from airllm_studio import store as store_mod
from airllm_studio.media import MediaError, decode_b64, load_wav, parse_openai_content
from airllm_studio.store import Manifest, detect_capabilities

def _png_1px() -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)            # 1x1 RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


PNG_1PX = base64.b64encode(_png_1px()).decode()


def wav_bytes(seconds=0.1, rate=8000, width=2, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate) * channels if width == 2 else b"\x80" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def vision_model(studio):
    studio.store.save(Manifest(name="org/vl-model", repo="org/vl-model", status="ready",
                               capabilities=["completion", "vision"]))
    return "org/vl-model"


# --- capability detection ------------------------------------------------------------------
def write_model(path, config, processor=True):
    path.mkdir(parents=True)
    (path / "config.json").write_text(json.dumps(config))
    if processor:
        (path / "preprocessor_config.json").write_text("{}")
    return path


def test_detect_capabilities(tmp_path):
    vl = write_model(tmp_path / "vl", {"vision_config": {"depth": 2}})
    assert detect_capabilities(vl, {"resident": ["model.visual"]}) == ["completion", "vision"]
    # the checkpoint has a vision tower, but AirLLM would leave it on the meta device
    assert detect_capabilities(vl, {"resident": []}) == ["completion"]
    no_proc = write_model(tmp_path / "np", {"vision_config": {}}, processor=False)
    assert detect_capabilities(no_proc, {"resident": ["model.visual"]}) == ["completion"]
    audio = write_model(tmp_path / "au", {"audio_config": {"d_model": 8}})
    assert detect_capabilities(audio, {"resident": ["model.audio_tower"]}) == ["completion", "audio"]
    assert detect_capabilities(audio, {"resident": ["model.visual"]}) == ["completion"]
    text = write_model(tmp_path / "txt", {"model_type": "llama"})
    assert detect_capabilities(text, {"resident": []}) == ["completion"]
    assert detect_capabilities(tmp_path / "missing", None) == ["completion"]


def test_capabilities_filled_for_old_manifests(studio, client, tmp_path, monkeypatch):
    snap = write_model(tmp_path / "snap", {"vision_config": {}})

    class FakeVL:
        def set_layer_names_dict(self):
            self.layer_names_dict = {"resident": ["model.visual"]}

    monkeypatch.setattr(store_mod, "airllm_class_for", lambda *a, **k: FakeVL)
    studio.store.save(Manifest(name="org/old-vl", status="ready", snapshot_path=str(snap)))
    models = {m["name"]: m for m in client.get("/api/studio/models").json()["models"]}
    assert models["org/old-vl"]["capabilities"] == ["completion", "vision"]
    assert models["org/ready-model"]["capabilities"] == ["completion"]
    assert studio.store.get("org/old-vl").capabilities == ["completion", "vision"]        # persisted
    show = client.post("/api/show", json={"model": "org/old-vl"}).json()
    assert show["capabilities"] == ["completion", "vision"]


# --- media in requests ---------------------------------------------------------------------
def test_images_rejected_for_text_models(client):
    resp = client.post("/api/chat", json={"model": "org/ready-model", "stream": False, "messages": [
        {"role": "user", "content": "what is this?", "images": [PNG_1PX]}]})
    assert resp.status_code == 400 and "does not take images" in resp.json()["detail"]


def test_older_images_are_dropped_when_switching_to_a_text_model(client, studio):
    resp = client.post("/api/chat", json={"model": "org/ready-model", "stream": False, "messages": [
        {"role": "user", "content": "describe", "images": [PNG_1PX]},
        {"role": "assistant", "content": "a red pixel"},
        {"role": "user", "content": "thanks, now a haiku"}]})
    assert resp.status_code == 200
    first = studio.engine.last_messages[0]
    assert "images" not in first and first["content"] == "describe [image omitted]"


def test_images_reach_vision_models(client, studio, vision_model):
    resp = client.post("/api/chat", json={"model": vision_model, "stream": False, "messages": [
        {"role": "user", "content": "what is this?", "images": [PNG_1PX]}]})
    assert resp.status_code == 200
    assert studio.engine.last_messages[-1]["images"] == [base64.b64decode(PNG_1PX)]


def test_openai_content_parts(client, studio, vision_model):
    body = {"model": vision_model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "what is "}, {"type": "text", "text": "this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + PNG_1PX}}]}]}
    resp = client.post("/v1/chat/completions", json=body)
    assert resp.status_code == 200, resp.text
    last = studio.engine.last_messages[-1]
    assert last["content"] == "what is this?" and len(last["images"]) == 1
    remote = {"model": vision_model, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}}]}]}
    err = client.post("/v1/chat/completions", json=remote)
    assert err.status_code == 400 and "remote URLs" in err.json()["error"]["message"]
    audio = {"model": vision_model, "messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav_bytes()).decode(), "format": "wav"}}]}]}
    assert "does not take audio" in client.post("/v1/chat/completions", json=audio).json()["error"]["message"]


def test_media_helpers():
    assert decode_b64("data:image/png;base64," + PNG_1PX, "image", 10_000)[:4] == b"\x89PNG"
    with pytest.raises(MediaError):
        decode_b64("not base64!!", "image", 10_000)
    with pytest.raises(MediaError, match="larger"):
        decode_b64(base64.b64encode(b"x" * 5000).decode(), "image", 1000)
    text, media = parse_openai_content([{"type": "text", "text": "hi"}])
    assert text == "hi" and media == {}
    with pytest.raises(MediaError, match="WAV"):
        parse_openai_content([{"type": "input_audio", "input_audio": {"data": "AAAA", "format": "mp3"}}])


def test_load_wav_resamples_and_downmixes():
    pytest.importorskip("scipy")
    samples = load_wav(wav_bytes(seconds=0.5, rate=8000, channels=2), 16000)
    assert samples.dtype.name == "float32" and abs(len(samples) - 8000) <= 2
    assert abs(float(samples[100]) - 16 / 32768) < 1e-3
    with pytest.raises(MediaError):
        load_wav(b"RIFF....not a wav", 16000)


def test_load_image():
    pytest.importorskip("PIL")
    from airllm_studio.media import load_image

    img = load_image(base64.b64decode(PNG_1PX))
    assert img.size == (1, 1) and img.mode == "RGB"
    with pytest.raises(MediaError):
        load_image(b"not an image")


# --- request guard (security.py, tested in test_security.py) covers the new endpoints -------
def test_project_endpoints_refuse_cross_site_writes(client):
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/studio/projects", json={"name": "x"}, headers=evil).status_code == 403
    p = client.post("/api/studio/projects", json={"name": "y"}).json()           # CLI/SDKs: no Origin
    upload = client.post(f"/api/studio/projects/{p['id']}/files?name=a.txt", content=b"hi", headers=evil)
    assert upload.status_code == 403
