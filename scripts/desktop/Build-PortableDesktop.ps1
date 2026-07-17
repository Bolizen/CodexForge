$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$frontend = Join-Path $repository "frontend"
$portableRoot = Join-Path $repository ".desktop-build\portable\Glacial"
$expectedRoot = [System.IO.Path]::GetFullPath((Join-Path $repository ".desktop-build"))
$resolvedPortable = [System.IO.Path]::GetFullPath($portableRoot)
if (-not $resolvedPortable.StartsWith($expectedRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to assemble portable output outside the repository build directory."
}

& (Join-Path $PSScriptRoot "Build-DesktopBackend.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $PSScriptRoot "Stage-DesktopSidecar.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location $frontend
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & npm.cmd run tauri:build -- --no-bundle
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

$application = Join-Path $frontend "src-tauri\target\release\glacial.exe"
$sidecarStage = Join-Path $frontend "src-tauri\binaries"
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "Tauri did not produce the expected production executable."
}

if (Test-Path -LiteralPath $portableRoot) {
    Remove-Item -LiteralPath $portableRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $portableRoot | Out-Null
Copy-Item -LiteralPath $application -Destination (Join-Path $portableRoot "Glacial.exe")
Copy-Item -LiteralPath (Join-Path $sidecarStage "glacial-backend-x86_64-pc-windows-msvc.exe") -Destination (Join-Path $portableRoot "glacial-backend.exe")
Copy-Item -LiteralPath (Join-Path $sidecarStage "_internal") -Destination (Join-Path $portableRoot "_internal") -Recurse
Write-Output $portableRoot
