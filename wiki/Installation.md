# Installation

Every package is **self-contained**: it brings its own Python (python-build-standalone), CPU PyTorch, `transformers`,
AirLLM and AirLLM Studio, so it never touches your system Python and behaves the same on every distribution. NVIDIA GPU
support is one extra command afterwards ([GPU and CUDA](GPU-and-CUDA)).

Packages are about 200-350 MB. Downloads are on the [Releases page](https://github.com/RudraLabs-dev/airllm-studio/releases);
the file name contains the AirLLM version and a package revision (`4.0.0-5` is AirLLM 4.0.0, revision 5 of our packaging).

## Requirements

| | |
|---|---|
| Linux | Debian 12 and 13, Ubuntu 22.04 and 24.04, current Fedora, Rocky 9, AlmaLinux 8 (and so RHEL 8/9 family); x86_64 or aarch64 |
| Windows | Windows 10 or 11, 64-bit (x64) |
| Disk | About 1.5 GB for the program, plus the models you download |
| GPU | Optional. Without one, models run on the CPU (slower) |

These are the systems the release pipeline installs and tests on every build. Other distributions with a recent glibc usually work but are not tested.
Not provided: macOS, 32-bit systems, Windows on ARM.

## Linux

```sh
sudo apt install ./airllm_<version>_amd64.deb        # Debian / Ubuntu (use _arm64.deb on ARM)
sudo dnf install ./airllm-<version>.x86_64.rpm       # Fedora / RHEL / Rocky / Alma (.aarch64.rpm on ARM)
```

What is installed:

| Path | Content |
|---|---|
| `/opt/airllm/` | the bundled Python, libraries and launchers |
| `/usr/bin/airllm` | the Studio command line ([Command Line](Command-Line)) |
| `/usr/bin/airllm-python` | the bundled interpreter, for your own scripts that `import airllm` |
| `/usr/bin/airllm-enable-cuda` | switches PyTorch to a CUDA build ([GPU and CUDA](GPU-and-CUDA)) |
| `/opt/airllm/share/airllm/BUILDINFO` | exact source commit, torch and Python versions of this build |
| application menu entry **AirLLM** | starts `airllm app` |
| `airllm.service` (systemd) | optional server mode ([Server Mode](Server-Mode)) |

Your chats, projects, settings and models are in your home folder (`~/.airllm`), not in the package.

## Windows

Run `AirLLM-<version>-setup-x64.exe`. It can install for all users (administrator rights) or just for you, then adds an **AirLLM** Start-menu entry; optional tasks add a desktop shortcut and start AirLLM at sign-in.
`airllm`, `airllm-python` and `airllm-enable-cuda` work in a **new** terminal window.

> **SmartScreen / "Unknown publisher".** The installer is not yet signed with a code-signing certificate, so Windows may warn
> that it is from an unknown publisher. Verify the download first (below).

**Silent install** (for IT deployments):

```bat
AirLLM-<version>-setup-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/DIR=D:\AirLLM] [/CURRENTUSER]
```

Silent uninstall: `"%ProgramFiles%\AirLLM\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.

**Portable:** `AirLLM-<version>-windows-x64.zip` contains the same files without an installer. Unzip it anywhere and run `airllm.cmd app` from that folder.

Your data lives in `%USERPROFILE%\.airllm`.

## Verify a download

Every release has a `SHA256SUMS` file and a signed **build provenance attestation** that proves the file was built by this repository's workflow from a given commit.

```sh
sha256sum -c SHA256SUMS --ignore-missing          # checks the files you downloaded
gh attestation verify <file> --owner RudraLabs-dev
```

On Windows PowerShell: `Get-FileHash .\AirLLM-<version>-setup-x64.exe -Algorithm SHA256`, then compare with the line in `SHA256SUMS`.
(`--owner` also verifies releases up to v4.0.0-4, which were signed while the repository had another name.)

## Upgrade

Install the newer package over the old one: `sudo apt install ./airllm_<newer>.deb`, `sudo dnf install ./airllm-<newer>.rpm`, or run the new Windows installer.
Your data in `~/.airllm` is kept. The installer uses a fixed product ID, so Windows treats it as an upgrade.

A CUDA overlay you enabled is also kept. If the new version ships a different PyTorch version, run `airllm-enable-cuda` again (the installer reminds you).

## Uninstall

```sh
sudo apt remove airllm        # Debian / Ubuntu
sudo dnf remove airllm        # Fedora / RHEL family
```

On Windows use **Settings, Apps** (or the silent command above). Downloaded models and chats are in your home folder and are not removed: delete `~/.airllm` (`%USERPROFILE%\.airllm`) yourself if you want the space back.
To go back from CUDA to the bundled CPU build without uninstalling, run `airllm-enable-cuda disable`.
