# Runs tests/test_layer_manager.py inside every installed 3ds Max (2021+)
# through 3dsmaxbatch.exe and prints the reports.
#
#   pwsh tests/run_tests.ps1                 # all installed versions
#   pwsh tests/run_tests.ps1 -Years 2024     # just one
param(
    [int[]]$Years,
    [string]$Test = "test_layer_manager.py"
)

$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "tests\out"
New-Item -ItemType Directory -Force $out | Out-Null

if (-not $Years) {
    $Years = Get-ChildItem "C:\Program Files\Autodesk" -Directory -Filter "3ds Max 20*" |
        Where-Object { Test-Path (Join-Path $_.FullName "3dsmaxbatch.exe") } |
        ForEach-Object { [int]($_.Name -replace '^3ds Max ', '') } |
        Where-Object { $_ -ge 2021 } | Sort-Object
}

foreach ($year in $Years) {                 # never report a stale run
    $old = Join-Path $out "report_$year.txt"
    if (Test-Path $old) { Remove-Item $old }
}

$env:LM_SRC = Join-Path $root "src\layer_manager.py"
$env:LM_TEST = Join-Path $root "tests\$Test"
$env:LM_OUT = $out
$env:LAYER_MANAGER_SETTINGS = "LayerManagerTests"   # keep the user's saved window and theme
foreach ($year in $Years) {                 # one at a time: parallel instances crash
    $exe = "C:\Program Files\Autodesk\3ds Max $year\3dsmaxbatch.exe"
    & $exe (Join-Path $root "tests\run_in_max.ms") -log (Join-Path $out "max_$year.log") 2>&1 | Out-Null
}

$bad = 0
foreach ($year in $Years) {
    $report = Join-Path $out "report_$year.txt"
    "===== 3ds Max $year"
    if (Test-Path $report) {
        $text = Get-Content $report
        $text | Where-Object { $_ -notmatch '^ok ' }
        "{0} checks passed" -f ($text | Where-Object { $_ -match '^ok ' }).Count
        if (-not ($text -match '^RESULT: PASSED')) { $bad++ }
    } else {
        "no report - see tests\out\max_$year.log"
        $bad++
    }
}
exit $bad
