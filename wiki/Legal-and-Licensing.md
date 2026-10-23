# Legal and Licensing

> This page explains how the project is licensed and how it relates to other projects. It is information, not legal advice.

## Independent project

**AirLLM Studio is made by [RudraLabs](https://github.com/RudraLabs-dev) and is not affiliated with, sponsored or endorsed by the authors of [AirLLM](https://github.com/lyogavin/airllm).** AirLLM is an open-source project by its own authors; AirLLM Studio is an app, command line and API server built **around** it, and the installers bundle AirLLM so that nothing else has to be set up.

"AirLLM" is the name of that project and belongs to its owners. It is used here only to say what this software is built on. Rights holders with questions about naming or branding can contact RudraLabs through the [issue tracker](https://github.com/RudraLabs-dev/airllm-studio/issues).

The same notice appears in the app (**Settings, About**), in the package descriptions and in the installer.

## Licence

AirLLM Studio and the packaging in this repository are licensed under the **[Apache License 2.0](https://github.com/RudraLabs-dev/airllm-studio/blob/main/LICENSE)**, the same licence as AirLLM. In short, you may use, modify and redistribute the software, including commercially, as long as you keep the licence and copyright notices and state significant changes. The licence includes a patent grant and a disclaimer of warranty, and it **does not grant any right to use the names, logos or trademarks** of the licensors.

## Is the bundled AirLLM modified?

No. The packages are built from the **source of a published AirLLM release** (by default the tag of the latest release of `lyogavin/airllm`), exactly as released. A build from a branch or commit, for example a branch of RudraLabs' fork with a patch that is not merged upstream yet, is published as a **pre-release**, and every release states in its notes which repository, ref and commit it was built from. The same information is in `share/airllm/BUILDINFO` inside the install folder.

Fixes we make to AirLLM are offered back to the upstream project as pull requests ([CONTRIBUTING](https://github.com/RudraLabs-dev/airllm-studio/blob/main/CONTRIBUTING.md)).

## What is inside the packages

The installers bundle open-source components, each under its own licence. The main ones (see each project for the authoritative text):

| Component | Licence |
|---|---|
| AirLLM | Apache-2.0 |
| AirLLM Studio (this repository) | Apache-2.0 |
| CPython (python-build-standalone) | Python Software Foundation licence |
| PyTorch, torchvision | BSD-style |
| Hugging Face `transformers`, `huggingface_hub`, `tokenizers`, `safetensors`, `accelerate`, `sentencepiece` | Apache-2.0 |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| NumPy, SciPy | BSD-3-Clause |
| Pillow | HPND |
| `pystray` (Windows tray icon only) | LGPL-3.0 |

The **exact list of Python packages and versions** in your installation is in `share/airllm/requirements.lock` inside the install folder (`/opt/airllm/share/airllm/` on Linux, `<install folder>\share\airllm\` on Windows), and the Windows installer shows the AirLLM licence during setup. Each Python package keeps its own licence files in its `*.dist-info` folder under `python/Lib/site-packages` (Linux: `python/lib/python3.12/site-packages`). Build tools (nfpm, Inno Setup) are used to create the packages and are not part of what you install.

**NVIDIA CUDA.** The packages contain no CUDA libraries. When you run `airllm-enable-cuda`, the PyTorch CUDA build and NVIDIA's CUDA libraries are downloaded from PyTorch's servers and are governed by their own licences, including NVIDIA's terms.

## Models

AirLLM Studio **does not include or distribute any model**. You download models from Hugging Face; each model has its own licence and terms (for example the Llama community licence, Qwen and Mistral licences), and some require you to accept them on the model page first ("gated" models). Make sure your use of a model, including commercial use and redistribution of its outputs, is permitted by its licence.

## No warranty, and AI output

The software is provided **"as is"**, without warranty of any kind (Apache-2.0, sections 7 and 8). Language models can produce wrong, biased or inappropriate output. Check anything important before relying on it, and do not use the software as the sole basis for medical, legal, financial or safety decisions.

## Privacy

RudraLabs does not collect any data through the software: it has no analytics, accounts or update check. The only connections it makes are to **Hugging Face** (downloading models, searching, and using your access token if you set one) and, if you run `airllm-enable-cuda`, to PyTorch's download server. Hugging Face's and PyTorch's own terms and privacy policies apply to those connections. Your chats, projects and settings stay on your computer ([Security](Security)).

## Other names

Ollama, OpenAI, Hugging Face, NVIDIA, Windows, Linux, Debian, Ubuntu, Fedora, Red Hat, Rocky Linux, AlmaLinux and the names of models are trademarks or names of their respective owners. They are used here only to describe compatibility ("works with clients written for the Ollama or OpenAI API") and do not imply any affiliation or endorsement.

## Windows publisher

The Windows installer names **RudraLabs** as publisher in its file details. It is not yet signed with a code-signing certificate, so Windows may show *Unknown publisher* in the SmartScreen and security prompts. Until it is signed, verify downloads with the published checksum and build attestation ([Installation](Installation#verify-a-download)).

## Contact and reporting

* Bugs and questions: [issues](https://github.com/RudraLabs-dev/airllm-studio/issues)
* Security reports: see [Security](Security#reporting-a-vulnerability)
* Problems in AirLLM itself: the [AirLLM project](https://github.com/lyogavin/airllm/issues)
