<#
.SYNOPSIS
  Build the self-contained AirLLM payload for Windows x64 (staging dir for the installer and zip).

.DESCRIPTION
  Layout produced in -Stage:
    python\               standalone CPython (python-build-standalone) with torch + airllm installed
    airllm-python.cmd     launcher, works from any install location (no absolute paths baked in)
    airllm.cmd            AirLLM Studio CLI (serve, app, pull, run, ...); airllm.ico for shortcuts
    airllm-enable-cuda.cmd / .ps1   swap CPU PyTorch for a CUDA build after install
    share\airllm\         BUILDINFO, requirements.lock
    LICENSE.txt           AirLLM licence + packaging notice

.EXAMPLE
  pwsh packaging/windows/build-payload.ps1 -Wheel dist/airllm-4.0.0-py3-none-any.whl `
    -StudioWheel dist/airllm_studio-1.0.0-py3-none-any.whl -License src/LICENSE -PackageVersion 4.0.0-1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Wheel,
    [Parameter(Mandatory)] [string] $StudioWheel,
    [Parameter(Mandatory)] [string] $License,
    [string] $Stage = 'build/stage',
    [string] $PackageVersion = 'unknown',
    [switch] $SkipE2E
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$PSNativeCommandUseErrorActionPreference = $true   # non-zero exit from a native tool = terminating error
$ProgressPreference = 'SilentlyContinue'            # Invoke-WebRequest is 10x faster without the progress bar

$packagingDir = Split-Path -Parent $PSScriptRoot

# --- versions.env (environment variables of the same name win, like the Linux scripts) ----
$cfg = @{}
foreach ($line in Get-Content (Join-Path $packagingDir 'versions.env')) {
    if ($line -match '^\s*(#|$)') { continue }
    $key, $value = $line -split '=', 2
    $override = [Environment]::GetEnvironmentVariable($key)
    $cfg[$key] = if ($override) { $override } else { $value }
}

function Get-Download([string] $Url, [string] $Path) {
    for ($i = 1; $i -le 5; $i++) {
        try { Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing; return }
        catch { if ($i -eq 5) { throw }; Write-Warning "download failed ($i/5): $_"; Start-Sleep -Seconds (3 * $i) }
    }
}

$Wheel = (Resolve-Path $Wheel).Path
$StudioWheel = (Resolve-Path $StudioWheel).Path
$License = (Resolve-Path $License).Path
if (Test-Path $Stage) { throw "$Stage already exists; remove it first (refusing to mix two builds)" }
New-Item -ItemType Directory -Force -Path $Stage, "$Stage/share/airllm" | Out-Null
$Stage = (Resolve-Path $Stage).Path
$work = Join-Path ([IO.Path]::GetTempPath()) ("airllm-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null

try {
    # --- 1. Standalone CPython, checksum-verified ---------------------------------------
    $asset = "cpython-$($cfg.PYTHON_VERSION)+$($cfg.PBS_RELEASE)-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
    $base = "https://github.com/astral-sh/python-build-standalone/releases/download/$($cfg.PBS_RELEASE)"
    Write-Host "==> Fetching $asset"
    Get-Download "$base/SHA256SUMS" "$work/SHA256SUMS"
    Get-Download "$base/$($asset.Replace('+', '%2B'))" "$work/$asset"
    $expected = (Get-Content "$work/SHA256SUMS" | Where-Object { $_ -match "\s$([regex]::Escape($asset))$" }) -replace '\s.*$', ''
    if (-not $expected) { throw "$asset is not listed in SHA256SUMS" }
    $actual = (Get-FileHash -Algorithm SHA256 "$work/$asset").Hash.ToLower()
    if ($actual -ne $expected) { throw "checksum mismatch for $asset" }
    tar -xzf "$work/$asset" -C $Stage            # -> $Stage\python\python.exe
    $py = Join-Path $Stage 'python\python.exe'
    & $py -VV

    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Stage 'python\Lib\EXTERNALLY-MANAGED')
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'; $env:PIP_NO_CACHE_DIR = '1'; $env:PIP_NO_INPUT = '1'

    # --- 2. PyTorch from its own index only, then 3. airllm with torch held in place -----
    # torchvision: the image processors of vision-language models need it (same index, matching build).
    Write-Host "==> Installing torch + torchvision from $($cfg.TORCH_INDEX_URL)"
    & $py -m pip install --no-warn-script-location --index-url $cfg.TORCH_INDEX_URL torch torchvision
    $torchVersion = & $py -c "import importlib.metadata as m; print(m.version('torch'))"
    $visionVersion = & $py -c "import importlib.metadata as m; print(m.version('torchvision'))"
    Set-Content -Path "$work/constraints.txt" -Value "torch==$torchVersion`ntorchvision==$visionVersion" -Encoding ascii

    Write-Host "==> Installing $(Split-Path -Leaf $Wheel) + $(Split-Path -Leaf $StudioWheel) (torch pinned at $torchVersion)"
    & $py -m pip install --no-warn-script-location --constraint "$work/constraints.txt" $Wheel $StudioWheel
    & $py -m pip check
    # Pre-compile everything: Program Files is read-only for normal users, so no runtime .pyc cache.
    try { & $py -m compileall -q -j 0 (Join-Path $Stage 'python\Lib') | Out-Null }
    catch { Write-Warning "compileall reported errors (non-fatal): $_" }

    # --- 4. Launchers and licence ----------------------------------------------------------
    foreach ($f in 'airllm-python.cmd', 'airllm-enable-cuda.cmd', 'airllm-shell.cmd', 'airllm.cmd') {
        Copy-Item (Join-Path $PSScriptRoot $f) $Stage
    }
    Copy-Item (Join-Path $packagingDir '..\studio\src\airllm_studio\web\airllm.ico') $Stage
    (Get-Content -Raw (Join-Path $PSScriptRoot 'airllm-enable-cuda.ps1')).Replace('@DEFAULT_CUDA_VARIANT@', $cfg.DEFAULT_CUDA_VARIANT) |
        Set-Content -NoNewline -Encoding utf8 (Join-Path $Stage 'airllm-enable-cuda.ps1')
    $notice = @"
AirLLM for Windows, packaged by $($cfg.PKG_VENDOR) ($($cfg.PKG_HOMEPAGE)).
AirLLM itself: https://github.com/$($cfg.UPSTREAM_REPO) - licensed under the Apache License 2.0 below.
Bundled third-party components (CPython, PyTorch, transformers, ...) keep their own licences;
see python\Lib\site-packages\*\licenses and python\LICENSE.txt.
AirLLM Studio is an independent project and is not affiliated with or endorsed by the AirLLM authors.

"@
    Set-Content -Encoding utf8 -Path (Join-Path $Stage 'LICENSE.txt') -Value ($notice + (Get-Content -Raw $License))

    # --- 5. Build metadata --------------------------------------------------------------
    $airllmVersion = & $py -c "import importlib.metadata as m; print(m.version('airllm'))"
    $studioVersion = & $py -c "import importlib.metadata as m; print(m.version('airllm-studio'))"
    & $py -m pip freeze --all | Set-Content -Encoding utf8 (Join-Path $Stage 'share\airllm\requirements.lock')
    @(
        "airllm_version=$airllmVersion"
        "studio_version=$studioVersion"
        "package_version=$PackageVersion"
        "source_repo=$($env:AIRLLM_SOURCE_REPO)"
        "source_ref=$($env:AIRLLM_SOURCE_REF)"
        "source_sha=$($env:AIRLLM_SOURCE_SHA)"
        "python=$($cfg.PYTHON_VERSION) (python-build-standalone $($cfg.PBS_RELEASE))"
        "torch=$torchVersion"
        "torchvision=$visionVersion"
        "arch=x86_64"
        "built_at=$((Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    ) | Set-Content -Encoding utf8 (Join-Path $Stage 'share\airllm\BUILDINFO')

    # --- 6. Smoke test the staged payload -----------------------------------------------
    Write-Host '==> Smoke testing payload'
    & (Join-Path $Stage 'airllm-python.cmd') (Join-Path $packagingDir 'tests\smoke_test.py') --expect-version $airllmVersion
    & (Join-Path $Stage 'airllm.cmd') --version
    if (-not $SkipE2E) {
        Write-Host '==> AirLLM Studio end-to-end test (tiny local model, offline)'
        & $py -I (Join-Path $packagingDir 'tests\studio_e2e.py') --airllm (Join-Path $Stage 'airllm.cmd')
    }

    $size = (Get-ChildItem -Recurse -File $Stage | Measure-Object -Sum Length).Sum / 1MB
    Write-Host ("==> Payload ready at {0} ({1:N0} MB)" -f $Stage, $size)
}
finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $work
}
