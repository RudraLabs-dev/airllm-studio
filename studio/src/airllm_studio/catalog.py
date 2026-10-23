"""Curated starting points shown in the model library. Anything on Hugging Face can still be pulled.

VRAM figures are AirLLM's own (one layer on the GPU at a time); see the upstream README.
"""

CATALOG = [
    {
        "name": "HuggingFaceTB/SmolLM2-135M-Instruct",
        "title": "SmolLM2 135M Instruct",
        "summary": "Tiny model to check your setup end to end in a minute. Not for real work.",
        "download": "~270 MB", "vram": "", "tags": ["test", "tiny"],
    },
    {
        "name": "Qwen/Qwen3-8B",
        "title": "Qwen3 8B",
        "summary": "Strong general-purpose model; a good first real model.",
        "download": "~16 GB", "vram": "~1-2 GB", "tags": ["general", "multilingual"],
    },
    {
        "name": "mistralai/Mistral-7B-Instruct-v0.3",
        "title": "Mistral 7B Instruct v0.3",
        "summary": "Fast, well-rounded 7B chat model.",
        "download": "~15 GB", "vram": "~1-2 GB", "tags": ["general"],
    },
    {
        "name": "Qwen/Qwen3-32B",
        "title": "Qwen3 32B",
        "summary": "Large dense model with much stronger reasoning.",
        "download": "~65 GB", "vram": "~2 GB", "tags": ["reasoning"],
    },
    {
        "name": "Qwen/Qwen3.8-27B",
        "title": "Qwen3.8 27B (VL)",
        "summary": "Dense vision-language model: chat about images you attach, or plain text.",
        "download": "", "vram": "~3.3 GB", "tags": ["vision", "general"],
    },
    {
        "name": "meta-llama/Llama-3.3-70B-Instruct",
        "title": "Llama 3.3 70B Instruct",
        "summary": "Full-precision 70B on a ~4 GB GPU. Gated: accept the licence on Hugging Face first.",
        "download": "~141 GB", "vram": "~4 GB", "tags": ["general", "gated"], "gated": True,
    },
    {
        "name": "Qwen/Qwen3.8-Flash-Next",
        "title": "Qwen3.8 Flash-Next",
        "summary": "~180B MoE with per-layer embeddings.",
        "download": "", "vram": "~6 GB", "tags": ["moe", "large"],
    },
    {
        "name": "Qwen/Qwen3-235B-A22B",
        "title": "Qwen3 235B-A22B",
        "summary": "235B mixture-of-experts.",
        "download": "~470 GB", "vram": "~3 GB", "tags": ["moe", "large"],
    },
    {
        "name": "deepseek-ai/DeepSeek-V3",
        "title": "DeepSeek-V3",
        "summary": "671B MoE. Plan for a very large download and lots of disk.",
        "download": "~690 GB", "vram": "~12 GB", "tags": ["moe", "huge"],
    },
]
