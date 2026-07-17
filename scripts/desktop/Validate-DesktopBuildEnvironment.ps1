$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$buildPython = Join-Path $repository ".desktop-build\venv\Scripts\python.exe"
$runtimePython = Join-Path $repository "backend\.venv\Scripts\python.exe"
$lockFile = Join-Path $repository "backend\desktop-build-requirements.lock"

if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    throw "Desktop build Python is missing. Create it with: backend\.venv\Scripts\python.exe -m venv .desktop-build\venv"
}
if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    throw "Runtime backend Python is missing. Restore backend\.venv before building the packaged backend."
}
if (-not (Test-Path -LiteralPath $lockFile -PathType Leaf)) {
    throw "The exact desktop build requirements lock is missing."
}

$approved = @(
    "altgraph==0.17.5"
    "packaging==26.2"
    "pefile==2024.8.26"
    "pyinstaller==6.21.0"
    "pyinstaller-hooks-contrib==2026.6"
    "pywin32-ctypes==0.2.3"
    "setuptools==83.0.0"
) | Sort-Object
$packageJson = & $buildPython -m pip list --format=json
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the dedicated desktop build environment."
}
$packages = $packageJson | ConvertFrom-Json
$installed = $packages |
    Where-Object { $_.name -ne "pip" } |
    ForEach-Object { "$($_.name.ToLowerInvariant())==$($_.version)" } |
    Sort-Object
if (Compare-Object $approved $installed) {
    throw "Desktop build packages do not match the approved exact lock. Run the reviewed wheel-only pip command."
}

& $buildPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "The desktop build environment failed pip check."
}

$pyInstallerVersion = & $buildPython -m PyInstaller --version
if ($LASTEXITCODE -ne 0 -or $pyInstallerVersion.Trim() -ne "6.21.0") {
    throw "PyInstaller 6.21.0 is required in the dedicated desktop build environment."
}

Write-Output "Desktop build environment validated."
