# Command Line

The `airllm` command (installed by every package; on Windows use a **new** terminal after installing) controls Studio from a terminal. Commands that need the server start it in the background automatically and leave it running, so repeated calls are fast.

```sh
airllm --version
airllm app                          # open the desktop app (starts the server if needed)
airllm app --background             # start the server (and tray icon on Windows) without a window
airllm serve                        # run the server in the foreground
airllm pull Qwen/Qwen3-8B           # download a model and prepare its layers
airllm run Qwen/Qwen3-8B            # chat in the terminal
airllm run Qwen/Qwen3-8B "Explain AirLLM in two sentences"
airllm list                         # installed models (also: airllm ls)
airllm ps                           # which model is loaded
airllm rm Qwen/Qwen3-8B             # delete models, free their disk space
airllm status                       # server, torch, device, model and storage info
airllm stop                         # stop the background server
```

## Commands in detail

### `airllm pull <model>`

Downloads a Hugging Face model (`org/name`) **or** prepares a local folder that holds one, then runs AirLLM's one-time layer split, with progress on the terminal. Ctrl+C only stops *watching*: the pull keeps running in the server (cancel it from the app).

| Option | Meaning |
|---|---|
| `--trust-remote-code` | Allow a model that ships its own Python code to run it. Only for publishers you trust ([Security](Security)). Without it such models are refused before the weights download. |

### `airllm run <model> [prompt...]`

If the model is not installed yet it is pulled first. With a prompt, prints one answer and exits. Without, starts an interactive chat (`/help` lists the commands; Ctrl+C stops an answer that is being written):

```text
Chatting with Qwen/Qwen3-8B. /clear resets the conversation, /bye or Ctrl+D quits.
>>> 
```

| Option | Meaning |
|---|---|
| `--system TEXT` | System prompt for this run |
| `--temperature N` | Sampling temperature |
| `--max-tokens N` | Upper limit for the answer length |
| `--verbose` | Print token speed after each answer |

### `airllm serve [--host host[:port]] [--log-level debug|info|warning|error]`

Runs the server in the foreground, for services and debugging. The default address is `127.0.0.1:11435`; see [Server Mode](Server-Mode) before binding to other interfaces.

### `airllm app [--background]`

Opens the desktop window. `--background` only starts the server (on Windows with the tray icon).

### `airllm status`

Prints the Studio and AirLLM versions, the server address, PyTorch version and CUDA status, GPUs, the compute device, the loaded model and the models folder with free disk space. Exit code 1 when the server is not running. The first thing to run when something is off; include its output in bug reports.

### `airllm list`, `ps`, `rm`, `stop`

`list` shows name, parameter count, size, status (downloading, preparing, ready, loaded) and age; `ps` shows the loaded model, its device and state; `rm <model>...` deletes models and their files; `stop` shuts the background server down (`--quiet` hides messages).

## Where the CLI connects

`airllm` talks to the server at `AIRLLM_HOST` (default `127.0.0.1:11435`). If nothing answers there, it starts a local server in the background (its log is `server.log` in the `logs` folder of the data directory). To use a server on another machine set `AIRLLM_HOST=gpu-box.lan:11435` and, if it requires a key, `AIRLLM_API_KEY=<key>` in your environment ([Configuration](Configuration), [Server Mode](Server-Mode)).

## The bundled Python

`airllm-python` is the interpreter that comes with the package, with `airllm`, `torch` and `transformers` installed. Use it for your own scripts:

```sh
airllm-python my_script.py
airllm-python -c "import airllm; print(airllm.__file__)"
```

On Windows `airllm-shell.cmd` opens a prompt with these tools on the `PATH`. `airllm-enable-cuda` is covered in [GPU and CUDA](GPU-and-CUDA).
