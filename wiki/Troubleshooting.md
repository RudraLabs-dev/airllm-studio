# Troubleshooting

Start with two things that answer most questions:

```sh
airllm status                      # is the server up, which PyTorch, CUDA, GPU, device, loaded model, free disk
```

and the logs: **Settings, About, Open logs** in the app, or the `logs` folder of the data directory ([Configuration](Configuration)); `server.log` is the one to read. On a systemd server use `journalctl -u airllm`.

Jump to: [Starting](#starting-the-app) · [Downloading models](#downloading-and-preparing-models) · [Answers and speed](#answers-and-speed) · [Images and voice](#images-and-voice) · [API and network](#api-and-network) · [CUDA](#cuda) · [Windows](#windows) · [Reporting a bug](#reporting-a-bug)

## Starting the app

| Symptom | Likely cause and fix |
|---|---|
| Nothing happens when I click AirLLM | The first start takes several seconds while PyTorch loads. Run `airllm app` in a terminal to see messages; read `server.log` |
| The window opens but shows an error page | The server is not running or still starting. `airllm status`; if it says *not running*, run `airllm serve` in a terminal and read what it prints |
| `Address already in use` in the log | Another program (or a second AirLLM) holds port 11435. Quit it, or set `AIRLLM_HOST=127.0.0.1:<other port>` for both server and CLI |
| The app opens in my normal browser, not an app window | No Chromium-based browser (Edge, Chrome, Chromium) was found. That is fine; everything works in the tab ([Using the App](Using-the-App)) |
| After updating, the old version still runs | The old server is still running. **Quit AirLLM** (tray icon on Windows, `airllm stop` on Linux) and start again |
| I closed the window but memory is still used | The server keeps running by design so other apps can use the API. **Quit AirLLM** frees everything |

## Downloading and preparing models

| Message or symptom | Meaning and fix |
|---|---|
| *This repo only has GGUF files* | AirLLM needs the original Hugging Face checkpoint (safetensors). Use the non-GGUF repository of the same model |
| *No .safetensors or .bin weights found in this repo* | Not a standard transformers checkpoint; pick another repository |
| *This repo has no config.json, so it is not a transformers model* | Same: AirLLM cannot run it |
| *Use a Hugging Face repo id like 'Qwen/Qwen3-8B', or a local model folder* | The name must be `organisation/name`, or the path of a folder on this computer |
| *This model ships its own Python code ...* | The model wants to run custom code. Only if you trust the publisher: **Allow custom code** in the app, or `airllm pull <model> --trust-remote-code` ([Security](Security)) |
| Download fails or says access denied for Llama, Gemma, ... | The model is **gated**: accept its licence on its Hugging Face page, create a token, and paste it in **Settings, Hugging Face access token** |
| The progress bar pauses during a big download | Short pauses between files or chunks are normal. If the byte counter has not moved for several minutes, check the network and the free disk space, cancel, and pull again (Hugging Face's cache normally resumes partial downloads) |
| *Model ... is not ready yet (...)* | The pull is still running or failed; look at the model's row for the error. Pull again to retry |
| Preparing fails midway or the disk fills up | Preparing needs roughly the model's size *again* on top of the download. Free space, or enable *Delete the original download after a large model is prepared*, then pull again |
| Architecture or class error while preparing | This AirLLM version does not know the model family. New releases are packaged automatically when AirLLM adds support ([Build and Release Pipeline](Build-and-Release-Pipeline)) |
| *Importing a model folder is only allowed from this computer* | Folder paths can only be imported by a caller on the same machine |

## Answers and speed

| Symptom | Cause and fix |
|---|---|
| Every answer takes minutes | That is how AirLLM works: each token reads the whole model from disk. See [Models and Performance](Models-and-Performance): smaller model, GPU, NVMe, shorter context, compression |
| The first answer after loading is much slower | The model is being loaded. It stays loaded for *Unload when idle* minutes (default 30) |
| Settings says compression needs `bitsandbytes` | It is not bundled. Install it into the bundled Python (see [Models and Performance](Models-and-Performance)), then pull the model again so it is prepared compressed |
| Out of memory (RAM) | AirLLM keeps only one layer in memory, so the usual causes are a large *Context length*, a very long chat or big project files. Lower *Context length* and *Max answer length*, start a new chat, close other programs |
| Out of GPU memory | Same remedies; or choose `cpu` in **Settings, Run models on** to confirm. GPUs with 8-12 GB are normally enough ([GPU and CUDA](GPU-and-CUDA)) |
| Answers cut off | Raise *Max answer length* |
| The model ignores my project files | Project text is cut to about half the context. Reduce the files, or raise *Context length* ([Projects](Projects)) |
| A second request waits | The server handles one generation at a time; other apps' API requests queue |
| "An answer is still being written in ..." when I send a message | Only one answer runs at a time. Wait for it, or open the chat marked with the pulsing dot and press **Stop** (or **Esc**). You can browse other chats and projects meanwhile |
| I want to stop an answer | The send button turns into **Stop** while an answer is being written (Ctrl+C in `airllm run`). The model stays loaded |

## Images and voice

| Symptom | Fix |
|---|---|
| No attach button | The selected model takes no images. Choose a vision-language model (tagged *Images* in the Models list) |
| *... does not take images* | The newest message has an image but the model cannot use it. Pick an image model, or send without the image |
| *This conversation with its images/audio is longer than the context length* | Start a new chat or raise *Context length* |
| No microphone button | Intentional: Voice appears only for models that take audio natively. No model that AirLLM can run does today ([Images and Voice](Images-and-Voice)) |
| *could not read the image* | Unsupported or damaged file. Try a PNG or JPEG |

## API and network

| Status / message | Meaning |
|---|---|
| `404 model '...' not found` | The name must match an installed model exactly as `airllm list` shows it |
| `401 missing or invalid API key` | The server has `AIRLLM_API_KEY` and the request comes from another computer: send `Authorization: Bearer <key>`. The built-in web UI cannot do this ([Server Mode](Server-Mode)) |
| `400 Host header not allowed` | You reached the server by a name it does not know. Add it to `AIRLLM_ALLOWED_HOSTS` ([Security](Security)) |
| `403 Origin ... is not allowed` / *Cross-site requests are not allowed* | A web page tried to call the API. Add its origin to `AIRLLM_ORIGINS` if you trust it |
| `403 only allowed from this computer` | Settings, shutdown and folder actions cannot be done remotely |
| Open WebUI cannot connect | Use the Ollama connection with `http://127.0.0.1:11435`. If Open WebUI runs in Docker, `127.0.0.1` is the container: use the host's address, set `AIRLLM_HOST=0.0.0.0:11435` with `AIRLLM_ALLOWED_HOSTS` and an API key |
| `airllm` cannot reach a remote server | Check `AIRLLM_HOST` and `AIRLLM_API_KEY` in *your* shell. If nothing answers, the CLI starts a local server instead, which is a hint that the address is wrong |
| Streaming stops early behind a proxy | Disable response buffering in the proxy ([Server Mode](Server-Mode)) |

## CUDA

First see what is going on:

```sh
airllm-enable-cuda status          # overlay installed? "torch ... | CUDA available: True/False"
nvidia-smi                         # does the driver see the GPU, and which CUDA version does it support?
airllm status                      # what the running server uses: torch, CUDA, GPUs, device
```

| Symptom | Cause and fix |
|---|---|
| *Access is denied* after the 2 GB download (Windows, versions before 4.0.0-5) | AirLLM lives under `Program Files` and the terminal was not elevated. Update to the current release: the command now asks for Administrator rights up front. Workaround on old versions: start the terminal as Administrator |
| *Administrator permission was not given* | You declined the UAC prompt. Run `airllm-enable-cuda` again and accept, or reinstall AirLLM for the current user only |
| `CUDA available: False` right after enabling | **Quit AirLLM and start it again.** A running app keeps the PyTorch it loaded at start. Then re-check with `airllm status` |
| `CUDA available: False`, overlay installed | The driver cannot run that CUDA build. Compare `nvidia-smi`'s CUDA version with the variant; install an older one, e.g. `airllm-enable-cuda cu126`. Also check that the NVIDIA driver is installed and loaded (Linux: reboot after installing it) |
| *pip failed ... offers torch ...* | The chosen variant does not publish the bundled torch version, or the network failed. Try another variant, or retry. See [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) |
| It worked before, not after an upgrade | The package now bundles a different torch version than the overlay. Run `airllm-enable-cuda` again |
| `device` shows `cpu` although CUDA is available | **Settings, Run models on** is set to `cpu`, or `AIRLLM_FORCE_CPU` is set |
| Wrong GPU is used | Set **Run models on** to `cuda:1` etc. |
| *could not remove ... (is AirLLM running?)* | On Windows the files are in use. Quit AirLLM (tray icon) and run the command again |
| I want to go back to CPU | `airllm-enable-cuda disable` (with `sudo` on Linux), then restart AirLLM |

More: [GPU and CUDA](GPU-and-CUDA).

## Windows

| Symptom | Fix |
|---|---|
| SmartScreen says *Unknown publisher* | The installer is not code-signed yet. Verify the SHA-256 ([Installation](Installation#verify-a-download)) and choose *More info, Run anyway* |
| `airllm` is not recognized | Open a **new** terminal window after installing, or use *AirLLM Command Prompt* from the Start menu |
| Installer reports files in use | **Quit AirLLM** from the tray icon before installing an update, then run the installer again |
| No window appears on start | Look for the tray icon; use its **Open AirLLM**. Logs: `%USERPROFILE%\.airllm\logs` |

## Linux

| Symptom | Fix |
|---|---|
| `airllm: command not found` after install | Open a new shell; the package installs `/usr/bin/airllm` |
| No AirLLM in the app menu | Log out and in once, or run `airllm app` |
| No dock icon / generic icon on Wayland | Cosmetic; the app works. The window is a Chromium app window ([Using the App](Using-the-App)) |
| Service does not start | `systemctl status airllm` and `journalctl -u airllm`. The service has its own data folder `/var/lib/airllm-server` ([Server Mode](Server-Mode)) |

## Resetting

* **Settings only:** quit AirLLM, delete `settings.json` in the data folder.
* **Everything** (chats, projects, models): quit AirLLM, delete the data folder (`~/.airllm`). The program is not affected.
* **Remove the CUDA overlay:** `airllm-enable-cuda disable`.

## Reporting a bug

Open an [issue](https://github.com/RudraLabs-dev/airllm-studio/issues) and include: your OS and version; the output of `airllm status`; the package file name you installed (and on Linux `cat /opt/airllm/share/airllm/BUILDINFO`); what you did and what you expected; the last lines of `server.log`. Remove tokens and private text first. Problems in AirLLM's model support itself belong to the [AirLLM project](https://github.com/lyogavin/airllm/issues).
