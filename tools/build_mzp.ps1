# Builds dist\LayerManager_<version>.mzp (an .mzp is a zip archive that
# 3ds Max unpacks and runs through mzp.run).
#
#   pwsh tools/build_mzp.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$source = Get-Content (Join-Path $root "src\layer_manager.py") -Raw
if ($source -notmatch 'VERSION = "([^"]+)"') { throw "VERSION not found in layer_manager.py" }
$version = $Matches[1]

foreach ($file in "installer\install.ms", "installer\mzp.run") {
    if (-not (Select-String -Path (Join-Path $root $file) -SimpleMatch $version -Quiet)) {
        throw "$file does not mention version $version"
    }
}

$stage = Join-Path $root "dist\stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item (Join-Path $root "installer\*") $stage -Recurse
Copy-Item (Join-Path $root "src\layer_manager.py") $stage

$name = "LayerManager_" + ($version -replace '\.', '')
$zip = Join-Path $root "dist\$name.zip"
$mzp = Join-Path $root "dist\$name.mzp"
foreach ($old in $zip, $mzp) { if (Test-Path $old) { Remove-Item $old } }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
Rename-Item $zip $mzp
Remove-Item $stage -Recurse -Force

"Built $mzp ({0:N0} bytes)" -f (Get-Item $mzp).Length
