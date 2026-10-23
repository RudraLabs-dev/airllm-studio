# Build and Release Pipeline

Everything that turns AirLLM source into installers is in this repository and runs on GitHub Actions. This page is for maintainers; users only need [Installation](Installation).

## What it produces

For each AirLLM version (and each package revision):

| Platform | Files |
|---|---|
| Debian / Ubuntu | `airllm_<version>_amd64.deb`, `airllm_<version>_arm64.deb` |
| Fedora / RHEL / Rocky / Alma | `airllm-<version>.x86_64.rpm`, `airllm-<version>.aarch64.rpm` |
| Windows x64 | `AirLLM-<version>-setup-x64.exe` (Inno Setup), `AirLLM-<version>-windows-x64.zip` (portable) |
| Integrity | `SHA256SUMS`, plus a signed build-provenance attestation for every file |

Releases are tagged **`v<airllm-version>-<revision>`**, for example `v4.0.0-5`: AirLLM 4.0.0, revision 5 of our packaging. A revision bump ships a new build of the same AirLLM version (Studio features, packaging fixes).

## The workflows

| Workflow | Trigger | Does |
|---|---|---|
| `release.yml` *Build & release packages* | manual; called by `watch-upstream`; pull requests touching `packaging/`, `studio/` or itself | builds, tests and (when allowed) publishes |
| `watch-upstream.yml` | daily 02:37 UTC (08:07 IST); manual | keeps the fork in sync; packages new upstream AirLLM releases |
| `lint.yml` | every pull request; pushes to `main` | shellcheck, actionlint, PSScriptAnalyzer, Studio unit tests (ruff, pytest), version-script self-test, web script syntax |
| `wiki.yml` | pushes to `main` that change `wiki/`; pull requests that change `wiki/`; manual | checks the wiki pages, publishes them to the GitHub wiki ([below](#the-wiki-pipeline)) |

Pull requests run the **whole build and all install tests but never publish**.

## Anatomy of a release run

```text
prepare ──► linux (x86_64, aarch64) ──► test-linux (9 container images) ──┐
   │                                                                       ├──► release
   └──────► windows (installer + zip, install test on a clean runner) ─────┘
```

**1. prepare** (Ubuntu): resolves the AirLLM ref (a tag, branch or commit; empty means the latest upstream release tag), checks the source out, computes every version string (`compute-version.sh`), runs the Studio unit tests, and builds the **AirLLM and AirLLM Studio wheels**. Branch or commit builds become pre-release snapshots such as `4.0.0+git20261014.ff35db2`.

**2. linux** (per architecture, native runners, no emulation): `build-payload.sh` builds the payload **at its final path** `/opt/airllm`, so every absolute path pip bakes in is already right:

1. download python-build-standalone and **verify its SHA-256**;
2. install `torch` and `torchvision` from the **CPU index only** (keeps the much larger CUDA build of PyPI out);
3. install the AirLLM and Studio wheels with torch pinned by a constraints file;
4. byte-compile, write launchers and `share/airllm/BUILDINFO` (source repo, ref, commit, torch and Python versions);
5. smoke test the payload and run the Studio end-to-end test offline.

`build-packages.sh` then packs the directory with **nfpm** into `.deb` and `.rpm` (zstd), adding the systemd unit, desktop entry, icons and maintainer scripts.

**3. test-linux**: installs each package with the distro's own tool (so declared dependencies are really checked) in a clean container, on **Debian 12 and 13, Ubuntu 22.04 and 24.04, Fedora (latest), Rocky 9, AlmaLinux 8** (x86_64), and Ubuntu 24.04 and Rocky 9 on aarch64: nine images. Each runs the smoke test as root and as a normal user, the Studio end-to-end test (a tiny offline model; Ubuntu additionally pulls a real Hugging Face model through the installed server), then uninstalls and checks that nothing is left behind.

**4. windows** (Windows Server 2025 runner): builds the payload with `build-payload.ps1` (same recipe, also writes `requirements.lock`), compiles the installer with **Inno Setup** and zips the portable copy, then **silently installs** it to a test folder, runs the smoke and end-to-end tests through the installed launcher, checks PATH and the Start-menu shortcut, uninstalls and verifies the folder and PATH entry are gone.

**5. release** (only if everything above passed, and never for pull requests): collects the artifacts, writes `SHA256SUMS`, creates a **build-provenance attestation** (`actions/attest-build-provenance`), writes the release notes, creates the release as a **draft**, uploads the files, and only then makes it public in one step, so nobody sees a half-filled release. If a *published* release with the same tag exists, the run fails and asks for a higher revision.

## Versions and pins

All toolchain pins are in **`packaging/versions.env`**: the AirLLM upstream and fork repositories, the Python version and python-build-standalone release, the PyTorch index, the default CUDA variant, the nfpm version, and package metadata (maintainer, vendor, homepage). Bump **one thing per pull request**. Environment variables of the same name override the file, so CI can test a change without editing it.

Third-party GitHub Actions are pinned to **full commit SHAs** with the version in a comment; Dependabot proposes updates weekly, grouped in one pull request.

## Running a release

**Manually:** Actions, *Build & release packages*, *Run workflow*:

| Input | Meaning |
|---|---|
| `airllm_ref` | AirLLM tag, branch or commit; empty = latest upstream release |
| `source_repo` | `lyogavin/airllm` (upstream) or `RudraLabs-dev/airllm` (our fork, for patches not yet merged upstream) |
| `pkg_release` | Package revision. Raise it to re-release the same AirLLM version |
| `publish` | Untick to build and test only |

**Automatically:** `watch-upstream.yml` looks daily for an upstream release tag that has no published release here yet, and calls `release.yml` with revision 1. It also fast-forwards the fork's `main` to upstream when the optional secret `FORK_SYNC_TOKEN` is set.

**Shipping a Studio change:** merge the pull request (its CI already built and tested everything), then run the workflow with `pkg_release` one higher than the last release of that AirLLM version.

## The wiki pipeline

The pages you are reading live in the **`wiki/`** folder of the repository and are published to the GitHub wiki by **`wiki.yml`**. Only the content of `wiki/` goes to the wiki.

* **Trigger:** a push to `main` that changes anything under `wiki/` (plus manual runs). Other changes never trigger it.
* **On pull requests** that touch `wiki/` only the check job runs; nothing is published.
* **Check:** `scripts/check-wiki.py wiki` verifies that `Home.md` exists, page names are valid, links between pages and images resolve, code fences are closed, and every page is linked from `_Sidebar.md`.
* **Publish:** clones `<repo>.wiki.git`, makes it an exact copy of `wiki/` (removed pages are removed), commits as `github-actions[bot]` with the source commit in the message, and pushes. If nothing changed, nothing is committed.
* **One-time setup:** GitHub creates the wiki repository only when the first page is created. Open the repository's **Wiki** tab, click *Create the first page*, save anything, then run the *Publish wiki* workflow once. The workflow fails with this exact instruction while the wiki does not exist yet.
* **Do not edit pages in the GitHub wiki editor**: the next publish overwrites them. Change `wiki/` through a pull request.

## Failure guide

| Failure | Where to look |
|---|---|
| Checksum mismatch while building the payload | The pinned Python release changed or a download was corrupted. Re-run; if it persists check `PBS_RELEASE` |
| A distro container fails to install | `packaging/ci/test-install.sh` output; usually a missing dependency in the nfpm `overrides` |
| Windows install test: *left behind after uninstall* | The uninstaller runs from `%TEMP%` and may need a few seconds; the test waits 60 s. A real failure means a running process kept a file open |
| `Release ... is already published` | Use a higher `pkg_release` |
| `watch-upstream` builds nothing | Upstream tag already packaged (a non-draft release `v<tag>-N` exists) |
| *Publish wiki* fails with *Wiki not initialised* | Create the first wiki page in the UI (above) |

## Building locally (Linux)

```sh
pipx run build --wheel --outdir dist /path/to/airllm/air_llm
pipx run build --wheel --outdir dist studio
sudo packaging/linux/build-payload.sh --wheel dist/airllm-*.whl --studio-wheel dist/airllm_studio-*.whl   # builds /opt/airllm
packaging/linux/build-packages.sh --version 4.0.0 --release 1 --out out                                      # .deb and .rpm in out/
```
