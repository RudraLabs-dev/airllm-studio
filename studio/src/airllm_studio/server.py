"""HTTP server: Ollama-compatible /api, OpenAI-compatible /v1, Studio /api/studio and the web UI."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .catalog import CATALOG
from .chats import UNSET, ChatStore, ProjectError, project_context
from .config import SettingsStore, data_dir, logs_dir, parse_host
from .engine import Engine, EngineError, GenOptions
from .media import MediaError, parse_ollama_media, parse_openai_content
from .security import allowed_host_names, api_key_matches, env_list, normalize_origin, request_allowed
from .store import ModelStore, StoreError

log = logging.getLogger("airllm_studio.server")
WEB_DIR = Path(__file__).parent / "web"
NS = 1_000_000_000
MAX_UPLOAD_BYTES = 2_000_000


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in ("testclient", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _airllm_version() -> str:
    try:
        from importlib.metadata import version

        return version("airllm")
    except Exception:  # noqa: BLE001
        return "unknown"


def _clean_messages(messages) -> list[dict]:
    """Normalise Ollama and OpenAI message shapes to {role, content[, images][, audio]}.

    Images/audio arrive as Ollama-style ``images``/``audio`` base64 lists or OpenAI content parts
    (``image_url`` data URLs, ``input_audio``); they are decoded to bytes here."""
    if not isinstance(messages, list):
        raise HTTPException(400, "messages must be a list")
    out = []
    for m in messages:
        if not isinstance(m, dict) or "role" not in m:
            raise HTTPException(400, "each message needs a role and content")
        role = m["role"] if m["role"] in ("system", "user", "assistant", "tool") else "user"
        if role == "tool":
            role = "user"
        try:
            text, media = parse_openai_content(m.get("content"))
            for key, items in parse_ollama_media(m).items():
                media.setdefault(key, []).extend(items)
        except MediaError as exc:
            raise HTTPException(400, str(exc)) from None
        out.append({"role": role, "content": text, **media})
    return out


MEDIA_LABEL = {"images": ("vision", "images", "[image omitted]"), "audio": ("audio", "audio", "[audio omitted]")}


def _fit_media(model: str, capabilities: list[str], messages: list[dict]) -> list[dict]:
    """Media for a model that cannot take it: an error if it is in the newest message (the user is
    asking about it now), otherwise dropped from older turns with a placeholder so a chat can
    switch to a text-only model."""
    out = []
    for i, m in enumerate(messages):
        m = dict(m)
        for key, (cap, noun, placeholder) in MEDIA_LABEL.items():
            if m.get(key) and cap not in capabilities:
                if i == len(messages) - 1:
                    raise HTTPException(400, f"{model} does not take {noun}. Pick a model that does, "
                                             f"or send the message without {noun}.")
                m.pop(key)
                m["content"] = (m["content"] + " " + placeholder).strip()
        out.append(m)
    return out


async def _stream_blocking(factory: Callable[[], Iterator[dict]], cancel: threading.Event) -> AsyncIterator[dict]:
    """Run a blocking generator in a thread and yield its items; cancel it if the client leaves."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def put(item):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:          # loop closed: the client is gone
            cancel.set()

    def worker():
        try:
            for item in factory():
                put(item)
        except BaseException as exc:  # noqa: BLE001
            put(exc)
        finally:
            put(sentinel)

    threading.Thread(target=worker, name="stream-worker", daemon=True).start()
    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        cancel.set()


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, (EngineError, StoreError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _ndjson(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode()


# ---------------------------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------------------------
class Studio:
    def __init__(self, settings: SettingsStore | None = None, store: ModelStore | None = None,
                 engine: Engine | None = None, chats: ChatStore | None = None):
        self.settings = settings or SettingsStore()
        s = self.settings
        self.store = store or ModelStore(s.models_dir, s.hf_token,
                                         compression=lambda: s.settings.compression,
                                         delete_original=lambda: s.settings.delete_original)
        self.engine = engine or Engine(self.store, self.settings)
        self.chats = chats or ChatStore(data_dir() / "chats.db")
        self.started_at = time.time()
        self.api_key = os.environ.get("AIRLLM_API_KEY") or ""
        self.shutdown_hook: Callable[[], None] | None = None


def create_app(studio: Studio | None = None, keepalive: bool = True, bind_host: str | None = None) -> FastAPI:
    """bind_host: the host the server listens on (default from AIRLLM_HOST); a name given here is
    accepted in the Host header in addition to loopback, IP addresses and AIRLLM_ALLOWED_HOSTS."""
    studio = studio or Studio()
    allowed_hosts = allowed_host_names(bind_host if bind_host is not None else parse_host()[0])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        threading.Thread(target=studio.engine.hardware, name="hw-probe", daemon=True).start()
        stop = threading.Event()
        if keepalive:
            def reaper():
                while not stop.wait(30):
                    minutes = studio.settings.settings.keep_alive_minutes
                    if minutes and studio.engine.unload_if_idle(minutes * 60):
                        log.info("unloaded idle model after %s min", minutes)
            threading.Thread(target=reaper, name="keepalive", daemon=True).start()
        yield
        stop.set()

    app = FastAPI(title="AirLLM Studio", version=__version__, lifespan=lifespan,
                  description="Ollama-compatible (/api) and OpenAI-compatible (/v1) API for AirLLM.")
    app.state.studio = studio

    origins = env_list("AIRLLM_ORIGINS")
    extra_origins = frozenset(normalize_origin(o) for o in origins)
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"],
                           allow_headers=["*"], allow_credentials=False)

    # Registered after CORS, so it runs first: nothing reaches a handler (or CORS) unchecked.
    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        protected = path.startswith(("/api", "/v1"))
        ok, status, message = request_allowed(request.headers, allowed_hosts, extra_origins, protected)
        if not ok:
            log.warning("refused %s %s: %s (Host=%s, Origin=%s)", request.method, path, message,
                        request.headers.get("host"), request.headers.get("origin"))
            return JSONResponse({"error": message}, status_code=status)
        if studio.api_key and protected and not _is_loopback(request):
            if not api_key_matches(request.headers.get("authorization", ""), studio.api_key):
                return JSONResponse({"error": "missing or invalid API key"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(EngineError)
    async def engine_error(request: Request, exc: EngineError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(StoreError)
    async def store_error(request: Request, exc: StoreError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(ProjectError)
    async def project_error(request: Request, exc: ProjectError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(MediaError)
    async def media_error(request: Request, exc: MediaError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    def local_only(request: Request):
        if not _is_loopback(request):
            raise HTTPException(403, "only allowed from this computer")

    def gen_options(opts: dict | None = None, **direct) -> GenOptions:
        opts = opts or {}
        return GenOptions.merge(
            studio.settings.settings.defaults,
            max_new_tokens=direct.get("max_new_tokens", opts.get("num_predict")),
            temperature=direct.get("temperature", opts.get("temperature")),
            top_p=direct.get("top_p", opts.get("top_p")),
            seed=direct.get("seed", opts.get("seed")),
            stop=direct.get("stop", opts.get("stop")),
            context_length=opts.get("num_ctx"),
        )

    def with_system(messages: list[dict], project: dict | None = None,
                    context_length: int | None = None) -> list[dict]:
        """Prepend the default system prompt and, for project chats, the project's instructions
        and files (cut to about half the context, so the conversation still fits)."""
        if any(m["role"] == "system" for m in messages):
            return messages
        parts = [studio.settings.settings.defaults.system_prompt.strip()]
        if project:
            ctx = context_length or studio.settings.settings.defaults.context_length
            parts.append(project_context(project, budget_chars=max(2000, ctx * 2)))
        system = "\n\n".join(p for p in parts if p)
        return [{"role": "system", "content": system}] + messages if system else messages

    def start_pull(request: Request, name: str, body: dict):
        # Model code only runs when the caller explicitly allows it; folders on this computer can
        # only be imported by local callers (a remote API client must not read arbitrary paths).
        return studio.store.pull(name, trust_remote_code=body.get("trust_remote_code") is True,
                                 allow_local=_is_loopback(request))

    def require_model(name: str | None) -> str:
        if not name:
            raise HTTPException(400, "model is required")
        manifest = studio.store.get(name)
        if manifest is None:
            raise HTTPException(404, f"model '{name}' not found, try pulling it first")
        return manifest.name

    def capabilities_of(name: str) -> list[str]:
        manifest = studio.store.get(name)
        if manifest is None:
            return ["completion"]
        return studio.store.ensure_capabilities(manifest).capabilities or ["completion"]

    def project_for(project_id) -> dict | None:
        if not project_id:
            return None
        project = studio.chats.get_project(str(project_id), with_files=True, with_content=True)
        if project is None:
            raise HTTPException(404, "project not found")
        return project

    # =========================================================================================
    # Ollama-compatible API
    # =========================================================================================
    @app.get("/api/version")
    def version():
        return {"version": __version__, "airllm": _airllm_version()}

    def _ollama_model(m) -> dict:
        return {
            "name": m.name, "model": m.name, "modified_at": m.modified_at,
            "size": m.size_on_disk, "digest": m.revision or m.name,
            "details": {"format": "safetensors", "family": m.model_type,
                        "families": [m.model_type] if m.model_type else [],
                        "parameter_size": m.parameter_size, "quantization_level": m.compression.upper()
                        if m.compression not in ("", "none") else (m.dtype or "BF16").upper()},
        }

    @app.get("/api/tags")
    def tags():
        return {"models": [_ollama_model(m) for m in studio.store.list() if m.status == "ready"]}

    @app.get("/api/ps")
    def ps():
        eng = studio.engine
        if not eng.model_name:
            return {"models": []}
        m = studio.store.get(eng.model_name)
        entry = _ollama_model(m) if m else {"name": eng.model_name, "model": eng.model_name}
        entry["size_vram"] = 0
        entry["expires_at"] = datetime.fromtimestamp(
            eng.last_used + studio.settings.settings.keep_alive_minutes * 60, timezone.utc).isoformat()
        entry["device"] = eng.device
        return {"models": [entry]}

    @app.post("/api/show")
    async def show(request: Request):
        body = await request.json()
        name = require_model(body.get("model") or body.get("name"))
        m = studio.store.get(name)
        return {"modelfile": "", "parameters": "", "template": "",
                "capabilities": capabilities_of(name),
                "details": _ollama_model(m)["details"],
                "model_info": {"general.architecture": m.model_type,
                               "general.context_length": m.context_length,
                               "airllm.architecture_class": m.architecture,
                               "airllm.source": m.repo},
                "modified_at": m.modified_at}

    @app.delete("/api/delete")
    async def delete(request: Request):
        body = await request.json()
        name = require_model(body.get("model") or body.get("name"))
        if studio.engine.model_name == name:
            await asyncio.to_thread(studio.engine.unload)
        studio.store.delete(name)
        return JSONResponse({}, status_code=200)

    @app.post("/api/pull")
    async def pull(request: Request):
        body = await request.json()
        name = body.get("model") or body.get("name")
        if not name:
            raise HTTPException(400, "model is required")
        job = start_pull(request, name, body)
        stream = body.get("stream", True)

        def ollama_events() -> Iterator[dict]:
            for ev in job.events():
                if ev["phase"] == "error":
                    yield {"error": ev["error"]}
                    return
                if ev["phase"] == "cancelled":
                    yield {"error": "cancelled"}
                    return
                if ev["phase"] == "success":
                    yield {"status": "success"}
                    return
                out = {"status": ev["message"]}
                if ev["phase"] == "downloading":
                    out.update(status=f"pulling {job.name}", digest=job.name,
                               total=ev["total"], completed=ev["completed"])
                elif ev["phase"] == "preparing":
                    out.update(status="preparing layers", total=ev["layers_total"],
                               completed=ev["layers_done"])
                yield out

        if not stream:
            result: dict = {}
            for item in await asyncio.to_thread(lambda: list(ollama_events())):
                result = item
            return JSONResponse(result, status_code=400 if "error" in result else 200)

        async def body_iter():
            cancel = threading.Event()   # leaving the stream does not cancel the pull itself
            async for item in _stream_blocking(ollama_events, cancel):
                yield _ndjson(item)

        return StreamingResponse(body_iter(), media_type="application/x-ndjson")

    async def _run_generation(name: str, messages, opts: GenOptions, raw_prompt, stream: bool,
                              shape: Callable[[dict], dict | None], final: Callable[[str, dict, str], dict]):
        cancel = threading.Event()
        factory = lambda: studio.engine.stream(name, messages, opts, cancel, raw_prompt)  # noqa: E731
        if stream:
            async def body_iter():
                try:
                    async for ev in _stream_blocking(factory, cancel):
                        if ev["type"] == "done":
                            yield _ndjson(final("", ev["stats"], ev["done_reason"]))
                        else:
                            item = shape(ev)
                            if item is not None:
                                yield _ndjson(item)
                except Exception as exc:  # noqa: BLE001
                    log.exception("generation failed")
                    yield _ndjson({"error": _error_text(exc)})
            return StreamingResponse(body_iter(), media_type="application/x-ndjson")

        text, stats, reason = [], {}, "stop"
        try:
            async for ev in _stream_blocking(factory, cancel):
                if ev["type"] == "token":
                    text.append(ev["text"])
                elif ev["type"] == "done":
                    stats, reason = ev["stats"], ev["done_reason"]
        except (EngineError, StoreError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            log.exception("generation failed")
            return JSONResponse({"error": _error_text(exc)}, status_code=500)
        return final("".join(text), stats, reason)

    def _ollama_stats(stats: dict) -> dict:
        return {
            "total_duration": int(stats.get("total_duration", 0) * NS),
            "load_duration": int(stats.get("load_duration", 0) * NS),
            "prompt_eval_count": stats.get("prompt_tokens", 0),
            "prompt_eval_duration": int(stats.get("prompt_duration", 0) * NS),
            "eval_count": stats.get("completion_tokens", 0),
            "eval_duration": int(stats.get("eval_duration", 0) * NS),
        }

    @app.post("/api/chat")
    async def chat(request: Request):
        body = await request.json()
        name = require_model(body.get("model"))
        messages = _clean_messages(body.get("messages") or [])
        if not messages:
            if body.get("keep_alive") in (0, "0", "0s"):
                await asyncio.to_thread(studio.engine.unload)
            else:
                await asyncio.to_thread(studio.engine.load, name)
            return {"model": name, "created_at": _now(), "message": {"role": "assistant", "content": ""},
                    "done": True, "done_reason": "load"}
        opts = gen_options(body.get("options"))
        want_progress = bool(body.get("airllm_progress"))   # the Studio UI's layer meter
        project = project_for(body.get("airllm_project"))  # Studio projects: instructions + files
        messages = _fit_media(name, capabilities_of(name), messages)

        def shape(ev):
            base = {"model": name, "created_at": _now(), "done": False}
            if ev["type"] == "token":
                return {**base, "message": {"role": "assistant", "content": ev["text"]}}
            if ev["type"] == "progress":
                if not want_progress:
                    return None
                return {**base, "message": {"role": "assistant", "content": ""},
                        "progress": {k: ev[k] for k in ("layer", "layers", "tokens")}}
            return {**base, "message": {"role": "assistant", "content": ""},
                    "status": ev.get("status"), "status_message": ev.get("message")}

        def final(text, stats, reason):
            return {"model": name, "created_at": _now(),
                    "message": {"role": "assistant", "content": text},
                    "done": True, "done_reason": reason, **_ollama_stats(stats),
                    "tokens_per_second": stats.get("tokens_per_second", 0)}

        return await _run_generation(name, with_system(messages, project, opts.context_length), opts, None,
                                     body.get("stream", True), shape, final)

    @app.post("/api/generate")
    async def generate(request: Request):
        body = await request.json()
        name = require_model(body.get("model"))
        prompt = body.get("prompt") or ""
        if not prompt:
            if body.get("keep_alive") in (0, "0", "0s"):
                await asyncio.to_thread(studio.engine.unload)
            else:
                await asyncio.to_thread(studio.engine.load, name)
            return {"model": name, "created_at": _now(), "response": "", "done": True, "done_reason": "load"}
        raw = prompt if body.get("raw") else None
        messages = []
        if body.get("system"):
            messages.append({"role": "system", "content": body["system"]})
        try:
            media = parse_ollama_media(body)
        except MediaError as exc:
            raise HTTPException(400, str(exc)) from None
        messages.append({"role": "user", "content": prompt, **media})
        if media and raw:
            raise HTTPException(400, "raw prompts cannot carry images or audio")
        messages = _fit_media(name, capabilities_of(name), messages)
        opts = gen_options(body.get("options"))

        def shape(ev):
            if ev["type"] == "token":
                return {"model": name, "created_at": _now(), "response": ev["text"], "done": False}
            return None

        def final(text, stats, reason):
            return {"model": name, "created_at": _now(), "response": text, "done": True,
                    "done_reason": reason, **_ollama_stats(stats)}

        return await _run_generation(name, messages if raw else with_system(messages), opts, raw,
                                     body.get("stream", True), shape, final)

    @app.post("/api/create")
    @app.post("/api/copy")
    @app.post("/api/push")
    async def unsupported():
        raise HTTPException(501, "not supported by AirLLM Studio")

    # =========================================================================================
    # OpenAI-compatible API
    # =========================================================================================
    def _oai_error(message: str, status: int = 400, code: str = "invalid_request_error"):
        return JSONResponse({"error": {"message": message, "type": code, "code": code}}, status_code=status)

    @app.get("/v1/models")
    def oai_models():
        return {"object": "list", "data": [
            {"id": m.name, "object": "model", "owned_by": "airllm",
             "created": int(datetime.fromisoformat(m.created_at).timestamp())}
            for m in studio.store.list() if m.status == "ready"]}

    async def _oai_generate(body: dict, chat_mode: bool):
        name = body.get("model")
        if not name or studio.store.get(name) is None:
            return _oai_error(f"model '{name}' not found", 404, "model_not_found")
        name = studio.store.get(name).name
        if chat_mode:
            try:
                messages = with_system(_fit_media(name, capabilities_of(name),
                                                  _clean_messages(body.get("messages") or [])))
            except HTTPException as exc:
                return _oai_error(exc.detail)
            raw = None
        else:
            prompt = body.get("prompt") or ""
            if isinstance(prompt, list):
                prompt = prompt[0] if prompt else ""
            messages, raw = [{"role": "user", "content": prompt}], prompt
        opts = gen_options(max_new_tokens=body.get("max_completion_tokens") or body.get("max_tokens"),
                           temperature=body.get("temperature"), top_p=body.get("top_p"),
                           seed=body.get("seed"), stop=body.get("stop"))
        cancel = threading.Event()
        factory = lambda: studio.engine.stream(name, messages, opts, cancel, raw)  # noqa: E731
        created = int(time.time())
        rid = ("chatcmpl-" if chat_mode else "cmpl-") + os.urandom(12).hex()
        finish_map = {"stop": "stop", "length": "length", "cancelled": "stop"}

        def usage(stats):
            p, c = stats.get("prompt_tokens", 0), stats.get("completion_tokens", 0)
            return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}

        if body.get("stream"):
            include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
            obj = "chat.completion.chunk" if chat_mode else "text_completion"

            def chunk(delta_or_text, finish=None):
                choice = ({"index": 0, "delta": delta_or_text, "finish_reason": finish} if chat_mode
                          else {"index": 0, "text": delta_or_text, "finish_reason": finish})
                return {"id": rid, "object": obj, "created": created, "model": name, "choices": [choice]}

            def event(payload) -> str:
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            async def sse():
                if chat_mode:
                    yield event(chunk({"role": "assistant", "content": ""}))
                try:
                    async for ev in _stream_blocking(factory, cancel):
                        if ev["type"] == "token":
                            yield event(chunk({"content": ev["text"]} if chat_mode else ev["text"]))
                        elif ev["type"] == "done":
                            yield event(chunk({} if chat_mode else "", finish_map[ev["done_reason"]]))
                            if include_usage:
                                yield event({"id": rid, "object": obj, "created": created, "model": name,
                                             "choices": [], "usage": usage(ev["stats"])})
                except Exception as exc:  # noqa: BLE001
                    log.exception("generation failed")
                    yield event({"error": {"message": _error_text(exc), "type": "server_error"}})
                yield "data: [DONE]\n\n"

            return StreamingResponse(sse(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        text, stats, reason = [], {}, "stop"
        try:
            async for ev in _stream_blocking(factory, cancel):
                if ev["type"] == "token":
                    text.append(ev["text"])
                elif ev["type"] == "done":
                    stats, reason = ev["stats"], ev["done_reason"]
        except (EngineError, StoreError) as exc:
            return _oai_error(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("generation failed")
            return _oai_error(_error_text(exc), 500, "server_error")
        content = "".join(text)
        if chat_mode:
            choice = {"index": 0, "message": {"role": "assistant", "content": content},
                      "finish_reason": finish_map[reason]}
            return {"id": rid, "object": "chat.completion", "created": created, "model": name,
                    "choices": [choice], "usage": usage(stats)}
        return {"id": rid, "object": "text_completion", "created": created, "model": name,
                "choices": [{"index": 0, "text": content, "finish_reason": finish_map[reason]}],
                "usage": usage(stats)}

    @app.post("/v1/chat/completions")
    async def oai_chat(request: Request):
        return await _oai_generate(await request.json(), chat_mode=True)

    @app.post("/v1/completions")
    async def oai_completions(request: Request):
        return await _oai_generate(await request.json(), chat_mode=False)

    # =========================================================================================
    # Studio API (used by the desktop UI)
    # =========================================================================================
    @app.get("/api/studio/status")
    def studio_status():
        models_dir = studio.settings.models_dir()
        try:
            disk = shutil.disk_usage(models_dir)
            disk_info = {"total": disk.total, "free": disk.free}
        except OSError:
            disk_info = {}
        return {
            "version": __version__, "airllm": _airllm_version(), "python": sys.version.split()[0],
            "platform": sys.platform, "uptime": time.time() - studio.started_at,
            "engine": studio.engine.status(), "hardware": studio.engine.hardware(),
            "device": studio.engine.resolve_device() if studio.engine._torch_info else None,
            "models_dir": str(models_dir), "data_dir": str(data_dir()), "disk": disk_info,
            "api_key_required": bool(studio.api_key),
            "jobs": [j.state() for j in studio.store.jobs.values() if not j.done],
        }

    @app.get("/api/studio/settings")
    def get_settings():
        data = studio.settings.settings.to_dict(redact=True)
        data["models_dir_effective"] = str(studio.settings.models_dir())
        return data

    @app.put("/api/studio/settings")
    async def put_settings(request: Request):
        local_only(request)
        patch = await request.json()
        if "hf_token" in patch and patch["hf_token"] == "":
            patch["hf_token"] = None          # empty = keep the stored token
        if patch.get("clear_hf_token"):
            patch["hf_token"] = ""
        patch.pop("clear_hf_token", None)
        try:
            studio.settings.update(patch)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return get_settings()

    @app.get("/api/studio/models")
    def studio_models():
        jobs = {name: job.state() for name, job in studio.store.jobs.items()}
        out = []
        for m in studio.store.list():
            item = studio.store.ensure_capabilities(m).to_dict()
            item["job"] = jobs.pop(m.name, None)
            item["loaded"] = studio.engine.model_name == m.name
            out.append(item)
        return {"models": out}

    @app.post("/api/studio/models/pull")
    async def studio_pull(request: Request):
        body = await request.json()
        job = start_pull(request, body.get("name", ""), body)
        return job.state()

    @app.post("/api/studio/models/cancel")
    async def studio_cancel(request: Request):
        body = await request.json()
        return {"cancelled": studio.store.cancel(body.get("name", ""))}

    @app.post("/api/studio/models/load")
    async def studio_load(request: Request):
        body = await request.json()
        name = require_model(body.get("name"))
        try:
            await asyncio.to_thread(studio.engine.load, name)
        except EngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("load failed")
            raise HTTPException(500, _error_text(exc)) from exc
        return studio.engine.status()

    @app.post("/api/studio/models/unload")
    async def studio_unload():
        await asyncio.to_thread(studio.engine.unload)
        return studio.engine.status()

    @app.get("/api/studio/catalog")
    def catalog():
        installed = {m.name.lower(): m.status for m in studio.store.list()}
        return {"models": [{**c, "installed": installed.get(c["name"].lower())} for c in CATALOG]}

    @app.get("/api/studio/search")
    async def search(q: str = "", limit: int = 20):
        q = q.strip()
        if len(q) < 2:
            return {"models": []}

        def run():
            from huggingface_hub import HfApi

            api = HfApi(token=studio.settings.hf_token())
            results = api.list_models(search=q, pipeline_tag="text-generation", sort="downloads",
                                      limit=min(max(limit, 1), 50))
            return [{"name": r.id, "downloads": getattr(r, "downloads", 0) or 0,
                     "likes": getattr(r, "likes", 0) or 0,
                     "gated": bool(getattr(r, "gated", False)),
                     "gguf": "gguf" in (getattr(r, "tags", None) or [])} for r in results]

        try:
            return {"models": await asyncio.to_thread(run)}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Hugging Face search failed: {_error_text(exc)}") from exc

    # --- chats ---------------------------------------------------------------------------
    @app.get("/api/studio/chats")
    def list_chats():
        return {"chats": studio.chats.list()}

    @app.post("/api/studio/chats")
    async def create_chat(request: Request):
        body = await request.json()
        return studio.chats.create(body.get("title", ""), body.get("model", ""), body.get("messages"),
                                   project_id=body.get("project_id"))

    @app.get("/api/studio/chats/{chat_id}")
    def get_chat(chat_id: str):
        chat = studio.chats.get(chat_id)
        if chat is None:
            raise HTTPException(404, "chat not found")
        return chat

    @app.patch("/api/studio/chats/{chat_id}")
    async def update_chat(chat_id: str, request: Request):
        body = await request.json()
        chat = studio.chats.update(chat_id, body.get("title"), body.get("model"), body.get("messages"),
                                   project_id=body["project_id"] if "project_id" in body else UNSET)
        if chat is None:
            raise HTTPException(404, "chat not found")
        return chat

    @app.delete("/api/studio/chats/{chat_id}")
    def delete_chat(chat_id: str):
        if not studio.chats.delete(chat_id):
            raise HTTPException(404, "chat not found")
        return {"deleted": True}

    @app.delete("/api/studio/chats")
    def clear_chats():
        return {"deleted": studio.chats.clear()}

    # --- projects ------------------------------------------------------------------------
    def _project_or_404(project_id: str) -> dict:
        project = studio.chats.get_project(project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        return project

    @app.get("/api/studio/projects")
    def list_projects():
        return {"projects": studio.chats.list_projects()}

    @app.post("/api/studio/projects")
    async def create_project(request: Request):
        body = await request.json()
        return studio.chats.create_project(body.get("name", ""), body.get("instructions", ""),
                                           body.get("model", ""))

    @app.get("/api/studio/projects/{project_id}")
    def get_project(project_id: str):
        return _project_or_404(project_id)

    @app.patch("/api/studio/projects/{project_id}")
    async def update_project(project_id: str, request: Request):
        body = await request.json()
        project = studio.chats.update_project(project_id, body.get("name"), body.get("instructions"),
                                              body.get("model"))
        if project is None:
            raise HTTPException(404, "project not found")
        return project

    @app.delete("/api/studio/projects/{project_id}")
    def delete_project(project_id: str):
        deleted = studio.chats.delete_project(project_id)
        if deleted is None:
            raise HTTPException(404, "project not found")
        return {"deleted": True, "deleted_chats": deleted}

    @app.post("/api/studio/projects/{project_id}/files")
    async def add_project_file(project_id: str, request: Request, name: str = ""):
        """Raw file body (any content type); the file name comes in ?name=."""
        _project_or_404(project_id)
        data = bytearray()
        async for chunk in request.stream():   # bounded read: Content-Length may be absent or wrong
            data += chunk
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "file too large")
        return studio.chats.add_file(project_id, name or "file.txt", bytes(data))

    @app.get("/api/studio/projects/{project_id}/files/{file_id}")
    def get_project_file(project_id: str, file_id: str):
        f = studio.chats.get_file(project_id, file_id)
        if f is None:
            raise HTTPException(404, "file not found")
        return f

    @app.delete("/api/studio/projects/{project_id}/files/{file_id}")
    def delete_project_file(project_id: str, file_id: str):
        if not studio.chats.delete_file(project_id, file_id):
            raise HTTPException(404, "file not found")
        return {"deleted": True}

    # --- desktop helpers -----------------------------------------------------------------
    @app.post("/api/studio/open-folder")
    async def open_folder(request: Request):
        local_only(request)
        body = await request.json()
        folder = {"models": studio.settings.models_dir(), "logs": logs_dir(),
                  "data": data_dir()}.get(body.get("what", "models"))
        if folder is None:
            raise HTTPException(400, "unknown folder")
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise HTTPException(500, f"could not open {folder}: {exc}") from exc
        return {"path": str(folder)}

    @app.post("/api/shutdown")
    async def shutdown(request: Request):
        local_only(request)
        if studio.shutdown_hook:
            asyncio.get_running_loop().call_later(0.2, studio.shutdown_hook)
        return {"stopping": True}

    # --- web UI --------------------------------------------------------------------------
    if WEB_DIR.exists():
        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

        app.mount("/", StaticFiles(directory=str(WEB_DIR)), name="web")

    return app
