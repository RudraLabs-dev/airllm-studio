# Contributing to AirLLM as RudraLabs

We contribute to [lyogavin/airllm](https://github.com/lyogavin/airllm) through the org fork
[RudraLabs-dev/airllm](https://github.com/RudraLabs-dev/airllm). The fork's `main` is a clean mirror of upstream
(kept in sync daily by `watch-upstream.yml`); all work happens on short-lived branches that become upstream pull requests.

## Workflow

```sh
scripts/dev-setup.sh ~/src/airllm       # origin = our fork, upstream = lyogavin/airllm
cd ~/src/airllm
git switch main && git pull             # main tracks upstream/main
git switch -c fix/<short-topic>
# ... change, test, commit ...
git push -u origin fix/<short-topic>
gh pr create --repo lyogavin/airllm --head RudraLabs-dev:fix/<short-topic>
```

Rules of thumb:

* **Never commit to the fork's `main`.** It must fast-forward to upstream; a diverged main breaks the daily sync.
* **One topic per PR**, small and reviewable, with a clear description of the problem and how you tested it.
* Follow upstream's conventions and CI (`.github/workflows` in the upstream repo); don't add RudraLabs-specific files to upstream PRs.
* Check open issues/PRs upstream first to avoid duplicate work; link the issue you fix.
* Need a fix in our packages before upstream merges it? Run *Build & release packages* with
  `source_repo = RudraLabs-dev/airllm` and your branch as `airllm_ref` — it ships as a pre-release.

## Good first contributions found while packaging

* `air_llm/setup.py` uses `find_packages()`, so the wheel also installs a top-level **`tests`** package into
  `site-packages` (verified on 4.0.0). Excluding it — `find_packages(exclude=["tests", "tests.*"])` — avoids
  clashing with other projects' `tests` modules.
* The root `requirements.txt` pins old versions (e.g. `bitsandbytes==0.39.0`, `peft@v0.3.0`) that no longer match
  `setup.py`'s `install_requires`; it could be marked as training-only or refreshed.
* **Audio models in AirLLM.** AirLLM streams vision-language models with their vision tower kept resident
  (Qwen3.5/3.8, Kimi K3), but no class keeps an audio encoder resident, so speech models (Qwen2-Audio, Voxtral,
  Qwen-Omni) cannot run. A class per family with `resident: ['model.audio_tower', 'model.multi_modal_projector']`
  and the language model's layer names would let Studio's voice input light up for them.
