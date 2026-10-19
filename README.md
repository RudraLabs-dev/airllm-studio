# AirLLM Studio

**Run large language models on everyday hardware.** AirLLM Studio is a desktop app, command line and local API
server for [AirLLM](https://github.com/lyogavin/airllm), which streams a model through memory one layer at a time,
so 70B-class models can run on a single consumer GPU or even on the CPU, trading speed for memory.
One self-contained installer for Linux and Windows: no Python, pip or CUDA setup.

[![Latest release](https://img.shields.io/github/v/release/RudraLabs-dev/airllm-studio?sort=semver&label=release)](https://github.com/RudraLabs-dev/airllm-studio/releases/latest)
[![Build & release](https://github.com/RudraLabs-dev/airllm-studio/actions/workflows/release.yml/badge.svg)](https://github.com/RudraLabs-dev/airllm-studio/actions/workflows/release.yml)
[![Lint](https://github.com/RudraLabs-dev/airllm-studio/actions/workflows/lint.yml/badge.svg)](https://github.com/RudraLabs-dev/airllm-studio/actions/workflows/lint.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

## Download

**[Latest release →](https://github.com/RudraLabs-dev/airllm-studio/releases/latest)**

| Platform | Package |
|---|---|
| Debian 12+, Ubuntu 22.04+ (x86_64, arm64) | `airllm_<ver>-<rev>_<arch>.deb` |
| Fedora, RHEL / Rocky / Alma 8+ (x86_64, aarch64) | `airllm-<ver>-<rev>.<arch>.rpm` |
| Windows 10/11 x64 | `AirLLM-<ver>-<rev>-setup-x64.exe` installer, `…-windows-x64.zip` portable |

## What you get

* **Desktop app**: chat with history, streaming answers with a live layer meter, a model library that downloads
  from Hugging Face and prepares AirLLM's layers with progress, and settings (models folder, HF token, GPU).
* **`airllm` command line**: `airllm app`, `pull`, `run`, `list`, `ps`, `rm`, `stop`, `status`, `serve`.
* **API server** on `127.0.0.1:11435`, compatible with the **Ollama** API (`/api/chat`, `/api/tags`, ...) and the
  **OpenAI** API (`/v1/chat/completions`), so tools like Open WebUI or any OpenAI SDK can use your models.
* **Self-contained**: every package bundles its own CPython
  ([python-build-standalone](https://github.com/astral-sh/python-build-standalone)), CPU PyTorch, transformers and
  AirLLM, so it never touches the system Python and works the same on every distro. NVIDIA GPUs: one command, below.

Packages are built by RudraLabs from AirLLM source (upstream, or our fork
[RudraLabs-dev/airllm](https://github.com/RudraLabs-dev/airllm) for fixes on their way upstream) by the
pipeline [described below](#how-the-pipeline-works). Studio's own docs: [studio/README.md](studio/README.md).

## Using the packages

```sh
sudo apt install ./airllm_4.0.0-4_amd64.deb        # Debian / Ubuntu
sudo dnf install ./airllm-4.0.0-4.x86_64.rpm       # Fedora / RHEL / Rocky / Alma

airllm app                                         # desktop app ("AirLLM" in the app menu too)
airllm pull Qwen/Qwen3-8B                          # download + prepare a model
airllm run Qwen/Qwen3-8B "Explain AirLLM"          # chat in the terminal
airllm-python my_script.py                         # the bundled interpreter, for your own code
cat /opt/airllm/share/airllm/BUILDINFO             # exact source commit, torch, python versions
```

**As a server.** `sudo systemctl enable --now airllm` runs the API and web UI as a hardened system service
(data in `/var/lib/airllm-server`). To reach it from other machines, keep the API key in a root-only file
(an `Environment=` line would show it to every local user through `systemctl show`):

```sh
sudo install -d -m 700 /etc/airllm
echo "AIRLLM_API_KEY=$(openssl rand -hex 32)" | sudo tee /etc/airllm/server.env >/dev/null
sudo chmod 600 /etc/airllm/server.env
sudo systemctl edit airllm      # add under [Service]:
                                #   Environment=AIRLLM_HOST=0.0.0.0:11435
                                #   EnvironmentFile=/etc/airllm/server.env
```

Clients send `Authorization: Bearer <key>`. Reached by a name (e.g. `gpu-box.lan`) rather than an IP address?
Add `Environment=AIRLLM_ALLOWED_HOSTS=gpu-box.lan`. Browser-based tools need their origin in `AIRLLM_ORIGINS`.
Behind a reverse proxy on the same machine every client looks local and the key is not enforced, so
authenticate in the proxy. Details: [studio/README.md](studio/README.md#security).

**NVIDIA GPU.** The packages ship CPU-only PyTorch so they stay well under GitHub's 2 GiB asset limit.
Switch to a CUDA build once after installing:

```sh
sudo airllm-enable-cuda            # default CUDA variant (see packaging/versions.env)
sudo airllm-enable-cuda cu126      # or any variant listed on https://pytorch.org/get-started/locally/
airllm-enable-cuda status
sudo airllm-enable-cuda disable    # back to CPU
```

The CUDA wheels go to `/var/lib/airllm/cuda-site` (Windows: `<install dir>\cuda-site`), which `airllm-python` puts first on the path.
Package upgrades never overwrite it; re-run the command after an upgrade that changes the torch version (the installer reminds you).
Older GPUs or drivers may need an older `cu12x` variant.

**Windows.** Run the installer (all users or just you) and open **AirLLM** from the Start menu; it runs in the
tray (right-click to open the models folder or quit). Optional installer tasks add a desktop shortcut and start
AirLLM at sign-in. `airllm`, `airllm-python` and `airllm-enable-cuda` work in a new terminal (the last one from an
Administrator prompt if installed under Program Files).
Silent install: `AirLLM-…-setup-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/DIR=D:\AirLLM] [/CURRENTUSER]`.

**Verify a download.** `sha256sum -c SHA256SUMS`, and `gh attestation verify <file> --owner RudraLabs-dev`
(each release carries a signed build-provenance attestation; `--owner` also covers releases up to v4.0.0-4,
which were signed while the repository was named `airllm-packaging`).

## How the pipeline works

```
watch-upstream.yml (daily 08:07 IST)          release.yml (manual / called / PR)
 ├─ sync-fork: fork main  ← upstream main      prepare ── resolve ref → checkout source → versions → wheel + sdist
 └─ new upstream tag? ──────────────────────▶   ├─ linux (x86_64, aarch64): payload in /opt/airllm → nfpm → .deb + .rpm
                                                 │    └─ test-linux: install / smoke + Studio E2E / uninstall on
                                                 │       Debian 12, 13 · Ubuntu 22.04, 24.04 · Fedora · Rocky 9 · Alma 8
                                                 ├─ windows: payload → Inno Setup .exe + .zip → silent install + Studio E2E
                                                 └─ release: SHA256SUMS + provenance → GitHub Release (draft → public)
```

* **Automatic:** when upstream tags a release (`vX.Y.Z`), the next daily run packages it as release `vX.Y.Z-1`.
* **Manual:** *Actions → Build & release packages → Run workflow*, with
  * `airllm_ref` — tag, branch or commit (empty = latest tag),
  * `source_repo` — `lyogavin/airllm` or our fork (e.g. to ship a fix before upstream merges it),
  * `pkg_release` — bump to re-release the same AirLLM version with packaging changes (`v4.0.0-2`),
  * `publish` — untick to build and test without releasing.
* Branch / commit builds are versioned `X.Y.Z+gitYYYYMMDD.<sha>` and published as pre-releases.
* Pull requests that touch `packaging/` run the full build and install tests but never publish.

### Repository layout

```
packaging/versions.env           every pin: Python, PyTorch index, nfpm, CUDA default, repo names
packaging/linux/                 build-payload.sh, build-packages.sh, nfpm.yaml, launchers, maintainer scripts
packaging/windows/               build-payload.ps1, airllm.iss (Inno Setup), .cmd/.ps1 launchers
packaging/ci/                    ref/version resolution, container install test
packaging/tests/                 smoke_test.py + studio_e2e.py, run on every payload and every installed package
studio/                          AirLLM Studio: desktop app, CLI, Ollama/OpenAI-compatible server (Python + web UI)
.github/workflows/               release.yml, watch-upstream.yml, lint.yml
scripts/dev-setup.sh             contributor clone of the fork with upstream wired up
```

### Building locally (Linux)

```sh
pipx run build --wheel --outdir dist /path/to/airllm/air_llm
pipx run build --wheel --outdir dist studio
sudo packaging/linux/build-payload.sh --wheel dist/airllm-*.whl --studio-wheel dist/airllm_studio-*.whl   # → /opt/airllm
packaging/linux/build-packages.sh --version 4.0.0 --release 1 --out out   # → out/*.deb, out/*.rpm
```

## One-time setup (org admins)

| What | Why |
|---|---|
| Secret `FORK_SYNC_TOKEN` (fine-grained PAT, repo `RudraLabs-dev/airllm`, *Contents: read & write*) | Lets the daily job fast-forward the fork. Optional — without it, use *Sync fork* on GitHub. |
| *Settings → Actions → General*: allow GitHub Actions | Workflows request `contents: write` only in the release job. |
| Branch protection on `main` requiring the **Lint** check | Pipeline changes go through PRs, which run the full build and tests. |

Bumping a pin (Python, nfpm, CUDA default) is a one-line PR to `packaging/versions.env`; Dependabot keeps the SHA-pinned actions current.

## Contributing to AirLLM

See [CONTRIBUTING.md](CONTRIBUTING.md) for how we send changes upstream through the org fork.

Licensed under Apache-2.0, like AirLLM. Bundled components keep their own licences.
