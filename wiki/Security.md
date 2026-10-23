# Security

AirLLM Studio is designed so that, installed with its defaults, **nothing outside your computer can use it**, and so that the usual ways a *local* AI server gets abused (web pages poking at `localhost`, models that run their own code) are closed by default. This page explains what is protected, how, and what is your responsibility.

## Defaults at a glance

| Area | Default |
|---|---|
| Network | Listens on `127.0.0.1:11435` only |
| Authentication | None needed from this computer; an API key is required of every other computer when `AIRLLM_API_KEY` is set |
| Web pages in your browser | Cannot call the API (origin and `Host` checks) |
| Models with their own Python code | Refused until you allow them, per model |
| Settings, shutdown, folders | Only from this computer |
| Telemetry | None. The code contains no analytics or update check |
| Your data | Stays in `~/.airllm` (Windows: `%USERPROFILE%\.airllm`). Not encrypted, but not shared |

## The request guard

Because the server trusts programs on your own machine, a malicious **web page** could try to use it through your browser. Two attacks are blocked for every `/api` and `/v1` request:

1. **Cross-site requests.** Browsers attach an `Origin` header to cross-origin writes and a `Sec-Fetch-Site` header to requests. A request whose origin is not the server itself (and not in `AIRLLM_ORIGINS`) is refused with `403`. This stops a page from, say, triggering generations or deleting models, even when it cannot read the answer.
2. **DNS rebinding.** A hostile domain can be re-pointed at `127.0.0.1` so that a page becomes "same-origin" with the API and can *read* answers. The `Host` header then carries that domain, so requests whose `Host` is not `localhost`, a loopback or IP address, the name the server was started with, or an entry in `AIRLLM_ALLOWED_HOSTS` are refused with `400`.

Programs that are not browsers (curl, the OpenAI/Ollama SDKs, `airllm`) send no `Origin` and are unaffected.

**Allowing a web app** that runs in your browser (a local Open WebUI, your own page): set `AIRLLM_ORIGINS=http://localhost:3000` (comma-separated, exact origins; `*` allows every site and defeats protection 1, so avoid it). **Reaching the server by a name** (`gpu-box.lan`): add it to `AIRLLM_ALLOWED_HOSTS`.

## API key

`AIRLLM_API_KEY` protects `/api` and `/v1` for clients **outside this computer**: they must send `Authorization: Bearer <key>`. The comparison is constant-time. Requests coming from the computer itself never need the key.

* Use a long random key (`openssl rand -hex 32`) and keep it in a root-only file ([Server Mode](Server-Mode)), not in shell history or a world-readable unit file.
* The key is a **shared secret for the whole server**, not a user account: everyone who has it can use the models and see every saved chat and project on that server.
* It travels in clear text over plain HTTP. On anything but a trusted network put TLS in front (reverse proxy or VPN such as WireGuard/Tailscale).
* A reverse proxy running on the same computer makes all requests look local, which switches the key check off. Authenticate in the proxy ([Server Mode](Server-Mode#behind-a-reverse-proxy)).
* The built-in web UI cannot send a key, so it is meant to be used from the computer itself.

## Actions that only work from this computer

| Action | Why |
|---|---|
| Change settings (`PUT /api/studio/settings`) | includes the Hugging Face token and the models folder |
| Open a folder, stop the server | act on the host |
| Import a model from a **folder path** | a remote caller must not be able to make the server read arbitrary paths |

Over the network the Hugging Face token is write-only: the API returns only whether a token is set.

## Models that bring their own code

Some Hugging Face repositories contain Python files that `transformers` runs when the model, tokenizer or processor is loaded (`trust_remote_code`). AirLLM always loads models that way, so a model with custom code would run that code **on your computer with your permissions**.

AirLLM Studio therefore:

* checks `config.json`, `tokenizer_config.json` and the image/audio processor configs for `auto_map` entries (code references, including ones that point to *another* repository);
* **does not download the model's `.py` files** and **refuses to prepare or load the model** until you allow it: *Allow custom code* in the app, `airllm pull <model> --trust-remote-code` on the command line, or `"trust_remote_code": true` in `/api/pull`;
* remembers the permission **per model**, and re-checks on load (so models pulled by older versions are covered too).

Only allow it for publishers and repositories you have reason to trust, ideally after reading the code on the model page. Most mainstream architectures need no custom code.

Also: when a repository offers both formats, Studio takes **`.safetensors`** weights. Python pickle files (`.bin`) can in general execute code when loaded, so prefer safetensors repositories.

## Images and audio

Attachments are decoded in memory with size limits (20 MB per image, 25 MB / 5 minutes per audio clip, 8 per message). The server **never fetches URLs** found in a request (no server-side request forgery): `http(s)` image links are rejected; data must be sent inline. Project uploads are limited too ([Projects](Projects)).

## Your data

| Item | Where | Note |
|---|---|---|
| Chats and projects | `chats.db` (SQLite) | Plain, unencrypted. Anyone who can read your home folder can read them |
| Settings and HF token | `settings.json` | Written atomically with owner-only permissions (`0600`) |
| Models | `models/` | Public weights; large |
| Logs | `logs/` | Server messages and errors (model loads, refused requests, failures) |

Use full-disk encryption if the machine can be lost. A chat is removed with **Delete chat** in its menu in the sidebar, a project with **Delete project** (which also deletes its chats and files); deleting the data folder removes everything.

## Network connections AirLLM Studio makes

Only on your behalf: **Hugging Face** (model downloads, search, gated-model checks, using your token if set) and, when you run `airllm-enable-cuda`, **download.pytorch.org**. Nothing else is contacted, and chat content never leaves the machine except through a server you configured yourself.

## Supply chain of the packages

* Every release asset has a SHA-256 in `SHA256SUMS` and a signed **build provenance attestation** (`gh attestation verify`), see [Installation](Installation#verify-a-download).
* Third-party GitHub Actions in the pipeline are **pinned to full commit SHAs**; Dependabot proposes updates ([Build and Release Pipeline](Build-and-Release-Pipeline)).
* The bundled Python build, the PyTorch index and the nfpm version are pinned in `packaging/versions.env`.
* Windows installers are **not yet code-signed**, which is why SmartScreen may warn. Verify the hash.

## Reporting a vulnerability

Please do not publish exploit details in a public issue. Use the repository's **Security → Report a vulnerability** (private advisory) if it is offered; otherwise open an issue saying you have a security report and ask for a private contact, without technical details. Vulnerabilities in AirLLM itself belong to the [AirLLM project](https://github.com/lyogavin/airllm).

## Hardening checklist for a shared server

- [ ] `AIRLLM_API_KEY` set; key stored root-only
- [ ] TLS in front (proxy or VPN); port not exposed to the internet
- [ ] Firewall limited to trusted networks
- [ ] `AIRLLM_ALLOWED_HOSTS` lists only the names you use; `AIRLLM_ORIGINS` is not `*`
- [ ] Custom-code models only from trusted publishers
- [ ] Disk encryption and backups for the data folder
