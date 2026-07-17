from pathlib import Path


repository = Path(SPECPATH).parent
backend = repository / "backend"
runtime_site_packages = backend / ".venv" / "Lib" / "site-packages"

analysis = Analysis(
    [str(backend / "app" / "desktop_entry.py")],
    pathex=[str(backend), str(runtime_site_packages)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="glacial-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="glacial-backend",
)
