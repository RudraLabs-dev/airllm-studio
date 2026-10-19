<#
.SYNOPSIS
  Switch AirLLM's bundled CPU-only PyTorch to a CUDA build (or back).

.EXAMPLE
  airllm-enable-cuda              # CUDA variant @DEFAULT_CUDA_VARIANT@ (default)
  airllm-enable-cuda cu126        # any variant served at download.pytorch.org/whl/<variant>
  airllm-enable-cuda disable      # back to the bundled CPU build
  airllm-enable-cuda status

.NOTES
  CUDA wheels go to <install dir>\cuda-site, which airllm-python.cmd puts first on the path.
  Installed under Program Files? The script asks Windows for Administrator rights (UAC) itself,
  before anything is downloaded.
  Re-run after upgrading AirLLM if the bundled torch version changed.
#>
param(
    [string] $Variant = '@DEFAULT_CUDA_VARIANT@',
    [switch] $Elevated      # set by the script itself when it relaunches as Administrator
)

$ErrorActionPreference = 'Stop'
$home_ = $PSScriptRoot
$py = Join-Path $home_ 'python\python.exe'
$cudaSite = Join-Path $home_ 'cuda-site'

function Exit-Script([int] $Code) {
    # The elevated window closes on exit: keep it open so its output can be read.
    if ($Elevated) { Read-Host "`nPress Enter to close this window" | Out-Null }
    exit $Code
}

function Stop-WithError([string] $Message, [int] $Code = 1) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    Exit-Script $Code
}

function Show-Status {
    if (Test-Path $cudaSite) {
        $v = Get-Content -ErrorAction SilentlyContinue (Join-Path $cudaSite '.airllm-variant')
        Write-Host "CUDA overlay: $v at $cudaSite"
    } else {
        Write-Host 'CUDA overlay: not installed (using bundled CPU build)'
    }
    & (Join-Path $home_ 'airllm-python.cmd') -c "import torch; print('torch', torch.__version__, '| CUDA available:', torch.cuda.is_available())"
}

function Test-Writable([string] $Dir) {
    $probe = Join-Path $Dir (".airllm-write-test-" + [guid]::NewGuid().ToString('N'))
    try { [IO.File]::WriteAllText($probe, ''); Remove-Item -Force $probe; return $true }
    catch { return $false }
}

function Confirm-WriteAccess {
    # Check before downloading ~2.5 GB, not after. Under Program Files a normal prompt cannot
    # write here: relaunch this script elevated (one UAC prompt) and pass its exit code on.
    if (Test-Writable $home_) { return }
    if ($Elevated) { Stop-WithError "cannot write to $home_, even as Administrator." }
    Write-Host "AirLLM is installed in $home_, which needs Administrator rights."
    Write-Host 'Asking Windows for permission (a UAC prompt will appear)...'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"",
                 '-Variant', $Variant, '-Elevated')
    try {
        $proc = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList $argList
    } catch {
        Stop-WithError ("Administrator permission was not given. Run 'airllm-enable-cuda' from an " +
                        "Administrator prompt, or reinstall AirLLM for the current user only.")
    }
    exit $proc.ExitCode
}

switch -Regex ($Variant) {
    '^(-h|--help|-help|/\?)$' { Get-Help $PSCommandPath -Detailed; exit 0 }
    '^(--)?status$'  { Show-Status; exit 0 }
    '^(--)?disable$' {
        Confirm-WriteAccess
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $cudaSite
        if (Test-Path $cudaSite) { Stop-WithError "could not remove $cudaSite (is AirLLM running? close it first)." }
        Write-Host 'CUDA overlay removed.'; Show-Status; Exit-Script 0
    }
    '^(cu\d+|rocm[\d.]+)$' { break }
    default { Stop-WithError "unknown variant '$Variant' (expected e.g. cu126, cu128, cu130)" 2 }
}

Confirm-WriteAccess

$torchVersion = (& $py -c "import importlib.metadata as m; print(m.version('torch').split('+')[0])").Trim()
# torchvision (used by vision models' image processors) must be the build that matches torch.
$visionVersion = $null
try { $visionVersion = (& $py -c "import importlib.metadata as m; print(m.version('torchvision').split('+')[0])" 2>$null) }
catch { $visionVersion = $null }   # Windows PowerShell 5.1 turns native stderr into an error under 'Stop'
$packages = @("torch==$torchVersion")
if ($LASTEXITCODE -eq 0 -and $visionVersion) { $packages += "torchvision==$("$visionVersion".Trim())" }
Write-Host "Installing $($packages -join ' ') ($Variant) into $cudaSite ..."

$tmp = "$cudaSite.new"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'; $env:PIP_NO_CACHE_DIR = '1'
& $py -m pip install --no-warn-script-location --target $tmp --index-url "https://download.pytorch.org/whl/$Variant" @packages
if ($LASTEXITCODE -ne 0) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp
    Stop-WithError "pip failed. Check your internet connection and that '$Variant' offers torch $torchVersion (see https://pytorch.org/get-started/locally/)."
}
Set-Content -Path (Join-Path $tmp '.airllm-variant') -Value $Variant
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $cudaSite
if (Test-Path $cudaSite) { Stop-WithError "could not replace $cudaSite (is AirLLM running? close it and try again)." }
Move-Item $tmp $cudaSite
Show-Status
Exit-Script 0
