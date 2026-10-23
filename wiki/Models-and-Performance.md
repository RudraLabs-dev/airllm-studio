# Models and Performance

## What AirLLM does, and what that means for speed

A normal runtime keeps the whole model in GPU or system memory. **AirLLM does not.** For each token it reads the model's layers from disk one at a time, runs the token through each, and discards them. Memory use stays small (a few GB, whatever the model size), so a 70B model can run on a laptop. The price is that **every generated token reads the whole model from disk**.

That gives one rule of thumb:

> **seconds per token ~ model size on disk / your disk's read speed**, plus compute time.

Rough, illustrative numbers for an NVMe SSD reading ~3 GB/s (your machine will differ; these are estimates, not measurements):

| Model on disk | ~ time per token | An answer of 300 tokens |
|---|---|---|
| ~16 GB (8B, 16-bit) | 5 s | ~25 min |
| ~4 GB (8B, 4-bit compressed *) | 1-2 s | ~5-10 min |
| ~54 GB (27B, 16-bit) | 15-20 s | over an hour |
| ~14 GB (27B, 4-bit compressed *) | 4-6 s | ~25 min |

\* needs `bitsandbytes`, see item 4 below.

A hard disk or USB drive is many times slower than NVMe. The GPU matters too: it makes the math fast, but not the reading.

**When AirLLM Studio is the right tool:** you want a model that is **bigger than your memory** (27B, 32B, 70B and up), where the alternatives are not an option, and you can wait for answers. **When it is not:** if the model fits in your GPU memory, a runtime that keeps it there (Ollama, llama.cpp) is far faster. Studio speaks the Ollama API, so you can use both.

## Making it faster, in order of effect

1. **Use a smaller model.** Time per token scales with model size. A 4B-8B model for everyday work; a big one for the occasional hard question.
2. **Turn on the GPU.** On NVIDIA hardware this is the biggest change in compute time ([GPU and CUDA](GPU-and-CUDA)). Without it, models run on the CPU.
3. **Put the models folder on an NVMe SSD** (**Settings, Storage and Hugging Face, Models folder**; set it before downloading, existing models are not moved). Disk read speed sets the pace.
4. **Layer compression: 4-bit** (**Settings, Hardware, Layer compression**). Layers are stored compressed, so far less data is read per token. Quality drops slightly. Two things to know:
   * It needs the **`bitsandbytes`** package, which is **not bundled** in the packages (Settings says "Compression needs the bitsandbytes package, which is not installed" until it is). Install it into the bundled Python: Linux `sudo airllm-python -m pip install bitsandbytes`; Windows, from an Administrator terminal, `airllm-python -m pip install bitsandbytes`. It is built for NVIDIA GPUs, so use it together with [CUDA](GPU-and-CUDA); we have not tested every platform.
   * It is applied when a model is **prepared**, so pull the model again (or delete it and pull) after changing the setting.

   Try it on a small model first.
5. **Shorter answers and context** (**Settings, Answers**): lower *Max answer length* and *Context length* if you do not need them. A long context also costs memory and time.
6. **Keep the model loaded** (**Unload when idle**, default 30 minutes): the first answer after loading is the slowest.
7. **Close other programs** that compete for the disk (downloads, backups, antivirus scans of the models folder).

## Choosing a model

The **Suggested** list on the Models page gives sizes. In general:

| Your goal | Start with |
|---|---|
| Check that everything works | `HuggingFaceTB/SmolLM2-135M-Instruct` (about 270 MB) |
| A good first real model | `Qwen/Qwen3-8B` (about 16 GB) |
| Stronger reasoning, patient | `Qwen/Qwen3-32B` (about 65 GB) |
| Chat about images | `Qwen/Qwen3.8-27B` (vision-language) |
| Very large models | catalog entries up to 235B, or any Hugging Face model AirLLM supports |

Any **text-generation** model on Hugging Face in safetensors format that AirLLM supports can be pulled. Disk space: roughly the model's size, plus about the same again while it is being prepared (enable **Delete the original download after a large model is prepared** to give the second half back). Gated models (Llama and others) need you to accept their licence on Hugging Face and add an access token in Settings.

AirLLM chooses a model class from the model's `config.json`; architectures it does not know fail with an error during preparation. Newer families need a newer AirLLM, which the packaging pipeline picks up automatically ([Build and Release Pipeline](Build-and-Release-Pipeline)).

## Model capabilities

Each model is tagged by what it takes as input: text always, **Images** and **Voice** when Studio can really feed them ([Images and Voice](Images-and-Voice)).
