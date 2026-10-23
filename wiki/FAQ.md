# FAQ

## About the project

**What is AirLLM Studio?**
A desktop app, command line and local API server built around [AirLLM](https://github.com/lyogavin/airllm), packaged as one installer for Linux and Windows. It is made by RudraLabs and is **not affiliated with the AirLLM authors** ([Legal and Licensing](Legal-and-Licensing)).

**What is AirLLM?**
An open-source library that runs very large language models on small hardware by loading the model **one layer at a time** from disk instead of keeping it all in memory.

**Is it free? Can I use it at work?**
Yes. It is Apache-2.0 licensed. The models you download have their own licences, which decide what you may do with them.

**Does it send my chats or files anywhere?**
No. Chats, projects and settings stay on your computer. The only connections are to Hugging Face (model downloads, search) and, if you run `airllm-enable-cuda`, to PyTorch's download server ([Security](Security)).

**Is it a replacement for Ollama?**
No, a different trade-off. Ollama keeps a model in memory and is fast, for models that fit. AirLLM Studio is for models that **do not** fit, and pays for it in speed. Any client that speaks the Ollama or OpenAI API works with both ([API Reference](API-Reference)), and Studio uses port 11435 so both can run side by side.

## Speed and hardware

**Why is it so slow?**
Every token requires reading the whole model from disk, layer by layer. The time per token is roughly *model size / disk read speed*. That is the price of running models larger than your memory ([Models and Performance](Models-and-Performance)).

**How do I make it faster?**
Smaller model, NVIDIA GPU ([GPU and CUDA](GPU-and-CUDA)), models on an NVMe SSD, shorter context, and optionally 4-bit layer compression (needs the extra `bitsandbytes` package, which is not bundled).

**Do I need a GPU?**
No. Without one the model runs on the CPU. A GPU speeds up the computation, not the disk reading.

**How much memory do I need?**
Little: AirLLM holds about one layer at a time, plus a vision tower for image models. What you need is **disk space**: roughly the model's size, and about the same again while it is being prepared.

**Can I run a 70B model on an 8 GB GPU?**
It can run, if you have the disk space (a 70B model in 16-bit is about 140 GB, and about the same again while it is prepared) and patience: expect tens of seconds per token or more.

**Which GPUs work?**
NVIDIA GPUs through the CUDA build of PyTorch are the supported path, and the CPU build works everywhere. Other accelerators (AMD, Apple) are not tested. macOS and Windows on ARM are not provided.

**Can I use several GPUs?**
You can choose which single GPU to use (`cuda:0`, `cuda:1`). A model is not split across GPUs.

## Models

**Which models work?**
Text-generation models on Hugging Face in **safetensors** (or PyTorch `.bin`) format, for architectures AirLLM supports. New families arrive with new AirLLM releases, which we package automatically. Pick from the **Suggested** list or search Hugging Face in the app.

**Why does it reject my GGUF file?**
AirLLM streams the original checkpoint. A repository that only has GGUF files (the llama.cpp format) cannot be used; look for the non-GGUF repository of the same model.

**Can I use a model I downloaded myself?**
Yes, if it is a Hugging Face folder (with `config.json` and weights): pull it by its folder path, or paste the path in **Add a model**. Folder import only works from the computer itself.

**Why does a model ask to "Allow custom code"?**
It ships its own Python code, which would run on your computer. It is off by default; allow it only for publishers you trust ([Security](Security)).

**Can it read images?**
Yes, for vision-language models that AirLLM supports (for example the `Qwen3.8` family in the Suggested list). **Voice input** is not available yet: no model that AirLLM can run takes audio ([Images and Voice](Images-and-Voice)).

**Can it read PDFs and Word files?**
Not directly. Projects accept **text** files (code, Markdown, CSV...). Studio does not convert documents; copy the text, or convert it first.

**Does it have web search, tools or an agent mode?**
No. It is a chat, projects, images, and an API.

## Using it

**Where are my chats and models?**
In `~/.airllm` (Windows: `%USERPROFILE%\.airllm`) ([Configuration](Configuration)).

**How do I back up or move my chats?**
Copy `chats.db` and `settings.json` from the data folder with AirLLM closed.

**Can I use it from my phone or another computer?**
Run the server on a machine and let clients connect with an API key ([Server Mode](Server-Mode)). The built-in web UI is meant for the machine it runs on.

**Can several people share one server?**
Technically yes, with one shared key and no separate accounts; the server answers one request at a time. It suits a few people on a trusted network, not a team ([Server Mode](Server-Mode)).

**How do I use it with Open WebUI, Continue, Chatbox, LangChain...?**
Add an Ollama connection to `http://127.0.0.1:11435`, or an OpenAI-compatible one with base URL `http://127.0.0.1:11435/v1` ([API Reference](API-Reference)).

**Does it update itself?**
No. Install the newer package over the old one; your data is kept ([Installation](Installation)). New AirLLM releases are packaged automatically, usually within a day, and appear on the [Releases page](https://github.com/RudraLabs-dev/airllm-studio/releases).

**How do I uninstall it completely?**
Remove the package (`sudo apt remove airllm`, `sudo dnf remove airllm`, or Windows *Settings, Apps*), then delete the data folder if you also want to remove chats and models.

## Security and trust

**The Windows installer says "Unknown publisher".**
It is not code-signed yet. Verify the SHA-256 from `SHA256SUMS` and, if you like, the build attestation ([Installation](Installation#verify-a-download)).

**Is my server open to the internet?**
Not by default: it listens on `127.0.0.1` only. If you change that, set an API key and read [Security](Security).

**How do I report a security problem?**
See [Security](Security#reporting-a-vulnerability).

## Contributing

**How can I help?**
Try it and report what breaks; improve these pages; send pull requests ([Development](Development)). Improvements to AirLLM itself are best sent to the [AirLLM project](https://github.com/lyogavin/airllm); the [contributing guide](https://github.com/RudraLabs-dev/airllm-studio/blob/main/CONTRIBUTING.md) lists good first ones.
