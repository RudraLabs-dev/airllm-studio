"""Local model library: pulling from Hugging Face (or importing a folder), preparing AirLLM's
per-layer shards, and keeping a manifest per model.

Layout under the models dir:
    hub/                          Hugging Face cache (cache_dir for every download)
    layers/<slug>/splitted_model  AirLLM per-layer shards (".4bit"/".8bit" suffix when compressed)
    manifests/<slug>.json         one manifest per model
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger("airllm_studio.store")

WEIGHT_SUFFIXES = (".safetensors", ".bin")
SIDECAR_FILES = {
    "config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json", "added_tokens.json", "vocab.json", "vocab.txt", "merges.txt",
    "tokenizer.model", "chat_template.json", "chat_template.jinja", "preprocessor_config.json",
    "processor_config.json", "video_preprocessor_config.json",
}
# Image/audio processors; like config.json they may name custom code in an auto_map.
PROCESSOR_FILES = ("preprocessor_config.json", "processor_config.json", "video_preprocessor_config.json")
SIDECAR_SUFFIXES = (".py", ".tiktoken", ".model", ".jinja")
DTYPE_BYTES = {"float32": 4, "float16": 2, "bfloat16": 2, "float8_e4m3fn": 1, "int8": 1, "uint8": 1}


class StoreError(Exception):
    """A problem worth showing to the user as-is."""


class RemoteCodeRequired(StoreError):
    """The model ships Python code (config auto_map) and the user has not allowed running it."""


def remote_code_refs(folder: Path) -> list[str]:
    """Classes a model wants loaded from its own code: the auto_map entries of its config.json,
    tokenizer_config.json and processor configs. transformers imports (= runs) these when
    trust_remote_code is on, which AirLLM always passes; an entry may even point at code in another
    Hub repo ("org/repo--mod.Cls")."""
    refs: set[str] = set()
    for name in ("config.json", "tokenizer_config.json", *PROCESSOR_FILES):
        try:
            data = json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        auto_map = data.get("auto_map") if isinstance(data, dict) else None
        if isinstance(auto_map, dict):
            for value in auto_map.values():
                values = value if isinstance(value, (list, tuple)) else [value]
                refs.update(str(v) for v in values if v)
    return sorted(refs)


def check_remote_code(folder: Path, name: str, trusted: bool) -> None:
    refs = remote_code_refs(folder)
    if refs and not trusted:
        raise RemoteCodeRequired(
            f"This model ships its own Python code ({', '.join(refs[:3])}), which AirLLM Studio only runs "
            f"if you allow it. Only do that for publishers you trust: 'Allow custom code' in the app, or "
            f"airllm pull {name} --trust-remote-code")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    return name.strip().replace("/", "--").replace("\\", "--").replace(":", "-")


@dataclass
class Manifest:
    name: str
    source: str = "hf"                  # hf | local
    repo: str = ""
    revision: str = ""
    snapshot_path: str = ""
    layers_path: str = ""
    compression: str = "none"
    status: str = "pending"             # pending | downloading | preparing | ready | error
    error: str = ""
    download_size: int = 0
    size_on_disk: int = 0
    architecture: str = ""
    model_type: str = ""
    parameter_size: str = ""
    context_length: int = 0
    dtype: str = ""
    original_deleted: bool = False
    trust_remote_code: bool = False     # the user allowed this model's own Python code to run
    needs_remote_code: bool = False     # the last pull stopped because the model ships code
    # What the model takes as input, as AirLLM can run it: "completion" (text), "vision" (images),
    # "audio". Empty = not detected yet (manifests written by Studio 1.0).
    capabilities: list = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    modified_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# Pull jobs
# ---------------------------------------------------------------------------------------------
class PullJob:
    """One pull, running in its own thread. Observers get every progress event through a queue."""

    def __init__(self, name: str):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.phase = "queued"           # queued | resolving | downloading | preparing | success | error | cancelled
        self.message = "Queued"
        self.total = 0
        self.completed = 0
        self.layers_total = 0
        self.layers_done = 0
        self.error = ""
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.cancel_event = threading.Event()
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    @property
    def done(self) -> bool:
        return self.phase in ("success", "error", "cancelled")

    def state(self) -> dict:
        return {
            "id": self.id, "name": self.name, "phase": self.phase, "message": self.message,
            "total": self.total, "completed": self.completed,
            "layers_total": self.layers_total, "layers_done": self.layers_done,
            "error": self.error, "done": self.done,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }

    def update(self, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self, key, value)
            if self.done and self.finished_at is None:
                self.finished_at = time.time()
            event = self.state()
            for q in self._subscribers:
                q.put(event)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
            q.put(self.state())
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def events(self, timeout: float = 1.0) -> Iterator[dict]:
        """Blocking iterator over progress events until the job finishes."""
        q = self.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=timeout)
                except queue.Empty:
                    continue
                yield event
                if event["done"]:
                    return
        finally:
            self.unsubscribe(q)

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise _Cancelled()


class _Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------------------------
class ModelStore:
    def __init__(self, models_dir: Callable[[], Path], hf_token: Callable[[], str | None],
                 compression: Callable[[], str] = lambda: "none",
                 delete_original: Callable[[], bool] = lambda: False):
        self._models_dir = models_dir
        self._hf_token = hf_token
        self._compression = compression
        self._delete_original = delete_original
        self._lock = threading.RLock()
        self.jobs: dict[str, PullJob] = {}
        self._recover_interrupted()

    # --- paths ---------------------------------------------------------------------------
    @property
    def root(self) -> Path:
        return self._models_dir()

    def _dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def manifest_path(self, name: str) -> Path:
        return self._dir("manifests") / f"{slugify(name)}.json"

    # --- manifests -----------------------------------------------------------------------
    def list(self) -> list[Manifest]:
        out = []
        for path in sorted(self._dir("manifests").glob("*.json")):
            try:
                out.append(Manifest(**json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, TypeError) as exc:
                log.warning("skipping unreadable manifest %s: %s", path, exc)
        return sorted(out, key=lambda m: m.modified_at, reverse=True)

    def get(self, name: str) -> Manifest | None:
        path = self.manifest_path(name)
        if not path.exists():
            # Accept a case-insensitive match, e.g. "qwen/qwen3-8b".
            for m in self.list():
                if m.name.lower() == name.lower():
                    return m
            return None
        return Manifest(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, manifest: Manifest) -> None:
        manifest.modified_at = now_iso()
        path = self.manifest_path(manifest.name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def ensure_capabilities(self, manifest: Manifest) -> Manifest:
        """Fill in capabilities for models pulled before they were tracked (Studio 1.0)."""
        if manifest.capabilities or manifest.status != "ready":
            return manifest
        snapshot = Path(manifest.snapshot_path) if manifest.snapshot_path else None
        try:
            if snapshot is None or not (snapshot / "config.json").exists():
                manifest.capabilities = ["completion"]
                self.save(manifest)
                return manifest
            manifest.capabilities = capabilities_for(snapshot, self._hf_token())
        except Exception as exc:  # noqa: BLE001 - fall back to text only, never fail a listing
            log.warning("capability detection failed for %s: %s", manifest.name, exc)
            manifest.capabilities = ["completion"]
        self.save(manifest)
        return manifest

    def _recover_interrupted(self) -> None:
        """Pulls cut off by a restart are marked as errors so the user can resume them."""
        try:
            for m in self.list():
                if m.status in ("pending", "downloading", "preparing"):
                    m.status, m.error = "error", "Interrupted. Pull again to resume."
                    self.save(m)
        except OSError:
            pass

    # --- pull ----------------------------------------------------------------------------
    def pull(self, name: str, trust_remote_code: bool = False, allow_local: bool = True) -> PullJob:
        """Start (or join) a pull. trust_remote_code: let a model that ships Python code run it.
        allow_local: accept a folder on this computer as the source (False for remote API callers)."""
        name = name.strip()
        if not name:
            raise StoreError("model name is empty")
        looks_local = name.startswith(("/", "~", ".", "\\")) or (len(name) > 1 and name[1] == ":")
        if not allow_local and looks_local:
            raise StoreError("Importing a model folder is only allowed from this computer.")
        local = Path(name).expanduser()
        is_local = allow_local and local.is_dir()
        display = f"local/{local.resolve().name}" if is_local else name
        if not is_local and name.count("/") != 1:
            raise StoreError("Use a Hugging Face repo id like 'Qwen/Qwen3-8B', or a local model folder.")
        previous = self.get(display)
        trusted = bool(trust_remote_code or (previous and previous.trust_remote_code))
        with self._lock:
            existing = self.jobs.get(display)
            if existing and not existing.done:
                return existing
            job = PullJob(display)
            self.jobs[display] = job
        target = self._run_local_import if is_local else self._run_hf_pull
        arg = local.resolve() if is_local else name
        threading.Thread(target=self._run_job, args=(job, target, arg, trusted), name=f"pull-{display}",
                         daemon=True).start()
        return job

    def cancel(self, name: str) -> bool:
        job = self.jobs.get(name)
        if job and not job.done:
            job.cancel_event.set()
            return True
        return False

    def _run_job(self, job: PullJob, target, arg, trusted: bool = False) -> None:
        manifest = self.get(job.name) or Manifest(name=job.name)
        manifest.trust_remote_code, manifest.needs_remote_code = trusted, False
        try:
            target(job, manifest, arg)
            manifest.status, manifest.error = "ready", ""
            manifest.size_on_disk = self.disk_usage(manifest)
            self.save(manifest)
            job.update(phase="success", message="Ready", completed=job.total)
        except RemoteCodeRequired as exc:
            manifest.status, manifest.error, manifest.needs_remote_code = "error", str(exc), True
            self.save(manifest)
            job.update(phase="error", message=str(exc), error=str(exc))
        except _Cancelled:
            manifest.status, manifest.error = "error", "Cancelled. Pull again to resume."
            self.save(manifest)
            job.update(phase="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - every failure must reach the user
            log.exception("pull of %s failed", job.name)
            msg = friendly_error(exc)
            manifest.status, manifest.error = "error", msg
            self.save(manifest)
            job.update(phase="error", message=msg, error=msg)

    def _run_hf_pull(self, job: PullJob, manifest: Manifest, repo: str) -> None:
        from huggingface_hub import HfApi, hf_hub_download

        token = self._hf_token()
        hub = self._dir("hub")
        job.update(phase="resolving", message="Looking up model on Hugging Face")
        info = HfApi(token=token).model_info(repo, files_metadata=True, token=token)
        files = select_files([(s.rfilename, s.size or 0) for s in info.siblings or []],
                             include_code=manifest.trust_remote_code)
        manifest.source, manifest.repo, manifest.revision = "hf", info.id, info.sha or ""
        manifest.name = job.name
        manifest.status, manifest.compression = "downloading", self._compression()
        manifest.download_size = sum(size for _, size in files)
        self.save(manifest)

        total = manifest.download_size
        job.update(phase="downloading", message="Downloading", total=total, completed=0)
        repo_cache = hub / f"models--{info.id.replace('/', '--')}"
        done_bytes = 0
        snapshot: Path | None = None
        for filename, size in files:
            job.check_cancelled()
            if snapshot is not None and filename.endswith(WEIGHT_SUFFIXES):
                # Config files come first: refuse a code-shipping model before the big download.
                check_remote_code(snapshot, job.name, manifest.trust_remote_code)
            job.update(message=f"Downloading {filename}")
            stop = threading.Event()
            watcher = threading.Thread(target=self._watch_partial, daemon=True,
                                       args=(job, repo_cache / "blobs", done_bytes, size, stop))
            watcher.start()
            try:
                path = hf_hub_download(info.id, filename, revision=info.sha, cache_dir=str(hub),
                                       token=token, **_progress_kwargs(job, done_bytes, size))
            finally:
                stop.set()
                watcher.join()
            snapshot = Path(path).parent
            done_bytes += size
            job.update(completed=done_bytes)
        if snapshot is None:
            raise StoreError("Nothing to download for this model.")
        manifest.snapshot_path = str(snapshot)
        self._prepare(job, manifest)

    def _run_local_import(self, job: PullJob, manifest: Manifest, folder: Path) -> None:
        job.update(phase="resolving", message=f"Checking {folder}")
        if not (folder / "config.json").exists():
            raise StoreError(f"{folder} has no config.json; point to a Hugging Face model folder.")
        names = [p.name for p in folder.iterdir() if p.is_file()]
        if not any(n.endswith(WEIGHT_SUFFIXES) for n in names):
            raise StoreError(f"{folder} has no .safetensors or .bin weights.")
        manifest.source, manifest.repo, manifest.snapshot_path = "local", str(folder), str(folder)
        manifest.compression = self._compression()
        self._prepare(job, manifest)

    def _watch_partial(self, job: PullJob, blobs: Path, base: int, size: int, stop: threading.Event):
        while not stop.wait(0.5):
            partial = 0
            try:
                for p in blobs.glob("*.incomplete"):
                    partial += p.stat().st_size
            except OSError:
                pass
            job.update(completed=max(job.completed, base + min(partial, size)))

    # --- prepare (AirLLM layer split) ------------------------------------------------------
    def _prepare(self, job: PullJob, manifest: Manifest) -> None:
        job.check_cancelled()
        snapshot = Path(manifest.snapshot_path)
        # AirLLM's layer split loads the config with trust_remote_code=True: gate it here, for
        # Hugging Face pulls and local folders alike.
        check_remote_code(snapshot, manifest.name, manifest.trust_remote_code)
        fill_details(manifest, snapshot)
        manifest.status = "preparing"
        manifest.layers_path = str(self._dir("layers") / slugify(manifest.name))
        self.save(manifest)

        expected = int(_config(snapshot).get("num_hidden_layers") or 0) + 3
        job.update(phase="preparing", message="Preparing layers for AirLLM (one-time)",
                   layers_total=expected, layers_done=0)
        split_dir = Path(manifest.layers_path) / split_dir_name(manifest.compression)
        try:
            manifest.capabilities = capabilities_for(snapshot, self._hf_token())
        except Exception as exc:  # noqa: BLE001 - the split below reports real problems
            log.warning("capability detection failed for %s: %s", manifest.name, exc)
            manifest.capabilities = ["completion"]
        stop = threading.Event()

        def watch():
            while not stop.wait(1.0):
                done = len(list(split_dir.glob("*.done"))) if split_dir.exists() else 0
                job.update(layers_done=min(done, max(expected - 1, 0)))

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            split_layers(snapshot, Path(manifest.layers_path), manifest.compression,
                         repo=manifest.repo if manifest.source == "hf" else None,
                         token=self._hf_token())
        finally:
            stop.set()
            watcher.join()
        job.update(layers_done=expected)

        if self._delete_original() and manifest.source == "hf":
            manifest.original_deleted = delete_original_weights(snapshot)

    # --- delete / usage ------------------------------------------------------------------
    def delete(self, name: str) -> Manifest:
        manifest = self.get(name)
        if manifest is None:
            raise KeyError(name)
        self.cancel(manifest.name)
        if manifest.layers_path:
            shutil.rmtree(manifest.layers_path, ignore_errors=True)
        if manifest.source == "hf" and manifest.repo:
            shutil.rmtree(self.root / "hub" / f"models--{manifest.repo.replace('/', '--')}",
                          ignore_errors=True)
        self.manifest_path(manifest.name).unlink(missing_ok=True)
        self.jobs.pop(manifest.name, None)
        return manifest

    def disk_usage(self, manifest: Manifest) -> int:
        roots = []
        if manifest.layers_path:
            roots.append(Path(manifest.layers_path))
        if manifest.source == "hf" and manifest.repo:
            roots.append(self.root / "hub" / f"models--{manifest.repo.replace('/', '--')}")
        seen, total = set(), 0
        for root in roots:
            if not root.exists():
                continue
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    try:
                        st = os.stat(os.path.join(dirpath, fn))   # follows symlinks into blobs
                    except OSError:
                        continue
                    key = (st.st_dev, st.st_ino)                   # hard links counted once
                    if key not in seen:
                        seen.add(key)
                        total += st.st_size
        return total


# ---------------------------------------------------------------------------------------------
# Helpers (module level so tests can exercise them directly)
# ---------------------------------------------------------------------------------------------
def select_files(files: list[tuple[str, int]], include_code: bool = False) -> list[tuple[str, int]]:
    """Pick what AirLLM needs from a repo listing: top-level config/tokenizer files plus one weight
    format (safetensors preferred). Sub-folders (original/, onnx/, gguf/, ...) are skipped, and so
    is the model's own Python code (*.py) unless the user allowed running it."""
    top = [(n, s) for n, s in files if "/" not in n]
    safetensors = [(n, s) for n, s in top if n.endswith(".safetensors")
                   or n == "model.safetensors.index.json"]
    torch_bins = [(n, s) for n, s in top if (n.endswith(".bin") and n != "training_args.bin")
                  or n == "pytorch_model.bin.index.json"]
    weights = safetensors if any(n.endswith(".safetensors") for n, _ in safetensors) else torch_bins
    if not any(n.endswith(WEIGHT_SUFFIXES) for n, _ in weights):
        if any(n.lower().endswith(".gguf") for n, _ in files):
            raise StoreError("This repo only has GGUF files. AirLLM needs the original Hugging Face "
                             "checkpoint (safetensors), e.g. the non-GGUF repo of the same model.")
        raise StoreError("No .safetensors or .bin weights found in this repo.")
    sidecars = [(n, s) for n, s in top if (n in SIDECAR_FILES or n.endswith(SIDECAR_SUFFIXES))
                and (include_code or not n.endswith(".py"))]
    if not any(n == "config.json" for n, _ in sidecars):
        raise StoreError("This repo has no config.json, so it is not a transformers model.")
    chosen = {n: s for n, s in sidecars + weights}
    # Small files first: config/tokenizer problems surface before the big download.
    return sorted(chosen.items(), key=lambda item: (item[0].endswith(WEIGHT_SUFFIXES), item[0]))


def split_dir_name(compression: str) -> str:
    return "splitted_model" if compression in ("", "none", None) else f"splitted_model.{compression}"


def _progress_kwargs(job: "PullJob", base: int, size: int) -> dict:
    """hf_hub_download arguments that feed real byte counts into the job.

    Hugging Face's Xet downloader (hf_xet, installed with huggingface-hub) fetches chunks into its
    own cache and only assembles the ``*.incomplete`` file later, so the size of that file stays near
    zero while the network is busy. The downloader's progress bars do count the bytes: this reports
    the highest count any of a file's bars has reached. Older huggingface-hub versions lack the
    ``tqdm_class`` argument; they get no extra arguments and rely on the file-size watcher alone."""
    import inspect

    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import tqdm as hub_tqdm

    if "tqdm_class" not in inspect.signature(hf_hub_download).parameters:
        return {}
    seen = {}                    # bar id -> bytes counted so far
    last_report = [0.0]

    class ProgressBar(hub_tqdm):
        def __init__(self, *args, **kwargs):
            self._counted = int(kwargs.get("initial") or 0)
            super().__init__(*args, **kwargs)
            seen[id(self)] = self._counted

        def update(self, n=1):   # also called when hub progress bars are disabled: count ourselves
            self._counted += int(n or 0)
            seen[id(self)] = self._counted
            now = time.monotonic()
            if now - last_report[0] >= 0.25:     # a few UI updates per second, not one per chunk
                last_report[0] = now
                job.update(completed=max(job.completed, base + min(max(seen.values()), size)))
            return super().update(n)

        def display(self, *args, **kwargs):   # the web UI draws progress; print nothing
            return None

    return {"tqdm_class": ProgressBar}


def airllm_class_for(snapshot: Path, token: str | None = None):
    from airllm.auto_model import AutoModel

    kwargs = {"hf_token": token} if token else {}
    module, cls_name = AutoModel.get_module_class(str(snapshot), **kwargs)
    return getattr(importlib.import_module(module), cls_name)


def layer_names_for(cls) -> dict:
    probe = cls.__new__(cls)          # no __init__: we only need the layer-name table
    probe.set_layer_names_dict()
    return probe.layer_names_dict


def split_layers(snapshot: Path, layers_path: Path, compression: str, repo: str | None,
                 token: str | None) -> str:
    """Run AirLLM's one-time per-layer split, exactly as AutoModel.from_pretrained would."""
    from airllm.utils import split_and_save_layers

    cls = airllm_class_for(snapshot, token)
    return split_and_save_layers(
        snapshot, layer_shards_saving_path=str(layers_path),
        compression=None if compression in ("", "none") else compression,
        layer_names=layer_names_for(cls), delete_original=False, repo_id=repo, hf_token=token)


def delete_original_weights(snapshot: Path) -> bool:
    """Drop the downloaded weights once the per-layer copy exists (multi-shard models only:
    single-file checkpoints are small and AirLLM's local-path detection needs the file)."""
    if not ((snapshot / "model.safetensors.index.json").exists()
            or (snapshot / "pytorch_model.bin.index.json").exists()):
        return False
    for path in snapshot.iterdir():
        if path.name.endswith(WEIGHT_SUFFIXES):
            real = Path(os.path.realpath(path))
            path.unlink(missing_ok=True)
            if real != path:
                real.unlink(missing_ok=True)
    return True


VISION_MODULES = re.compile(r"visual|vision|image|mm_projector|multi_modal_projector|vit\b", re.I)
AUDIO_MODULES = re.compile(r"audio|speech|whisper|sound", re.I)


def _declares_media(snapshot: Path) -> bool:
    """Does config.json describe a vision or audio encoder at all? (cheap: no AirLLM import)"""
    try:
        raw = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(raw, dict):
        return False
    thinker = raw.get("thinker_config") if isinstance(raw.get("thinker_config"), dict) else {}
    keys = ("vision_config", "audio_config", "audio_encoder_config")
    return any(raw.get(k) is not None or thinker.get(k) is not None for k in keys)


def capabilities_for(snapshot: Path, token: str | None = None) -> list[str]:
    """Capabilities of a pulled model. Text-only configs never load AirLLM's model class (which
    imports torch and reads the config with trust_remote_code)."""
    if not _declares_media(snapshot):
        return ["completion"]
    return detect_capabilities(snapshot, layer_names_for(airllm_class_for(snapshot, token)))


def detect_capabilities(snapshot: Path, layer_names: dict | None) -> list[str]:
    """Which inputs a model takes natively *and* AirLLM can feed it.

    A checkpoint can carry a vision or audio encoder, but it only works under AirLLM when the
    AirLLM class keeps that encoder resident (``layer_names['resident']``); otherwise it would stay
    on the meta device. Both the config and the AirLLM class must agree, and the processor that
    turns pixels or audio into model inputs must ship with the model."""
    caps = ["completion"]
    try:
        raw = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return caps
    resident = " ".join((layer_names or {}).get("resident", []))
    has_processor = any((snapshot / f).exists() for f in PROCESSOR_FILES[:2])   # image/audio, not video-only
    if has_processor and raw.get("vision_config") is not None and VISION_MODULES.search(resident):
        caps.append("vision")
    thinker = raw.get("thinker_config") or {}
    audio_cfg = any(cfg.get(key) is not None for cfg in (raw, thinker)
                    for key in ("audio_config", "audio_encoder_config"))
    if has_processor and audio_cfg and AUDIO_MODULES.search(resident):
        caps.append("audio")
    return caps


def _config(snapshot: Path) -> dict:
    try:
        cfg = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Multimodal configs keep the language model's numbers under text_config.
    text = cfg.get("text_config") or {}
    return {**text, **{k: v for k, v in cfg.items() if v is not None}}


def human_count(n: float) -> str:
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            value = n / div
            return f"{value:.0f}{unit}" if value >= 10 else f"{value:.1f}{unit}"
    return str(int(n))


def fill_details(manifest: Manifest, snapshot: Path) -> None:
    cfg = _config(snapshot)
    archs = cfg.get("architectures") or []
    manifest.architecture = archs[0] if archs else ""
    manifest.model_type = cfg.get("model_type", "")
    manifest.context_length = int(cfg.get("max_position_embeddings") or 0)
    dtype = cfg.get("torch_dtype") or cfg.get("dtype") or ""
    manifest.dtype = str(dtype)
    total_bytes = 0
    for index in ("model.safetensors.index.json", "pytorch_model.bin.index.json"):
        try:
            meta = json.loads((snapshot / index).read_text(encoding="utf-8")).get("metadata", {})
            total_bytes = int(meta.get("total_size") or 0)
            break
        except (OSError, ValueError):
            continue
    if not total_bytes:
        for p in snapshot.iterdir():
            if p.name.endswith(WEIGHT_SUFFIXES):
                try:
                    total_bytes += p.stat().st_size
                except OSError:
                    pass
    if total_bytes:
        manifest.parameter_size = human_count(total_bytes / DTYPE_BYTES.get(manifest.dtype, 2))


def friendly_error(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else name
    if isinstance(exc, StoreError):
        return text
    if name == "GatedRepoError" or "gated" in text.lower():
        return ("This model is gated. Accept its licence on huggingface.co, then add your "
                "Hugging Face token in Settings.")
    if name in ("RepositoryNotFoundError", "RevisionNotFoundError"):
        return "Model not found on Hugging Face (check the name, or add a token for private repos)."
    if "CERTIFICATE_VERIFY_FAILED" in text or name in ("SSLError", "SSLCertVerificationError"):
        return ("Secure connection to Hugging Face failed: the system has no trusted CA certificates "
                "(install the ca-certificates package) or a proxy is intercepting TLS.")
    if name in ("LocalEntryNotFoundError", "ConnectionError", "OfflineModeIsEnabled", "ProxyError",
                "ConnectError", "ConnectTimeout", "ReadTimeout"):
        return f"Could not reach Hugging Face ({text}). Check your internet connection or proxy."
    if "No space left" in text or name == "NotEnoughSpaceException":
        return "Not enough disk space. Free some space or move the models folder in Settings."
    return f"{name}: {text}"
