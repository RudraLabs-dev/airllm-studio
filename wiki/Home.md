# AirLLM Studio

**Run large language models on everyday hardware.** AirLLM Studio is a desktop app, command line and local API
server built on [AirLLM](https://github.com/lyogavin/airllm), which streams a model through memory one layer at a
time. A model far bigger than your GPU memory (even bigger than your RAM) can run on one consumer machine: you trade
speed for the ability to run it at all.

It ships as one self-contained installer for Linux (`.deb`, `.rpm`) and Windows. No Python, pip or CUDA toolkit to set up.

> **Independent project.** AirLLM Studio is made by [RudraLabs](https://github.com/RudraLabs-dev) and is not affiliated with,
> sponsored or endorsed by the authors of AirLLM. See [Legal and Licensing](Legal-and-Licensing).

## Start here

| I want to... | Go to |
|---|---|
| Install it and chat in five minutes | [Getting Started](Getting-Started) |
| Install on Debian, Ubuntu, Fedora, RHEL or Windows, upgrade or uninstall | [Installation](Installation) |
| Learn the app: chats, model library, settings | [Using the App](Using-the-App) |
| Group chats with shared instructions and files | [Projects](Projects) |
| Chat about images; understand voice input | [Images and Voice](Images-and-Voice) |
| Pick a model that fits my machine and make it faster | [Models and Performance](Models-and-Performance) |
| Use my NVIDIA GPU | [GPU and CUDA](GPU-and-CUDA) |
| Script it from a terminal | [Command Line](Command-Line) |
| Connect Open WebUI, the OpenAI SDK, curl... | [API Reference](API-Reference) |
| Run it as a server for other machines | [Server Mode](Server-Mode) and [Security](Security) |
| Look up a setting or environment variable | [Configuration](Configuration) |
| Fix a problem | [Troubleshooting](Troubleshooting) |

## For contributors and maintainers

* [Architecture](Architecture): how the pieces fit and how a model runs.
* [Build and Release Pipeline](Build-and-Release-Pipeline): how packages are built, tested and published.
* [Development](Development): run it locally, tests, contributing.
* [FAQ](FAQ).

## What you get

* **Desktop app**: chat with history, streaming answers, a live layer meter, a model library that downloads from
  Hugging Face and prepares AirLLM's layers with progress, and settings.
* **Projects**: chats grouped under shared instructions and text files.
* **Images** for vision-language models that AirLLM can run. Voice input appears only for models that take audio natively.
* **`airllm` command line**: `app`, `pull`, `run`, `list`, `ps`, `rm`, `stop`, `status`, `serve`.
* **API server** on `127.0.0.1:11435`, compatible with the **Ollama** API and the **OpenAI** API.
* **Self-contained packages** with their own Python, PyTorch (CPU) and AirLLM; a one-command switch to CUDA.
* **Signed build provenance** on every release and a daily watch that packages new AirLLM versions automatically.

Latest packages: [Releases](https://github.com/RudraLabs-dev/airllm-studio/releases/latest).
