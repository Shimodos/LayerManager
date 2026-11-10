# Renders screenshots and demo frames of the panel into docs\shots by running
# tools/shots/make_shots.py inside 3ds Max (3dsmaxbatch, nothing is shown).
#
#   pwsh tools/make_shots.ps1            # 3ds Max 2026
#   pwsh tools/make_shots.ps1 -Year 2024
param([int]$Year = 2026)

$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "docs\shots"
New-Item -ItemType Directory -Force (Join-Path $out "demo") | Out-Null

$env:LM_SRC = Join-Path $root "src\layer_manager.py"
$env:LM_TEST = Join-Path $root "tools\shots\make_shots.py"
$env:LM_OUT = $out
$env:LAYER_MANAGER_SETTINGS = "LayerManagerTests"   # keep the user's saved window and theme
$exe = "C:\Program Files\Autodesk\3ds Max $Year\3dsmaxbatch.exe"
& $exe (Join-Path $root "tests\run_in_max.ms") -log (Join-Path $root "tests\out\shots_$Year.log") 2>&1 | Out-Null

Get-Content (Join-Path $out "make_shots.log")
