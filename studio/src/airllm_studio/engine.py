"""Runs one AirLLM model at a time and streams generations from it.

AirLLM streams every layer from disk for each forward pass, so a single model is resident and
requests are served one after another; callers waiting their turn see a "queued" status.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .config import SettingsStore
from .store import Manifest, ModelStore, RemoteCodeRequired, check_remote_code

log = logging.getLogger("airllm_studio.engine")


class EngineError(Exception):
    """A problem worth showing to the user as-is."""


@dataclass
class GenOptions:
    max_new_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    seed: int | None = None
    stop: list[str] = field(default_factory=list)
    context_length: int = 4096

    @classmethod
    def merge(cls, defaults, **overrides) -> "GenOptions":
        opts = cls(max_new_tokens=defaults.max_new_tokens, temperature=defaults.temperature,
                   top_p=defaults.top_p, context_length=defaults.context_length)
        for key, value in overrides.items():
            if value is not None and hasattr(opts, key):
                setattr(opts, key, value)
        if isinstance(opts.stop, str):
            opts.stop = [opts.stop]
        opts.max_new_tokens = max(1, min(int(opts.max_new_tokens), 32768))
        opts.temperature = max(0.0, float(opts.temperature))
        opts.top_p = min(1.0, max(0.01, float(opts.top_p)))
        return opts


class Engine:
    def __init__(self, store: ModelStore, settings: SettingsStore):
        self.store = store
        self.settings = settings
        self.model = None
        self.model_name: str | None = None
        self.device: str | None = None
        self.state = "idle"                     # idle | loading | ready | generating
        self.loaded_at: float | None = None
        self.last_used = time.time()
        self.waiting = 0
        self.last_stats: dict = {}
        self.layer_pos = -1                     # module AirLLM is streaming right now
        self.layer_total = 0
        self._gen_lock = threading.Lock()
        self._torch_info: dict | None = None
        self._processor = None                  # multimodal models: loaded on first image/audio
        self._manifest_loaded: Manifest | None = None

    # --- hardware ------------------------------------------------------------------------
    def hardware(self) -> dict:
        """torch / CUDA facts for the status bar. Cached after the first (slow) torch import."""
        if self._torch_info is None:
            info = {"torch": None, "cuda": None, "gpus": [], "bitsandbytes": False}
            try:
                import torch

                info["torch"] = torch.__version__
                info["cuda"] = torch.version.cuda
                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        props = torch.cuda.get_device_properties(i)
                        info["gpus"].append({"index": i, "name": props.name,
                                             "vram_total": int(props.total_memory)})
            except Exception as exc:  # noqa: BLE001
                info["error"] = str(exc)
            try:
                import importlib.util

                info["bitsandbytes"] = importlib.util.find_spec("bitsandbytes") is not None
            except Exception:  # noqa: BLE001
                pass
            self._torch_info = info
        return self._torch_info

    def resolve_device(self) -> str:
        wanted = self.settings.settings.device
        if wanted and wanted != "auto":
            return wanted
        return "cuda:0" if self.hardware()["gpus"] else "cpu"

    def status(self) -> dict:
        return {
            "state": self.state, "model": self.model_name, "device": self.device,
            "loaded_at": self.loaded_at, "last_used": self.last_used, "queued": self.waiting,
            "last_stats": self.last_stats,
        }

    # --- load / unload -------------------------------------------------------------------
    def _manifest(self, name: str) -> Manifest:
        manifest = self.store.get(name)
        if manifest is None:
            raise EngineError(f"Model '{name}' is not installed. Pull it first (airllm pull {name}).")
        if manifest.status != "ready":
            raise EngineError(f"Model '{name}' is not ready yet ({manifest.status}). "
                              + (manifest.error or "Wait for the pull to finish."))
        return manifest

    def _load(self, name: str) -> None:
        if self.model is not None and self.model_name == name:
            return
        manifest = self._manifest(name)
        if manifest.snapshot_path:
            try:
                check_remote_code(Path(manifest.snapshot_path), manifest.name, manifest.trust_remote_code)
            except RemoteCodeRequired as exc:      # e.g. a model pulled before this check existed
                raise EngineError(str(exc)) from None
        self._unload()
        self.state = "loading"
        try:
            import torch
            from airllm import AutoModel

            device = self.resolve_device()
            kwargs = {
                "device": device,
                "layer_shards_saving_path": manifest.layers_path,
                "max_seq_len": self.settings.settings.defaults.context_length,
            }
            if device == "cpu":
                kwargs["dtype"] = torch.float32       # bf16 matmuls are slow/partial on many CPUs
            if manifest.compression not in ("", "none"):
                kwargs["compression"] = manifest.compression
            token = self.settings.hf_token()
            if token:
                kwargs["hf_token"] = token
            log.info("loading %s on %s", name, device)
            self.model = AutoModel.from_pretrained(manifest.snapshot_path, **kwargs)
            self._watch_layers()
            self.model_name, self.device, self.loaded_at = name, device, time.time()
            self._manifest_loaded, self._processor = manifest, None
            self.state = "ready"
        except Exception:
            self.model, self.model_name, self.device, self.state = None, None, None, "idle"
            raise

    def _watch_layers(self) -> None:
        """Track which layer AirLLM is streaming, for the UI's layer meter."""
        layers = list(getattr(self.model, "layers", None) or [])
        self.layer_total, self.layer_pos = len(layers), -1

        def make_hook(index):
            def hook(module, args):
                self.layer_pos = index
            return hook

        for index, module in enumerate(layers):
            try:
                module.register_forward_pre_hook(make_hook(index))
            except Exception:  # noqa: BLE001 - a missing meter must never break generation
                pass

    def _unload(self) -> None:
        if self.model is None:
            return
        log.info("unloading %s", self.model_name)
        executor = getattr(self.model, "_executor", None)
        if executor is not None:
            executor.shutdown(wait=False)
        self.model, self.model_name, self.device, self.loaded_at = None, None, None, None
        self._manifest_loaded, self._processor = None, None
        self.state = "idle"
        try:
            import gc

            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def load(self, name: str) -> None:
        with self._gen_lock:
            self._load(name)
            self.last_used = time.time()

    def unload(self) -> None:
        with self._gen_lock:
            self._unload()

    def unload_if_idle(self, idle_seconds: float) -> bool:
        if self.model is None or idle_seconds <= 0 or self.waiting:
            return False
        if time.time() - self.last_used < idle_seconds:
            return False
        if self._gen_lock.acquire(blocking=False):
            try:
                self._unload()
                return True
            finally:
                self._gen_lock.release()
        return False

    # --- generation ----------------------------------------------------------------------
    def stream(self, name: str, messages: list[dict], options: GenOptions,
               cancel: threading.Event, raw_prompt: str | None = None) -> Iterator[dict]:
        """Yields {"type": "status"|"token"|"done", ...} events. Blocking; run it in a thread."""
        self.waiting += 1
        acquired = False
        try:
            if self._gen_lock.locked():
                yield {"type": "status", "status": "queued", "message": "Waiting for the model to be free"}
            while not acquired:
                acquired = self._gen_lock.acquire(timeout=0.5)
                if not acquired and cancel.is_set():
                    yield {"type": "done", "done_reason": "cancelled", "stats": {}}
                    return
            self.waiting -= 1
            started = time.time()
            if self.model is None or self.model_name != name:
                yield {"type": "status", "status": "loading", "message": f"Loading {name}"}
                self._load(name)
            load_duration = time.time() - started
            self.state = "generating"
            yield {"type": "status", "status": "generating",
                   "message": "Thinking (AirLLM streams every layer from disk, first token takes a while)"}
            yield from self._generate(messages, options, cancel, raw_prompt, started, load_duration)
        finally:
            if acquired:
                if self.model is not None:
                    self.state = "ready"
                self.last_used = time.time()
                self._gen_lock.release()
            else:
                self.waiting -= 1

    def _render(self, messages: list[dict], tok) -> str:
        if getattr(tok, "chat_template", None):
            plain = [{"role": m["role"], "content": m["content"]} for m in messages]
            return tok.apply_chat_template(plain, tokenize=False, add_generation_prompt=True)
        parts = [f"{m['role'].capitalize()}: {m['content']}" for m in messages]
        return "\n".join(parts) + "\nAssistant:"

    def _encode(self, messages: list[dict], raw_prompt: str | None, limit: int):
        """Token ids for the prompt, fitted to ``limit``.

        Too long a conversation loses its oldest turns first; system messages (instructions and
        project files) and the latest message are kept. Only if that is still too long is the
        prompt cut from the front."""
        tok = self.model.tokenizer
        templated = raw_prompt is None and bool(getattr(tok, "chat_template", None))

        def ids_for(msgs):
            text = raw_prompt if raw_prompt is not None else self._render(msgs, tok)
            return tok(text, return_tensors="pt", add_special_tokens=not templated)["input_ids"]

        ids = ids_for(messages)
        if raw_prompt is None:
            msgs = list(messages)
            while ids.shape[1] > limit:
                droppable = [i for i, m in enumerate(msgs[:-1]) if m["role"] != "system"]
                if not droppable:
                    break
                del msgs[droppable[0]]
                ids = ids_for(msgs)
        if ids.shape[1] > limit:                 # keep the most recent context
            ids = ids[:, -limit:]
        return ids

    # --- images / audio ------------------------------------------------------------------
    def capabilities(self) -> list[str]:
        manifest = self._manifest_loaded
        return list(manifest.capabilities) if manifest and manifest.capabilities else ["completion"]

    def _get_processor(self):
        if self._processor is None:
            from transformers import AutoProcessor

            manifest = self._manifest_loaded
            if manifest is None or not manifest.snapshot_path:
                raise EngineError("This model has no processor for images or audio.")
            # Same opt-in as the model itself: a processor's own code runs only if the user allowed it.
            self._processor = AutoProcessor.from_pretrained(
                manifest.snapshot_path, trust_remote_code=bool(manifest.trust_remote_code))
        return self._processor

    def _multimodal_inputs(self, messages: list[dict], limit: int) -> dict:
        """Chat with images/audio -> model inputs, via the model's own processor and chat template."""
        import torch

        from .media import load_image, load_wav

        caps = self.capabilities()
        if any(m.get("images") for m in messages) and "vision" not in caps:
            raise EngineError(f"{self.model_name} does not take images.")
        if any(m.get("audio") for m in messages) and "audio" not in caps:
            raise EngineError(f"{self.model_name} does not take audio.")
        proc = self._get_processor()
        extractor = getattr(proc, "feature_extractor", None)
        rate = int(getattr(extractor, "sampling_rate", 16000) or 16000)
        conversation = []
        for m in messages:
            parts = [{"type": "image", "image": load_image(b)} for b in m.get("images", [])]
            parts += [{"type": "audio", "audio": load_wav(b, rate)} for b in m.get("audio", [])]
            if m["content"] or not parts:
                parts.append({"type": "text", "text": m["content"]})
            conversation.append({"role": m["role"], "content": parts})
        inputs = proc.apply_chat_template(conversation, add_generation_prompt=True, tokenize=True,
                                          return_dict=True, return_tensors="pt")
        if inputs["input_ids"].shape[1] > limit:
            raise EngineError("This conversation with its images/audio is longer than the context length. "
                              "Start a new chat or raise the context length in Settings.")
        dtype = getattr(self.model, "running_dtype", None)
        device = torch.device(self.device or "cpu")
        out = {}
        for key, value in dict(inputs).items():
            if isinstance(value, torch.Tensor):
                value = value.to(device)
                if value.is_floating_point() and dtype is not None:
                    value = value.to(dtype)
            out[key] = value
        return out

    def _generate(self, messages, options: GenOptions, cancel: threading.Event,
                  raw_prompt: str | None, started: float, load_duration: float) -> Iterator[dict]:
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

        model, tok = self.model, self.model.tokenizer
        limit = max(16, options.context_length - options.max_new_tokens)
        device = torch.device(self.device or "cpu")
        if raw_prompt is None and any(m.get("images") or m.get("audio") for m in messages):
            inputs = self._multimodal_inputs(messages, limit)
            tok = getattr(self._get_processor(), "tokenizer", None) or tok
        else:
            input_ids = self._encode(messages, raw_prompt, limit).to(device)
            inputs = {"input_ids": input_ids, "attention_mask": torch.ones_like(input_ids)}
        prompt_tokens = int(inputs["input_ids"].shape[1])
        stop_now = threading.Event()

        class _Counter(StoppingCriteria):
            count = 0
            first_token_at: float | None = None

            def __call__(self, ids, scores, **kwargs):
                self.count += 1
                if self.first_token_at is None:
                    self.first_token_at = time.time()
                halt = cancel.is_set() or stop_now.is_set()
                return torch.full((ids.shape[0],), halt, dtype=torch.bool, device=ids.device)

        counter = _Counter()
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=0.25)
        pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
        gen_kwargs = dict(
            **inputs,
            max_new_tokens=options.max_new_tokens,
            streamer=streamer,
            stopping_criteria=StoppingCriteriaList([counter]),
            use_cache=True,
            pad_token_id=pad_id,
        )
        if options.temperature > 0:
            gen_kwargs.update(do_sample=True, temperature=options.temperature, top_p=options.top_p)
        else:
            gen_kwargs.update(do_sample=False, temperature=None, top_p=None, top_k=None)
        if options.seed is not None:
            torch.manual_seed(int(options.seed))

        error: list[BaseException] = []

        def run():
            try:
                with torch.inference_mode():
                    model.generate(**gen_kwargs)
            except BaseException as exc:  # noqa: BLE001 - re-raised in the consumer
                error.append(exc)
                streamer.end()

        gen_started = time.time()
        worker = threading.Thread(target=run, name="airllm-generate", daemon=True)
        worker.start()
        produced, emitted = "", 0
        hit_stop = False
        last_progress = None
        self.layer_pos = -1
        pieces = iter(streamer)
        while True:
            try:
                piece = next(pieces)
            except StopIteration:
                break
            except queue.Empty:                  # no new text yet: report where AirLLM is
                progress = (self.layer_pos + 1, self.layer_total, counter.count)
                if progress != last_progress and self.layer_total:
                    last_progress = progress
                    yield {"type": "progress", "layer": progress[0], "layers": progress[1],
                           "tokens": progress[2]}
                continue
            if not piece or hit_stop:
                continue
            produced += piece
            if options.stop:
                cut = min((produced.find(s) for s in options.stop if s and s in produced), default=-1)
                if cut >= 0:
                    hit_stop = True
                    stop_now.set()
                    if cut > emitted:
                        yield {"type": "token", "text": produced[emitted:cut]}
                    emitted = cut
                    continue
                # Hold back a tail that could be the start of a stop string.
                hold = max(len(s) for s in options.stop) - 1
                safe = max(emitted, len(produced) - hold)
            else:
                safe = len(produced)
            if safe > emitted:
                yield {"type": "token", "text": produced[emitted:safe]}
                emitted = safe
        worker.join()
        if error and not cancel.is_set():
            raise error[0]
        if not hit_stop and emitted < len(produced):
            yield {"type": "token", "text": produced[emitted:]}

        end = time.time()
        first = counter.first_token_at or end
        eval_count = counter.count
        if cancel.is_set():
            reason = "cancelled"
        elif hit_stop:
            reason = "stop"
        elif eval_count >= options.max_new_tokens:
            reason = "length"
        else:
            reason = "stop"
        stats = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": eval_count,
            "load_duration": load_duration,
            "prompt_duration": max(0.0, first - gen_started),
            "eval_duration": max(0.0, end - first),
            "total_duration": end - started,
            "tokens_per_second": (eval_count - 1) / (end - first) if eval_count > 1 and end > first else 0.0,
        }
        self.last_stats = stats
        yield {"type": "done", "done_reason": reason, "stats": stats}
