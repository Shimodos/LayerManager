# Renders the promo clip for social posts: frames are painted inside 3ds Max
# (tools/promo/make_promo.py, 3dsmaxbatch, nothing is shown), then ffmpeg joins
# them into an mp4.
#
#   pwsh tools/make_promo.ps1                                  # -> dist\promo.mp4
#   pwsh tools/make_promo.ps1 -Out ..\LayerManagerSite\marketing\promo.mp4
param(
    [int]$Year = 2026,
    [string]$Out
)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $root "dist\promo.mp4" }
$frames = Join-Path $root "tests\out\promo_frames"
if (Test-Path $frames) { Remove-Item $frames -Recurse -Force }
New-Item -ItemType Directory -Force $frames, (Split-Path -Parent $Out) | Out-Null

$env:LM_SRC = Join-Path $root "src\layer_manager.py"
$env:LM_TEST = Join-Path $root "tools\promo\make_promo.py"
$env:LM_OUT = $frames
$env:LAYER_MANAGER_SETTINGS = "LayerManagerTests"   # keep the user's saved window and theme
$exe = "C:\Program Files\Autodesk\3ds Max $Year\3dsmaxbatch.exe"
$ErrorActionPreference = "Continue"                 # 3dsmaxbatch exits non-zero on start-up noise
& $exe (Join-Path $root "tests\run_in_max.ms") -log (Join-Path $root "tests\out\promo_$Year.log") 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

$log = Get-Content (Join-Path $frames "make_promo.log") -Raw
$log
if ($log -notmatch '^ok') { throw "frames were not rendered" }

& ffmpeg -y -loglevel error -framerate 30 -i (Join-Path $frames "frame_%05d.png") `
    -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -movflags +faststart $Out
"Built $Out ({0:N0} bytes)" -f (Get-Item $Out).Length
