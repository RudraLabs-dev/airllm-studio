# Using the App

AirLLM Studio's window has three places: the **chat**, the **Models** page and **Settings**. The sidebar on the left holds your chat history, **New chat**, your [Projects](Projects) and the **Models** and **Settings** buttons. A small status line at its bottom shows the compute device (for example a GPU name or CPU).

## Chatting

* Pick a model from the drop-down at the top. Only models you have pulled appear. A project's default model is chosen for you.
* Type in the message box. **Enter** sends; **Shift+Enter** starts a new line.
* Answers stream in as they are produced. While AirLLM works, a **layer meter** shows how far through the model's layers the current token is. This is normal: AirLLM reads every layer from disk for every token, which is why big models are slow but fit on small machines ([Models and Performance](Models-and-Performance)).
* The first answer after loading a model is the slowest, because the model must be loaded. Studio unloads an idle model after the time set under **Unload when idle** (30 minutes by default).
* One model runs at a time and requests are served in order. If you send a message while another is running (in another chat, or from another app through the API), it waits and shows a *queued* status.
* Chats are saved automatically, in a database on your computer, and listed in the sidebar. Open the **⋯** menu of a chat to rename it, move it into a project or delete it.
* A chat remembers which model you used. You can switch models in the middle of a chat: the new model sees the earlier messages (older images are replaced with a placeholder if it cannot read images).

If a model cannot take images, the attach button is hidden; the microphone button appears only for models that understand audio. See [Images and Voice](Images-and-Voice).

## Models page

* **Installed** lists your models with their size on disk and context length, and a **Chat** button, plus **Load** (load into memory now, so the first answer is faster) and a trash button to delete one and free its disk space. A model that is downloading shows a progress bar and **Cancel**.
* **Add a model** takes a Hugging Face id (`org/name`) or a folder on your computer that holds a Hugging Face model (`config.json` and `.safetensors` or `.bin` weights). Type to search Hugging Face, or choose from **Suggested**. Press **Pull**.
* A pull has stages: *Looking up the model*, *Downloading* (with bytes and percentage), then **Preparing layers (one time)**, where AirLLM splits the model into per-layer files. After that, loading is quick.
* Tags such as **Images** and **Voice** show what a model can take ([Images and Voice](Images-and-Voice)).
* Models that ship their own Python code are refused until you explicitly allow it: the row offers **Allow custom code**. Only do that for publishers you trust ([Security](Security)).
* Gated models (for example Llama) need a Hugging Face access token under **Settings**.

## Settings

| Section | Setting | What it does |
|---|---|---|
| **Answers** | System prompt | Text every chat starts with (a project's instructions follow it) |
| | Max answer length (tokens) | Upper limit for one answer; default 512 |
| | Temperature, Top-p | Randomness of the wording; defaults 0.7 and 0.9 |
| | Context length (tokens) | How much of the conversation the model sees; default 4096. Longer is slower and uses more memory |
| **Hardware** | Run models on | `auto`, `cpu`, or a specific GPU (`cuda:0`, ...) |
| | Layer compression | None (full precision), 8-bit, or 4-bit (fastest). Applies when a model is prepared. Needs the `bitsandbytes` package, which is not bundled ([Models and Performance](Models-and-Performance)) |
| | Unload when idle (minutes) | 0 keeps the model loaded until you unload it |
| **Storage and Hugging Face** | Models folder | Where models are stored; empty means the default under `~/.airllm`. Choose it before downloading: existing models are not moved ([Configuration](Configuration)) |
| | Delete the original download after a large model is prepared | Halves the disk use of big models; pulling again re-downloads |
| | Hugging Face access token | For gated models; stored on your computer, never shown again |
| **Connect other apps** | Copy-and-paste addresses | The server addresses for Ollama- and OpenAI-style clients ([API Reference](API-Reference)) |
| **About** | Versions, folders | Buttons to open the models folder and the logs |

Press **Save changes**. Most settings apply to the next model you load.

## The window, the tray and quitting

The app window is your Chromium-based browser (Microsoft Edge or Google Chrome on Windows; Chrome, Chromium, Edge or similar on Linux) opened in a standalone app-style window with no tabs or address bar. If none is found, Studio opens the page in your default browser instead. The same page is available in any browser at `http://127.0.0.1:11435`.

On **Windows** the server runs inside a tray process. The tray icon's menu has **Open AirLLM**, **Open models folder** and **Quit AirLLM**. Closing the window does not stop the server, so other apps can keep using the API; use **Quit AirLLM** (tray menu, or **Settings, About, Quit AirLLM**) to stop it. Quitting also frees the memory a loaded model uses, and is needed after [switching to CUDA](GPU-and-CUDA).

On **Linux**, `airllm app --background` starts the server without a window and `airllm stop` stops it ([Command Line](Command-Line)). **Settings, About, Quit AirLLM** stops it from the app.

Keyboard: **Enter** sends, **Shift+Enter** adds a line, **Ctrl+Shift+O** (Cmd+Shift+O on a Mac browser) starts a new chat.

## Where things are stored

See [Configuration](Configuration): chats and projects in `chats.db`, settings in `settings.json`, logs in `logs/`, models in `models/`, all under `~/.airllm` unless you change it.
