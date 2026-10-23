# GPU and CUDA

The packages ship **CPU-only PyTorch**. That keeps each download well under GitHub's 2 GiB file limit and works everywhere. With an NVIDIA GPU, switch once to a CUDA build of PyTorch:

```sh
sudo airllm-enable-cuda            # Linux: default CUDA variant
airllm-enable-cuda                 # Windows: asks for Administrator rights itself
```

Windows: open a new terminal after installing. If AirLLM is installed under `Program Files`, the command shows a Windows permission (UAC) prompt, then continues in an elevated window that stays open until you press Enter. Before version 4.0.0-5 you had to start the terminal as Administrator yourself (the old version downloaded 2 GB first and then failed with *Access is denied*).

The command downloads the matching CUDA PyTorch (and torchvision) from `download.pytorch.org` (about 2.5 GB), installs it into an overlay folder, and keeps the bundled CPU build untouched:

| System | Overlay folder |
|---|---|
| Linux | `/var/lib/airllm/cuda-site` |
| Windows | `<install folder>\cuda-site` (normally `C:\Program Files\AirLLM\cuda-site`) |

After it finishes, **quit and reopen AirLLM** (on Windows: tray icon, **Quit AirLLM**; Linux: `airllm stop`). A running app keeps the PyTorch it started with.

## Commands

```sh
airllm-enable-cuda                 # default variant (cu130 in the current packages)
airllm-enable-cuda cu126           # another variant: anything served at download.pytorch.org/whl/<variant>
airllm-enable-cuda status          # which overlay is active, torch version, "CUDA available: True/False"
airllm-enable-cuda disable         # remove the overlay: back to the bundled CPU build
```

Use `sudo` on Linux for commands that change anything. `status` needs no special rights.

## Choosing a CUDA variant

The variant (`cu126`, `cu128`, `cu130`, ...) must be one your **NVIDIA driver** supports and one PyTorch publishes for the bundled torch version (see [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/)). A recent driver supports newer variants; an older GPU or driver may need an older one. If the command fails with *pip failed ... offers torch*, try another variant.

Check your driver with `nvidia-smi` (it shows the highest CUDA version the driver supports).

## Then in the app

* **Settings, Hardware, Run models on** should say `auto` or your GPU (`cuda:0`). The status line at the bottom of the sidebar shows the device in use.
* If you run **several GPUs**, choose which one with `cuda:N`.
* Set `AIRLLM_FORCE_CPU=1` in the environment to ignore the overlay and use the CPU build (for testing).

## After upgrading AirLLM

The overlay survives package upgrades. If the new package bundles a different PyTorch version, run `airllm-enable-cuda` again so the two match (the installer prints a reminder).

## What a GPU does and does not change

A GPU speeds up the computation of each layer. It does **not** remove the main cost of AirLLM, reading the layers from disk for every token ([Models and Performance](Models-and-Performance)). Expect a clear improvement, not the speed of a model that lives in GPU memory. Memory use of the GPU stays low: AirLLM holds only one layer (plus any vision tower) at a time, so GPUs with 8-12 GB can run very large models.

## Troubleshooting

See [Troubleshooting](Troubleshooting#cuda): *Access is denied*, `CUDA available: False`, driver and variant mismatches.
