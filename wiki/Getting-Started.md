# Getting Started

This page takes you from nothing to a first answer. Details for every step are on the linked pages.

## 1. Install

Download the package for your system from the [latest release](https://github.com/RudraLabs-dev/airllm-studio/releases/latest):

| System | File | Install |
|---|---|---|
| Debian 12+, Ubuntu 22.04+ | `airllm_<version>_amd64.deb` or `_arm64.deb` | `sudo apt install ./airllm_<version>_amd64.deb` |
| Fedora, RHEL, Rocky, Alma 8+ | `airllm-<version>.x86_64.rpm` or `.aarch64.rpm` | `sudo dnf install ./airllm-<version>.x86_64.rpm` |
| Windows 10/11 (x64) | `AirLLM-<version>-setup-x64.exe` | Run it (for everyone, or just you) |

More options (portable zip, silent install, verifying downloads): [Installation](Installation).

## 2. Open the app

* **Linux:** open **AirLLM** from the application menu, or run `airllm app`.
* **Windows:** open **AirLLM** from the Start menu. It lives in the system tray.

The app starts a private server on your computer (`127.0.0.1:11435`) and opens its window. Nothing is exposed to the network.

## 3. Get a model

Open **Models** in the sidebar. Under **Add a model**, pick one from **Suggested** or paste a Hugging Face name such as `Qwen/Qwen3-8B`, then press **Pull**.
Studio downloads the weights and runs AirLLM's one-time layer split ("Preparing layers"). This takes a while and uses
disk space: a model needs roughly its full size on disk, and more while it is being prepared.

> **Your first model should be small.** The catalog's tiny test model (`HuggingFaceTB/SmolLM2-135M-Instruct`, about 270 MB) checks your
> whole setup in a minute. Then move to a 7B-8B model. Big models work, but each answer takes much longer.
> See [Models and Performance](Models-and-Performance).

## 4. Chat

When the model appears under **Installed**, press **Chat**. The first answer is slowest because the model has to load. A **layer meter**
under the message shows AirLLM streaming through the model's layers for each token.

Or from a terminal:

```sh
airllm pull Qwen/Qwen3-8B
airllm run Qwen/Qwen3-8B "Explain AirLLM in two sentences"
```

## 5. Next steps

* Have an NVIDIA GPU? [GPU and CUDA](GPU-and-CUDA) is the biggest speed-up available.
* Working on something over many chats? Use [Projects](Projects).
* Want other tools (Open WebUI, scripts) to use your models? [API Reference](API-Reference).
* Something went wrong? [Troubleshooting](Troubleshooting).
