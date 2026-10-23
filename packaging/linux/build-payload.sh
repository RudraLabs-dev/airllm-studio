#!/usr/bin/env bash
# Build the self-contained AirLLM payload that the .deb and .rpm install under /opt/airllm.
#
# Usage: sudo build-payload.sh --wheel dist/airllm-X.Y.Z-py3-none-any.whl --studio-wheel dist/airllm_studio-*.whl
#                              [--prefix /opt/airllm] [--arch x86_64|aarch64] [--skip-e2e]
#
# The payload is built *at its final install path*, so every absolute path pip bakes in
# (script shebangs, RECORD files) is already correct; nfpm then packs the directory verbatim.
# Optional env for BUILDINFO: AIRLLM_SOURCE_REPO, AIRLLM_SOURCE_REF, AIRLLM_SOURCE_SHA, PKG_VERSION.
set -euo pipefail
umask 022
# shellcheck source=../lib/common.sh
source "$(dirname "$0")/../lib/common.sh"
load_versions

prefix=/opt/airllm
arch="$(uname -m)"
wheel=""
studio_wheel=""
run_e2e=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wheel)  wheel="$2"; shift 2 ;;
    --studio-wheel) studio_wheel="$2"; shift 2 ;;
    --skip-e2e) run_e2e=0; shift ;;
    --prefix) prefix="$2"; shift 2 ;;
    --arch)   arch="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ -f "$wheel" ]] || die "--wheel must point to the airllm wheel built from source"
wheel="$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")"
[[ -f "$studio_wheel" ]] || die "--studio-wheel must point to the airllm_studio wheel"
studio_wheel="$(cd "$(dirname "$studio_wheel")" && pwd)/$(basename "$studio_wheel")"
case "$arch" in x86_64|aarch64) ;; *) die "unsupported arch: $arch" ;; esac
[[ ! -e "$prefix" ]] || die "$prefix already exists; remove it first (refusing to mix two builds)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$prefix/bin" "$prefix/share/airllm"

# --- 1. Standalone CPython, checksum-verified ---------------------------------------------
asset="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-${arch}-unknown-linux-gnu-install_only_stripped.tar.gz"
base="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}"
log "Fetching $asset"
fetch "$base/SHA256SUMS" "$work/SHA256SUMS"
fetch "$base/${asset/+/%2B}" "$work/$asset"
expected="$(awk -v a="$asset" '$2 == a { print $1 }' "$work/SHA256SUMS")"
[[ -n "$expected" ]] || die "$asset is not listed in SHA256SUMS of $PBS_RELEASE"
[[ "$(sha256_of "$work/$asset")" == "$expected" ]] || die "checksum mismatch for $asset"
tar -xzf "$work/$asset" -C "$prefix"          # -> $prefix/python
py="$prefix/python/bin/python3"
"$py" -VV

# The interpreter is private to this package, so pip may manage it.
rm -f "$("$py" -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')/EXTERNALLY-MANAGED"

export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PIP_NO_INPUT=1 PIP_ROOT_USER_ACTION=ignore

# --- 2. PyTorch, from its own index only -------------------------------------------------
# Installing torch on its own (no --extra-index-url) keeps PyPI's much larger CUDA build out.
# torchvision: the image processors of vision-language models need it (same index, matching build).
log "Installing torch + torchvision from $TORCH_INDEX_URL"
"$py" -m pip install --index-url "$TORCH_INDEX_URL" torch torchvision
torch_version="$("$py" -c 'import importlib.metadata as m; print(m.version("torch"))')"
vision_version="$("$py" -c 'import importlib.metadata as m; print(m.version("torchvision"))')"
printf 'torch==%s\ntorchvision==%s\n' "$torch_version" "$vision_version" > "$work/constraints.txt"

# --- 3. AirLLM and the rest of its dependencies from PyPI, holding torch in place --------
log "Installing $(basename "$wheel") + $(basename "$studio_wheel") (torch pinned at $torch_version)"
"$py" -m pip install --constraint "$work/constraints.txt" "$wheel" "$studio_wheel"
"$py" -m pip check

# Byte-compile the stdlib too: /opt is root-owned, so normal users could never cache .pyc there.
"$py" -m compileall -q -j 0 "$("$py" -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')" >/dev/null || true

# --- 4. Launchers ----------------------------------------------------------------------
install -m 0755 "$PACKAGING_DIR/linux/bin/airllm-python" "$prefix/bin/airllm-python"
install -m 0755 "$PACKAGING_DIR/linux/bin/airllm" "$prefix/bin/airllm"
sed "s/@DEFAULT_CUDA_VARIANT@/${DEFAULT_CUDA_VARIANT}/g" \
  "$PACKAGING_DIR/linux/bin/airllm-enable-cuda" > "$prefix/bin/airllm-enable-cuda"
chmod 0755 "$prefix/bin/airllm-enable-cuda"

# --- 5. Build metadata (handy in bug reports: `cat /opt/airllm/share/airllm/BUILDINFO`) ---
airllm_version="$("$py" -c 'import importlib.metadata as m; print(m.version("airllm"))')"
studio_version="$("$py" -c 'import importlib.metadata as m; print(m.version("airllm-studio"))')"
"$py" -m pip freeze --all > "$prefix/share/airllm/requirements.lock"
cat > "$prefix/share/airllm/BUILDINFO" <<EOF
airllm_version=$airllm_version
studio_version=$studio_version
package_version=${PKG_VERSION:-unknown}
source_repo=${AIRLLM_SOURCE_REPO:-unknown}
source_ref=${AIRLLM_SOURCE_REF:-unknown}
source_sha=${AIRLLM_SOURCE_SHA:-unknown}
python=$PYTHON_VERSION (python-build-standalone $PBS_RELEASE)
torch=$torch_version
torchvision=$vision_version
arch=$arch
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# --- 6. Smoke test the payload before it is packed ---------------------------------------
log "Smoke testing payload"
"$prefix/bin/airllm-python" "$PACKAGING_DIR/tests/smoke_test.py" --expect-version "$airllm_version"
"$prefix/bin/airllm" --version
if [[ "$run_e2e" == 1 ]]; then
  log "AirLLM Studio end-to-end test (tiny local model, offline)"
  "$prefix/bin/airllm-python" -I "$PACKAGING_DIR/tests/studio_e2e.py" --airllm "$prefix/bin/airllm"
fi

# Upstream tarballs ship some group-writable files; nothing under /opt should be.
chmod -R go-w "$prefix"

du -sh "$prefix" >&2
log "Payload ready at $prefix"
