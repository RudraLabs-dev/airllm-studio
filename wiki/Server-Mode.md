# Server Mode

By default AirLLM Studio is a **personal** app: the window and the CLI start a server on `127.0.0.1:11435` when you need it, and only programs on your own computer can reach it. **Server mode** is for the other cases: a GPU workstation that other machines use, a home server, a shared lab box.

> Read [Security](Security) before listening on anything other than `127.0.0.1`. The server has **no user accounts**: one shared API key is the only access control.

## What runs where

| Part | Notes |
|---|---|
| One server process | Loads **one model at a time**. Requests are served **one at a time** in order; others wait ([Models and Performance](Models-and-Performance)) |
| Web UI | Served at `/` by the same process. It has **no field for an API key**, so with a key set it only works from the server computer itself ([see below](#using-the-server-from-another-computer)) |
| API | Ollama-compatible (`/api`) and OpenAI-compatible (`/v1`), see [API Reference](API-Reference) |
| Data | Models, settings, chats and projects of the account running the server ([Configuration](Configuration)) |

## Linux: the systemd service

The `.deb` and `.rpm` install `airllm.service`. It is **not enabled by default**.

```sh
sudo systemctl enable --now airllm        # start now and at every boot
systemctl status airllm
journalctl -u airllm -f                   # live log
```

The unit runs `airllm serve` as a throw-away system user (`DynamicUser`), keeps all data in **`/var/lib/airllm-server`** (models, settings, chats), and is sandboxed: read-only system, no access to home folders, private `/tmp`, no new privileges. Out of the box it listens only on `127.0.0.1:11435`.

> The service has its **own** data folder. Models you pulled as a desktop user live in `~/.airllm` and are not visible to it. Pull models for the service with `AIRLLM_HOST` pointing at it, or via its web UI/API.

### Open it to the network

Create a drop-in with `sudo systemctl edit airllm`:

```ini
[Service]
Environment=AIRLLM_HOST=0.0.0.0:11435
Environment=AIRLLM_ALLOWED_HOSTS=gpu-box.lan
EnvironmentFile=/etc/airllm/server.env
```

and put the key in a root-only file:

```sh
sudo install -d -m 755 /etc/airllm
sudo sh -c 'umask 077; echo "AIRLLM_API_KEY=$(openssl rand -hex 32)" > /etc/airllm/server.env'
sudo systemctl restart airllm
```

| Setting | Why |
|---|---|
| `AIRLLM_HOST=0.0.0.0:11435` | listen on all interfaces. A specific address or name (`192.168.1.20:11435`) is safer |
| `AIRLLM_API_KEY` | **required in practice**: without it every computer that can reach the port may use the API. The server logs a warning when it starts like that |
| `AIRLLM_ALLOWED_HOSTS` | host *names* clients will type (`gpu-box.lan`). IP addresses always work. Needed for names because of [DNS-rebinding protection](Security) |

Then open the firewall for that port only for the networks you trust, for example `sudo ufw allow from 192.168.1.0/24 to any port 11435`.

### GPU

The service uses the same CUDA overlay as the desktop app: run `sudo airllm-enable-cuda` once, then `sudo systemctl restart airllm`. `airllm status` shows what the server uses (see below).

## Windows and desktop installs

You can also run `airllm serve` yourself (for example from Task Scheduler or NSSM) with the same environment variables. On a desktop the usual approach is the app plus tray icon; server mode is meant for Linux hosts.

## Using the server from another computer

From a client machine:

```sh
export AIRLLM_HOST=gpu-box.lan:11435
export AIRLLM_API_KEY=<the key>
airllm list                       # the CLI now talks to the remote server
airllm run Qwen/Qwen3-8B "Hello"
```

Other tools use the API directly with `Authorization: Bearer <key>`:

```sh
curl http://gpu-box.lan:11435/api/tags -H "Authorization: Bearer $AIRLLM_API_KEY"
```

OpenAI SDKs: `base_url="http://gpu-box.lan:11435/v1"`, `api_key=<the key>`. Open WebUI: add an Ollama connection to `http://gpu-box.lan:11435`.

> **The built-in web UI cannot be used from another computer once an API key is set**: the page loads, but its requests are answered with `401 missing or invalid API key`, because the UI cannot send a key. Remote users should use the CLI, the SDKs or a client such as Open WebUI. If they need the AirLLM web UI itself, put an authenticating reverse proxy in front (next section) and keep the key for direct API clients.

### What a remote client can and cannot do

| Allowed with the key | Only from the server computer itself |
|---|---|
| Chat and generate, list/pull/delete models, saved chats and projects | Changing settings, opening folders, shutting the server down (`airllm stop`), importing a model from a local folder path |

The Hugging Face token is write-only: it can be set from the machine itself and is never sent back.

## Behind a reverse proxy

A proxy such as nginx or Caddy that runs **on the same computer** and forwards to `127.0.0.1:11435` makes every request look like it comes from this computer, so the server treats all of them as local: **no API key is asked for and the local-only actions are open.** If you put a proxy in front:

* enforce authentication in the proxy (basic auth, SSO, mTLS), and
* make the proxy pass the original `Host`, and add the name to `AIRLLM_ALLOWED_HOSTS`, and
* terminate TLS there. The server speaks plain HTTP.

Streaming responses need buffering turned off (`proxy_buffering off;` in nginx).

## Operating it

| Task | How |
|---|---|
| Check state | `airllm status` (add `AIRLLM_HOST`/`AIRLLM_API_KEY` for a remote one); `GET /api/studio/status` |
| Free GPU/RAM when idle | The loaded model is released after `keep_alive_minutes` of inactivity (default 30; 0 = keep forever), see [Configuration](Configuration) |
| Unload now | `curl -X POST http://127.0.0.1:11435/api/generate -d '{"model":"<name>","keep_alive":0}'` |
| Logs | `journalctl -u airllm`; desktop installs write `~/.airllm/logs/server.log` |
| Back up | stop the service and copy `/var/lib/airllm-server` (`settings.json`, `chats.db`, `manifests/`; `models/` only if you do not want to re-download) |
| Upgrade | Install the new package. The service is restarted if it was running |

Capacity planning: because the server answers one request at a time and each token needs a pass over the whole model from disk, a shared AirLLM server suits a few people with patience, not a busy team. Use a fast NVMe disk ([Models and Performance](Models-and-Performance)).
