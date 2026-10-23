"""Images and audio sent with chat messages: decoding, limits, and conversion for model processors.

Media is only passed to models that take it natively (see ``store.detect_capabilities``); this
module never converts one kind of input into another (no OCR, no speech-to-text).
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import wave

MAX_IMAGE_BYTES = 20_000_000
MAX_AUDIO_BYTES = 25_000_000
MAX_AUDIO_SECONDS = 300
MAX_ITEMS_PER_MESSAGE = 8
_DATA_URL = re.compile(r"^data:([\w.+-]+/[\w.+-]+)?(;[\w=.+-]+)*;base64,", re.I)


class MediaError(ValueError):
    """Bad or unsupported media; the message is shown to the user."""


def decode_b64(value, what: str, limit: int) -> bytes:
    """Accepts plain base64 or a data: URL (what browsers and the OpenAI API send)."""
    if not isinstance(value, str) or not value:
        raise MediaError(f"{what} must be a base64 string or a data: URL")
    if value.startswith(("http://", "https://")):
        raise MediaError(f"{what}: remote URLs are not fetched; send the data itself (base64 or a data: URL)")
    value = _DATA_URL.sub("", value.strip(), count=1)
    if len(value) * 3 // 4 > limit:
        raise MediaError(f"{what} is larger than {limit // 1_000_000} MB")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise MediaError(f"{what} is not valid base64") from None


def load_image(data: bytes):
    """bytes -> RGB PIL image. Raises MediaError for anything Pillow cannot read."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ships with the packages
        raise MediaError("image support needs the Pillow package") from None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types
        raise MediaError(f"could not read the image ({type(exc).__name__})") from None
    return img.convert("RGB")


def load_wav(data: bytes, sampling_rate: int):
    """WAV (PCM 8/16/24/32-bit, any rate, mono or stereo) -> mono float32 numpy array at
    ``sampling_rate``. The Studio UI records straight to 16 kHz mono WAV."""
    import numpy as np

    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as exc:
        raise MediaError(f"audio must be a PCM WAV file ({exc})") from None
    if rate <= 0 or not frames:
        raise MediaError("the audio clip is empty")
    if len(frames) / (rate * channels * width) > MAX_AUDIO_SECONDS:
        raise MediaError(f"audio clips are limited to {MAX_AUDIO_SECONDS // 60} minutes")
    if width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        ints = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8)
                | (raw[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        samples = ints.astype(np.float32) / float(1 << 23)
    elif width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / float(1 << 31)
    else:
        raise MediaError(f"unsupported WAV sample width: {width * 8} bits")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != sampling_rate:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(rate, sampling_rate)
        samples = resample_poly(samples, sampling_rate // g, rate // g).astype(np.float32)
    return samples


def parse_ollama_media(message: dict) -> dict:
    """Ollama messages carry ``images`` (base64 list); Studio adds ``audio`` the same way."""
    out = {}
    for key, what, limit in (("images", "image", MAX_IMAGE_BYTES), ("audio", "audio", MAX_AUDIO_BYTES)):
        items = message.get(key) or []
        if not isinstance(items, list):
            raise MediaError(f"{key} must be a list")
        if len(items) > MAX_ITEMS_PER_MESSAGE:
            raise MediaError(f"at most {MAX_ITEMS_PER_MESSAGE} {key} per message")
        if items:
            out[key] = [decode_b64(item, what, limit) for item in items]
    return out


def parse_openai_content(content) -> tuple[str, dict]:
    """OpenAI content parts -> (text, media). Supports text, image_url (data URLs) and input_audio (wav)."""
    if not isinstance(content, list):
        return ("" if content is None else str(content)), {}
    text, images, audio = [], [], []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in ("text", "input_text", None):
            text.append(str(part.get("text", "")))
        elif kind == "image_url":
            url = part.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            images.append(decode_b64(url, "image", MAX_IMAGE_BYTES))
        elif kind == "input_audio":
            spec = part.get("input_audio") or {}
            if str(spec.get("format", "wav")).lower() != "wav":
                raise MediaError("only WAV audio is supported (input_audio.format = 'wav')")
            audio.append(decode_b64(spec.get("data"), "audio", MAX_AUDIO_BYTES))
    if len(images) > MAX_ITEMS_PER_MESSAGE or len(audio) > MAX_ITEMS_PER_MESSAGE:
        raise MediaError(f"at most {MAX_ITEMS_PER_MESSAGE} images or audio clips per message")
    media = {}
    if images:
        media["images"] = images
    if audio:
        media["audio"] = audio
    return "".join(text), media
