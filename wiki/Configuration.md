# Configuration

Two layers: **settings** you change in the app (stored in `settings.json`), and **environment variables** for the things that must be known before the server starts (addresses, keys, folders). Environment variables win where both exist.

## Where everything lives

Under the **data folder**, `~/.airllm` on Linux and `%USERPROFILE%\.airllm` on Windows (change it with `AIRLLM_HOME`). The Linux service uses `/var/lib/airllm-server` instead ([Server Mode](Server-Mode)).

```text
~/.airllm/
├── settings.json          your settings (owner-only permissions; holds the Hugging Face token)
├── chats.db               chats and projects (SQLite)
├── logs/
│   ├── server.log         the background server
│   └── app.log            output of the windowless Windows launcher
└── models/                (default) all downloaded models
    ├── hub/               Hugging Face download cache
    ├── layers/<model>/    AirLLM's per-layer files, the thing that is streamed at run time
    └── manifests/         one small JSON file per model (status, size, capabilities, permissions)
```

The program itself is separate and replaced on upgrade: `/opt/airllm` (Linux) or the install folder (Windows, normally `C:\Program Files\AirLLM`). The optional CUDA overlay is `/var/lib/airllm/cuda-site` or `<install folder>\cuda-site` ([GPU and CUDA](GPU-and-CUDA)).

**Back up** `settings.json` and `chats.db`; models can be downloaded again. **Reset**: quit AirLLM and delete the data folder.

**Putting models on a bigger disk.** Set *Models folder* (or `AIRLLM_MODELS`) *before* you download models. Changing it later does **not** move or re-link anything: the model list is read from the new folder, so models in the old one disappear from the list (their files stay where they are) and have to be pulled again. Each model's record stores absolute paths, so copying the `models` folder by hand does not work either. If you want to keep the old downloads, point the old location at the new disk instead (a symbolic link or a mount at the same path).

## Settings (in the app)

All are on the **Settings** page; press **Save changes**. The same values are in `settings.json` and over `GET/PUT /api/studio/settings`.

| Setting (UI label) | JSON key | Default | Notes |
|---|---|---|---|
| System prompt | `defaults.system_prompt` | empty | Added to every chat; project instructions follow it |
| Max answer length | `defaults.max_new_tokens` | 512 | Per-request override: `options.num_predict` / `max_tokens` |
| Temperature | `defaults.temperature` | 0.7 | |
| Top-p | `defaults.top_p` | 0.9 | |
| Context length | `defaults.context_length` | 4096 | Memory and time grow with it; `options.num_ctx` overrides per request |
| Run models on | `device` | `auto` | `auto` (GPU if PyTorch sees one, else CPU), `cpu`, or `cuda:N` |
| Layer compression | `compression` | `none` | `none`, `8bit`, `4bit`. Applied when a model is prepared; needs `bitsandbytes` ([Models and Performance](Models-and-Performance)) |
| Unload when idle (minutes) | `keep_alive_minutes` | 30 | 0 = never unload automatically |
| Models folder | `models_dir` | empty (`<data>/models`) | |
| Delete original download... | `delete_original` | off | Frees disk after preparing |
| Hugging Face access token | `hf_token` | empty | Write-only; never shown again |

Changes to generation defaults apply to the next answer; device and compression apply to the next model **load**. A damaged `settings.json` is moved aside as `settings.json.bad` and defaults are used, so the server always starts.

## Environment variables

Set them in your shell, the Windows "Environment Variables" dialog, a systemd drop-in, or a service `EnvironmentFile`.

| Variable | Meaning | Default |
|---|---|---|
| `AIRLLM_HOME` | Data folder | `~/.airllm` |
| `AIRLLM_MODELS` | Models folder; overrides the setting | `<data>/models` |
| `AIRLLM_HOST` | Address the **server listens on** and the **CLI connects to**: `host`, `host:port`, `:port` or a URL | `127.0.0.1:11435` |
| `AIRLLM_API_KEY` | Server: clients on other computers must send `Authorization: Bearer <key>`. CLI: the key it sends | unset |
| `AIRLLM_ORIGINS` | Extra browser origins allowed to call the API, comma-separated (`*` = any, not recommended) | none |
| `AIRLLM_ALLOWED_HOSTS` | Extra host names the server may be reached by, comma-separated | none |
| `AIRLLM_FORCE_CPU` | Any value: ignore the CUDA overlay and use the bundled CPU PyTorch | unset |
| `HF_TOKEN` | Hugging Face token, used when none is saved in Settings | unset |

`airllm serve --host` overrides `AIRLLM_HOST` for that run. See [Security](Security) for what the key and the allow-lists protect.

Standard Hugging Face and PyTorch variables (`HF_ENDPOINT` for a mirror, `HTTPS_PROXY` for a corporate proxy, `CUDA_VISIBLE_DEVICES` to hide GPUs) are honoured by the libraries Studio uses. They are not specific to Studio and are not tested here, so verify them in your setup.

## Ports and URLs

| What | Address |
|---|---|
| Web UI | `http://127.0.0.1:11435/` |
| Interactive API docs | `http://127.0.0.1:11435/docs` |
| Ollama API | `http://127.0.0.1:11435/api/...` |
| OpenAI API | `http://127.0.0.1:11435/v1/...` |

The default port 11435 differs from Ollama's 11434 on purpose, so both can run side by side. To use another port: `AIRLLM_HOST=127.0.0.1:8080`.

## Files you should not edit by hand

`chats.db` and `manifests/*.json` are managed by the app. Edit them only with the app stopped, and keep a copy.
