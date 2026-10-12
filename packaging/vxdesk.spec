# PyInstaller spec for the VxDesk desktop app (onedir, windowed).
# Build via scripts/build_desktop.py — do not invoke pyinstaller directly.

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, os.pardir))
BACKEND = os.path.join(REPO, "backend")
ENTRY = os.path.join(BACKEND, "vxdesk", "desktop.py")
ICON = os.path.join(REPO, "packaging", "icon.ico")

datas = [
    (os.path.join(REPO, "frontend", "dist"), "frontend_dist"),
    (os.path.join(REPO, "scripts", "samples"), "samples"),
]
binaries = []
hiddenimports = []

for pkg in ("dxcam", "rapidocr_onnxruntime", "onnxruntime", "pynput", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn / pywin32 bits that static analysis tends to miss
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("pygetwindow")
hiddenimports += [
    "win32gui",
    "win32con",
    "win32api",
    "win32process",
    "pythoncom",
    "pywintypes",
]

a = Analysis(
    [ENTRY],
    pathex=[BACKEND],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "pytest_asyncio", "mcp", "tests"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VxDesk",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # no console window
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VxDesk",
)
