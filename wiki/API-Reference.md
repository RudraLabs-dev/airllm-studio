# API Reference

AirLLM Studio runs a local HTTP server, by default at `http://127.0.0.1:11435`, with three families of endpoints:

| Family | For | Where |
|---|---|---|
| **Ollama-compatible** | Ollama clients and libraries, Open WebUI, scripts | `/api/...` |
| **OpenAI-compatible** | the OpenAI SDKs and tools built on them | `/v1/...` |
| **Studio** | the desktop app (models, chats, projects, settings) | `/api/studio/...` |

An interactive reference of every endpoint is served at **`/docs`** (for example http://127.0.0.1:11435/docs). The server handles **one generation at a time**; additional requests wait their turn.

## Connecting a client

| Client setting | Value |
|---|---|
| Ollama host | `http://127.0.0.1:11435` |
| OpenAI base URL | `http://127.0.0.1:11435/v1` |
| API key | not needed from the same computer; any non-empty string if the client insists. For remote use see [Server Mode](Server-Mode) |
| Model name | exactly as listed by `airllm list` / `GET /api/tags`, e.g. `Qwen/Qwen3-8B` |

Requests must name an **installed** model; otherwise the answer is `404 model '...' not found, try pulling it first`.

Browser-based tools (a web page calling the API from your browser) are subject to the origin rules in [Security](Security): list their origin in `AIRLLM_ORIGINS`.

## Ollama-compatible endpoints

| Endpoint | Notes |
|---|---|
| `GET /api/version` | `{"version": "<studio>", "airllm": "<airllm>"}` |
| `GET /api/tags` | Installed models (name, size on disk, details) |
| `GET /api/ps` | The loaded model |
| `POST /api/show` | Model details, context length and `capabilities` (`completion`, `vision`, `audio`) |
| `POST /api/chat` | Chat. Streams newline-delimited JSON by default; `"stream": false` for one JSON answer. An empty `messages` list loads the model; with `"keep_alive": 0` it unloads it |
| `POST /api/generate` | Single prompt (optionally `system`, `raw`). An empty prompt loads the model; with `"keep_alive": 0` it unloads it |
| `POST /api/pull` | Download + prepare a model: `{"model": "Qwen/Qwen3-8B"}`; streams progress (`"stream": false` waits and returns the final status). Add `"trust_remote_code": true` to allow model code. A folder on disk can only be imported by a caller on the same computer |
| `DELETE /api/delete` | Delete a model: `{"model": "Qwen/Qwen3-8B"}` |
| `/api/create`, `/api/copy`, `/api/push` | Answer `501 not supported by AirLLM Studio` |

Options accepted in `options`: `num_predict` (max new tokens), `temperature`, `top_p`, `seed`, `stop`, `num_ctx` (context length). Anything else is ignored. Defaults come from Settings.

```sh
curl http://127.0.0.1:11435/api/chat -d '{
  "model": "Qwen/Qwen3-8B",
  "stream": false,
  "options": {"num_predict": 200, "temperature": 0.3},
  "messages": [{"role": "user", "content": "Give me three uses for a Raspberry Pi."}]
}'
```

The final message carries `done`, `done_reason` and Ollama's timing and token counts (`prompt_eval_count`, `eval_count`, `eval_duration`, ...); `/api/chat` adds `tokens_per_second`.

Studio extensions on `/api/chat` (ignored by other servers): `"airllm_project": "<id>"` applies a [project](Projects)'s instructions and files; `"airllm_progress": true` adds a `progress` object (`layer`, `layers`, `tokens`) to the stream, which is what the layer meter uses.

## OpenAI-compatible endpoints

| Endpoint | Notes |
|---|---|
| `GET /v1/models` | Installed models |
| `POST /v1/chat/completions` | Streaming (`"stream": true`, Server-Sent Events) and not. `stream_options.include_usage` supported |
| `POST /v1/completions` | Text completion |

Parameters: `max_tokens` or `max_completion_tokens`, `temperature`, `top_p`, `seed`, `stop`. Responses include a `usage` block. Other OpenAI parameters (tools, `n`, logprobs, ...) are ignored.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:11435/v1", api_key="not-needed")
reply = client.chat.completions.create(
    model="Qwen/Qwen3-8B",
    messages=[{"role": "user", "content": "Explain layer streaming in one paragraph."}],
)
print(reply.choices[0].message.content)
```

Errors from these endpoints use OpenAI's shape: `{"error": {"message": ..., "type": ..., "code": ...}}`, for example `404` with code `model_not_found`. (Refusals by the request guard and the API-key check are plain `{"error": "..."}`.)

## Images and audio in requests

| Style | Images | Audio |
|---|---|---|
| Ollama | `"images": ["<base64>", ...]` on a message (or on `/api/generate`) | `"audio": ["<base64 WAV>"]` |
| OpenAI | content part `{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}` | `{"type": "input_audio", "input_audio": {"data": "<base64>", "format": "wav"}}` |

Images can also be plain base64 or `data:` URLs. Audio must be a PCM **WAV** file. Only models with the matching capability accept them ([Images and Voice](Images-and-Voice)); a request that attaches media to a model without it fails with a clear `400`. (Media in *older* turns of a conversation is replaced by a placeholder, so a chat can switch to a text-only model.) Limits: 20 MB per image, 25 MB and 5 minutes per audio clip, 8 items per message. Remote `http(s)` URLs are refused: the server never fetches URLs for you.

## Studio endpoints (used by the app)

These can change between versions; prefer the Ollama/OpenAI endpoints for integrations. Highlights:

| Endpoint | Purpose |
|---|---|
| `GET /api/studio/status` | version, hardware, device, loaded model, free disk, running jobs |
| `GET /api/studio/settings`, `PUT /api/studio/settings` | settings ([Configuration](Configuration)); changing them is **local computer only**, and the Hugging Face token is write-only |
| `GET /api/studio/models`, `POST .../models/pull`, `.../cancel`, `.../load`, `.../unload` | model library and pull jobs |
| `GET /api/studio/catalog`, `GET /api/studio/search?q=` | suggested models; Hugging Face text-generation search (`502` if Hugging Face cannot be reached) |
| `GET/POST /api/studio/chats`, `GET/PATCH/DELETE /api/studio/chats/{id}`, `DELETE /api/studio/chats` (all chats) | saved chats |
| `GET/POST /api/studio/projects`, `GET/PATCH/DELETE /api/studio/projects/{id}` | [projects](Projects) |
| `POST /api/studio/projects/{id}/files?name=<file name>` | upload a project file (the raw bytes as the request body; 2 MB request limit) |
| `GET/DELETE /api/studio/projects/{id}/files/{file_id}` | read or remove a project file |
| `POST /api/studio/open-folder`, `POST /api/shutdown` | open the models, logs or data folder; stop the server. **Local computer only** |

## Status codes

`200` success; `400` bad request (an `error` field explains: media not supported, model needs custom-code permission, `Host` header not in the allow-list...); `401` missing or invalid API key from a remote client; `403` origin not allowed, or a local-only endpoint called from another computer; `404` unknown model, chat, project or file; `413` upload too large; `500` generation or model-load failure; `501` Ollama endpoints that do not apply; `502` Hugging Face search failed.
