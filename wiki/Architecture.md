# Architecture

How AirLLM Studio is put together, from the process layout down to one token. Useful for contributors, integrators and anyone who wants to know what runs on their machine.

## The big picture

```text
 you ──► desktop window ─┐                          ┌──────────────────────────────────┐
         (Chromium app    │      HTTP, 127.0.0.1    │ airllm serve  (FastAPI + uvicorn) │
          window / tab)   ├───────────────────────► │  request guard ► API handlers     │
 you ──► airllm CLI ──────┤        :11435           │   /api   Ollama      /v1  OpenAI  │
 apps ─► Ollama/OpenAI ───┘                         │   /api/studio  (the web UI)       │
         clients                                    │            │                      │
                                                    │   ┌────────▼───────┐ ┌──────────┐│
                                                    │   │ Engine         │ │ ModelStore││
                                                    │   │ one model,     │ │ pulls,    ││
                                                    │   │ one generation │ │ manifests ││
                                                    │   │ at a time      │ └─────┬────┘│
                                                    │   └────────┬───────┘       │     │
                                                    │            │          ChatStore   │
                                                    └────────────┼──────────(SQLite)───┘
                                                                 ▼
                                              AirLLM ──► per-layer files on disk ──► CPU / GPU
```

There is **one server process**. The window, the CLI and third-party clients are all just HTTP clients of it, which is why the same models, chats and settings are visible everywhere and why quitting the window does not stop the server.

## Components

| Module (`airllm_studio/`) | Role |
|---|---|
| `cli.py`, `client.py` | The `airllm` command. `client.py` is a small HTTP client that also starts a background server when none answers |
| `desktop.py` | Opens the UI in a Chromium "app" window (or the default browser); on Windows runs the tray icon (`pystray`) around the server |
| `server.py` | FastAPI application: Ollama API, OpenAI API, Studio API, static web UI, the idle-unload thread |
| `security.py` | Request guard: `Host` allow-list, `Origin` / `Sec-Fetch-Site` checks, API-key comparison ([Security](Security)) |
| `engine.py` | Loads one AirLLM model, generates, streams tokens, queues requests, reports layer progress |
| `store.py` | Model library: Hugging Face pulls, folder import, layer splitting, manifests, capability detection, custom-code gate |
| `chats.py` | SQLite store for chats, projects and project files |
| `media.py` | Decoding and limits for images and audio in requests |
| `config.py` | Data folder, host parsing, `settings.json`, the CUDA-overlay path hook |
| `catalog.py` | The "Suggested" models list |
| `web/` | The UI: plain HTML, CSS and JavaScript, no build step, no framework, no external requests |

Dependencies are deliberately few: `airllm`, `fastapi`, `uvicorn`, `huggingface-hub`, `pillow` (and `pystray` on Windows). PyTorch and `transformers` come with AirLLM.

## What a model is on disk

```text
models/
├── hub/…                         Hugging Face download (snapshot with weights + config + tokenizer)
├── layers/<org>--<name>/
│   └── splitted_model/           AirLLM's per-layer files (suffix .4bit / .8bit when compressed)
└── manifests/<org>--<name>.json  status, sizes, architecture, capabilities, trust permission
```

AirLLM cannot stream a normal checkpoint efficiently, so each model is converted once into **one file per transformer layer**. Reading a layer, applying it and dropping it is the unit of work at run time. This one-time conversion is the *preparing* phase of a pull, and it needs about the model's size in extra disk space.

## Pulling a model

1. **Resolve.** Name is `org/name` (Hugging Face) or a folder on this computer (local callers only).
2. **Choose files.** Weights (`.safetensors`, else `.bin`), `config.json`, tokenizer and processor files. A repo with only GGUF files, or no `config.json`, is rejected with an explanation. The model's own `.py` files are **not** downloaded unless the user allowed custom code.
3. **Gate custom code.** `auto_map` references in config/tokenizer/processor files must be allowed by the user.
4. **Download** with `huggingface_hub`. Progress comes from the library's own progress bars (the newer Xet downloader writes its partial files late, so counting bytes on disk would stall).
5. **Prepare.** AirLLM's `split_and_save_layers` writes the per-layer files, optionally compressed. Multi-shard originals can then be deleted to halve disk use.
6. **Detect capabilities** (images, audio) and write the manifest as `ready`.

Jobs run in background threads, can be cancelled, survive the window closing, and a job interrupted by a crash is marked as such at the next start. Events are streamed to the UI, the CLI and `/api/pull`.

## Generating an answer

1. **Guard and routing.** The request passes the guard, then the Ollama, OpenAI or Studio handler normalises messages (including images/audio) to one internal shape. Project instructions and files are put in the system message, cut to about half the context.
2. **Queue.** The engine has a single generation lock: other requests wait and are told they are queued.
3. **Load.** If another model is loaded, it is unloaded first (GPU cache cleared). AirLLM's `AutoModel.from_pretrained` is called with the device, the layer folder and the context length; on CPU in `float32`, since bf16 is slow or incomplete on many CPUs.
4. **Encode.** The tokenizer's chat template renders the conversation. If it exceeds *Context length minus Max answer length*, the **oldest non-system turns are dropped first**; system messages (instructions, project files) and the newest message are kept. Multimodal turns go through the model's own processor.
5. **Generate** in a worker thread with `transformers`' streamer. For every token AirLLM loads each layer from disk, runs it, and frees it. Forward hooks on the layers feed the **layer meter**. A stopping criterion checks the cancel flag, so closing the connection or pressing Stop ends generation at the next token.
6. **Stream out.** Text pieces are filtered for stop strings (a tail that might start one is held back), then written as newline-delimited JSON (Ollama), Server-Sent Events (OpenAI) or the UI's stream. The final event carries token counts, durations and speed.
7. **Idle.** After *Unload when idle* minutes without requests a background thread unloads the model.

## Capabilities: images and voice

A model is tagged *vision* or *audio* only when **three** things agree: its `config.json` declares the encoder, AirLLM's class for that architecture keeps the encoder **resident** in memory (otherwise the weights would stay on the meta device and fail), and a processor ships with the model. Text-only configs never trigger AirLLM class loading, which keeps pulls cheap and avoids running model code unnecessarily. Studio never converts one kind of input into another (no OCR, no speech-to-text). See [Images and Voice](Images-and-Voice).

## Packaging architecture

The release is a **self-contained payload**: a private CPython (python-build-standalone), CPU-only PyTorch and torchvision, `transformers`, AirLLM and AirLLM Studio, installed under `/opt/airllm` (Linux) or the install folder (Windows). Launchers (`airllm`, `airllm-python`, `airllm-enable-cuda`) call that interpreter. Nothing touches the system Python.

CUDA is an **overlay**: `airllm-enable-cuda` installs a CUDA build of torch/torchvision into a separate folder that the launchers (and, for entry points that skip them, `config.apply_cuda_overlay`) put first on `sys.path`. Package upgrades never overwrite the overlay. How it is built and released: [Build and Release Pipeline](Build-and-Release-Pipeline).

## Design decisions

| Decision | Reason |
|---|---|
| One server, many thin clients | One loaded model and one set of data, whatever front end you use |
| One generation at a time | AirLLM runs one model per process and is disk-bound; parallel requests would only fight for the disk |
| Port 11435 | Next to Ollama's 11434, so both can run |
| Loopback by default, no accounts | A personal tool should be safe without configuration; sharing is an explicit, documented step ([Security](Security)) |
| Web UI without a framework or CDN | Works offline, nothing to build, small and auditable |
| CPU PyTorch in the package | Keeps downloads well under GitHub's 2 GiB asset limit and works everywhere; CUDA is one command ([GPU and CUDA](GPU-and-CUDA)) |
| Wrap AirLLM, do not fork it | Studio uses AirLLM's public entry points; new model families arrive by packaging new AirLLM releases automatically |
| Per-model permission for custom code | AirLLM always enables `trust_remote_code`; the gate sits in front of it |
