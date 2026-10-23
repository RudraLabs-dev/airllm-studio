# Development

How to work on AirLLM Studio and its packaging. Everything here is checked by CI on every pull request.

## Repository map

```text
studio/                        AirLLM Studio (Python package `airllm_studio`)
├── src/airllm_studio/         server, engine, store, CLI... (see Architecture)
│   └── web/                   the UI: index.html, app.js, app.css, icons, fonts
├── tests/                     pytest suite; uses a fake engine, no torch needed
└── tools/                     dev_server.py (UI with a fake engine), make_icons.py
packaging/                     everything that builds installers
├── versions.env               every pin
├── linux/  windows/           payload builders, nfpm config, Inno Setup script, launchers
├── ci/                        version and ref resolution, container install test
└── tests/                     smoke_test.py, studio_e2e.py (run on built payloads)
scripts/                       dev-setup.sh (AirLLM contributor clone), check-wiki.py
wiki/                          the pages you are reading
.github/workflows/             release, watch-upstream, lint, wiki
```

## Run the tests

No GPU, model or PyTorch is needed for the Studio tests:

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install fastapi uvicorn huggingface-hub pytest httpx ruff pillow numpy scipy
pip install --no-deps ./studio             # no-deps: skips airllm and therefore torch

python -m pytest -q studio/tests           # about 80 tests, a few seconds
ruff check --select E,F,W,B --line-length 120 --target-version py310 studio packaging/tests
node --check studio/src/airllm_studio/web/app.js
python scripts/check-wiki.py wiki          # if you touched the wiki
```

These are the same commands as the *Lint* workflow. If you run the tests with a Python that has torch and AirLLM installed (for example `airllm-python` from a package), use a timeout: a test that triggers real model loading would otherwise hang.

The API tests use `FakeEngine` from `studio/tests/conftest.py`, which "generates" a fixed reply and reports fake layer progress. Real generation is covered by `packaging/tests/studio_e2e.py`: it builds a tiny random Llama model (and a tiny vision-language one), starts a real server, and exercises both APIs, the CLI and the web UI. CI runs it on every built payload and every installed package.

## Work on the UI

```sh
python studio/tools/dev_server.py 8765     # then open http://127.0.0.1:8765
```

It starts the real server with a fake slow engine and a few seeded models (one mid-download), so you can work on the UI without torch. The UI is plain JavaScript with no build step; edit the files in `web/` and reload. Keep it dependency-free and make no external requests.

## Run Studio against real models

Use a package install (`airllm-python`), or a virtualenv with `torch` and `airllm` plus `pip install -e ./studio`:

```sh
AIRLLM_HOME=/tmp/airllm-dev airllm serve --log-level debug
```

A separate `AIRLLM_HOME` keeps your real chats and models out of the experiment.

## Conventions

* **Small pull requests, one topic each.** Pipeline pins: one per pull request.
* **Tests with the change.** API behaviour gets a test in `studio/tests`; anything touching install, launchers or packaging is covered by the install test in CI.
* **Security-sensitive code** (`security.py`, the custom-code gate in `store.py`, upload limits) needs a test for the refusal as well as for the happy path.
* **Wording in the UI** is plain and short; error messages say what happened and what to do.
* **No telemetry, no network calls** except Hugging Face and the PyTorch index.
* **Do not change `AppId`** in `airllm.iss`: Windows uses it to recognise upgrades.
* Shell scripts pass `shellcheck`; PowerShell passes PSScriptAnalyzer; workflows pass `actionlint`.
* Python 3.10+ syntax (the package declares `requires-python >=3.10`; the bundled interpreter is newer).

## Common changes

| I want to... | Do this |
|---|---|
| Add a suggested model | Add an entry to `catalog.py` (name, title, summary, download size, VRAM, tags). Anything on Hugging Face can already be pulled |
| Support a new model family | Usually nothing: it arrives with a new AirLLM release, which the pipeline packages. If AirLLM needs a fix, contribute it upstream ([CONTRIBUTING](https://github.com/RudraLabs-dev/airllm-studio/blob/main/CONTRIBUTING.md)) and test with `source_repo = RudraLabs-dev/airllm` |
| Add a setting | Add the field to `Settings` in `config.py`, validate it in `SettingsStore.update`, add the control to `index.html` and `app.js`, document it in [Configuration](Configuration) |
| Add an API endpoint | Add it in `server.py`, a test in `studio/tests/test_api.py`, and a row in [API Reference](API-Reference). Endpoints that act on the host must call `local_only` |
| Bump the Studio version | `version` in `studio/pyproject.toml` **and** `__version__` in `studio/src/airllm_studio/__init__.py` (keep them equal) |
| Ship it | Merge, then run *Build & release packages* with a higher `pkg_release` ([Build and Release Pipeline](Build-and-Release-Pipeline)) |
| Change a pinned tool | Edit `packaging/versions.env` in its own pull request; the PR build proves it works |

## Editing this wiki

The wiki is source-controlled in `wiki/`:

1. Edit or add Markdown files in `wiki/`. File name = page title (`Command-Line.md` is *Command Line*); use dashes, not spaces.
2. Link pages with plain Markdown links without extension: `[Security](Security)`, `[CUDA troubleshooting](Troubleshooting#cuda)`. Add new pages to `_Sidebar.md`.
3. Run `python scripts/check-wiki.py wiki`.
4. Open a pull request. When it is merged to `main`, the *Publish wiki* workflow updates the GitHub wiki. Edits made directly in the GitHub wiki editor are overwritten.

Links between pages are written for the wiki (`[Security](Security)`), so they look broken when you browse the `wiki/` folder in GitHub's file viewer; they work on the published wiki.

Write for readers who have not seen the code: say what to do, what they will see, and what to do if it does not work. Verify every UI label and command against the application before writing it down.

## Releasing checklist

- [ ] Pull requests merged, `main` green
- [ ] Studio version bumped if user-visible behaviour changed
- [ ] Run *Build & release packages* (`pkg_release` + 1), all jobs green: nine Linux images and the Windows install test
- [ ] Release is public with 6 packages + `SHA256SUMS`; `gh attestation verify` works on one file
- [ ] Wiki updated for changed behaviour (same pull request as the change, ideally)
