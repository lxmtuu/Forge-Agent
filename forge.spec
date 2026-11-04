# PyInstaller spec — build "forge" standalone executable
# Usage:  pyinstaller forge.spec
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [("server/static", "server/static")]  # web UI build (cho forge --web)
binaries = []
hiddenimports = ["engine", "server", "cli", "tui", "uvicorn", "textual"]

for pkg in ("textual", "rich"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["tui/launch.py"],
    pathex=[os.path.dirname(os.path.abspath(SPEC))],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="forge",
    console=True,
    upx=False,
)
