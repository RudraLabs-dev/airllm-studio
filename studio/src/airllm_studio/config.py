"""Paths, server address and persisted user settings.

Environment variables (all optional):
  AIRLLM_HOME     data directory (settings, chats, logs, default models dir)  default: ~/.airllm
  AIRLLM_MODELS   models directory, overrides the setting                       default: $AIRLLM_HOME/models
  AIRLLM_HOST     address to serve on / talk to, "host", "host:port" or URL      default: 127.0.0.1:11435
  AIRLLM_API_KEY  if set, non-local clients must send "Authorization: Bearer <key>"
  AIRLLM_ORIGINS  extra comma-separated browser origins allowed to call the API (see security.py)
  AIRLLM_ALLOWED_HOSTS  extra comma-separated host names the server may be reached by
  HF_TOKEN        Hugging Face token (the setting in the app takes precedence)
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PORT = 11435
DEFAULT_HOST = "127.0.0.1"


def apply_cuda_overlay() -> str | None:
    """Put the CUDA PyTorch overlay from `airllm-enable-cuda` ahead of the bundled CPU torch.

    The shell launchers already do this through PYTHONPATH; this covers entry points that start
    the interpreter directly (the Windows Start-menu shortcut runs pythonw.exe -m airllm_studio).
    """
    import sys

    if os.environ.get("AIRLLM_FORCE_CPU"):
        return None
    candidates = [Path(sys.executable).resolve().parent.parent / "cuda-site",   # Windows: <app>\cuda-site
                  Path("/var/lib/airllm/cuda-site")]                             # Linux packages
    for path in candidates:
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
            return str(path)
    return None


def data_dir() -> Path:
    env = os.environ.get("AIRLLM_HOME")
    path = Path(env).expanduser() if env else Path.home() / ".airllm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_host(value: str | None = None) -> tuple[str, int]:
    """Parse AIRLLM_HOST-style values: "", "0.0.0.0", ":8080", "host:port", "http://host:port"."""
    value = (value if value is not None else os.environ.get("AIRLLM_HOST", "")).strip()
    if not value:
        return DEFAULT_HOST, DEFAULT_PORT
    if "://" not in value:
        value = "http://" + value
    parsed = urlparse(value)
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or DEFAULT_PORT
    return host, port


def base_url(host: str | None = None, port: int | None = None) -> str:
    h, p = parse_host()
    host, port = host or h, port or p
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"   # a wildcard bind is reachable locally via loopback
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


@dataclass
class GenerationDefaults:
    max_new_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    system_prompt: str = ""
    context_length: int = 4096


@dataclass
class Settings:
    models_dir: str = ""                 # empty = $AIRLLM_HOME/models
    hf_token: str = ""                   # write-only through the API
    device: str = "auto"                 # auto | cpu | cuda:0 | cuda:1 ...
    compression: str = "none"            # none | 4bit | 8bit (needs bitsandbytes)
    delete_original: bool = False        # free disk after preparing multi-shard models
    keep_alive_minutes: int = 30         # unload an idle model after this long (0 = never)
    defaults: GenerationDefaults = field(default_factory=GenerationDefaults)

    @classmethod
    def from_dict(cls, raw: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in (raw or {}).items() if k in known and k != "defaults"}
        gen_known = {f.name for f in fields(GenerationDefaults)}
        gen = {k: v for k, v in (raw or {}).get("defaults", {}).items() if k in gen_known}
        return cls(**values, defaults=GenerationDefaults(**gen))

    def to_dict(self, redact: bool = False) -> dict:
        data = asdict(self)
        if redact:
            data["hf_token_set"] = bool(self.hf_token or os.environ.get("HF_TOKEN"))
            data["hf_token"] = ""
        return data


class SettingsStore:
    """settings.json in the data dir, written atomically with owner-only permissions."""

    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "settings.json"
        self._lock = threading.Lock()
        self._settings = self._read()

    def _read(self) -> Settings:
        try:
            return Settings.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return Settings()
        except (ValueError, TypeError):
            # A corrupt file must not stop the server; keep a copy for the user and start fresh.
            self.path.replace(self.path.with_suffix(".json.bad"))
            return Settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    def update(self, patch: dict) -> Settings:
        with self._lock:
            current = self._settings.to_dict()
            for key, value in (patch or {}).items():
                if key == "defaults" and isinstance(value, dict):
                    current["defaults"].update(value)
                elif key == "hf_token" and value is None:
                    continue
                elif key in current:
                    current[key] = value
            new = Settings.from_dict(current)
            if new.compression not in ("none", "4bit", "8bit"):
                raise ValueError("compression must be none, 4bit or 8bit")
            if new.device != "auto" and not (new.device == "cpu" or new.device.startswith("cuda")):
                raise ValueError("device must be auto, cpu or cuda[:N]")
            self._write(new)
            self._settings = new
            return new

    def _write(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(settings.to_dict(), fh, indent=2)
            os.chmod(tmp, 0o600)      # holds the HF token
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # --- derived values -------------------------------------------------------------------
    def models_dir(self) -> Path:
        env = os.environ.get("AIRLLM_MODELS")
        raw = env or self._settings.models_dir
        path = Path(raw).expanduser() if raw else data_dir() / "models"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def hf_token(self) -> str | None:
        return self._settings.hf_token or os.environ.get("HF_TOKEN") or None
