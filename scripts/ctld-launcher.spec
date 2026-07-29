# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ctld-launcher.

Bundles:
  - src/ctld_launcher/main.py (entry point)
  - assets/                   (app icon)
  - hamlib-bundle/            (rigctld/rotctld/rigctl/rotctl + libhamlib +
                                Python bindings, downloaded by CI from this
                                repo's own hamlib-bundle release — see
                                .github/workflows/build-hamlib.yml — placed
                                under the "hamlib/" prefix so
                                core/hamlib_locator.py's bundled_hamlib_dir()
                                finds it via sys._MEIPASS/hamlib at runtime)
"""

import sys
from pathlib import Path

block_cipher = None

# Repository root (one level up from scripts/)
ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is injected by PyInstaller)
SRC = ROOT / "src"

# --------------------------------------------------------------------------- #
# hamlib-bundle (downloaded by CI into hamlib-bundle/ relative to repo root).
#
# Deliberately added via `datas` (plain file copy), not `binaries`:
# PyInstaller's binary-collection path runs its own dependency analysis and
# rewrites install names/rpaths on macOS/Linux, which would fight with the
# $ORIGIN/@loader_path-relative, already-relocatable layout the
# build-hamlib.yml CI produced and verified (see that workflow's comments
# on the RUNPATH/patchelf and dylibbundler fixes). `datas` just copies the
# files as-is (shutil.copy2, which preserves the executable bit) and leaves
# them alone.
# --------------------------------------------------------------------------- #
hamlib_datas: list[tuple[str, str]] = []
_hamlib_dir = ROOT / "hamlib-bundle"
if _hamlib_dir.exists():
    for _f in _hamlib_dir.iterdir():
        if _f.is_file():
            hamlib_datas.append((str(_f), "hamlib"))

# --------------------------------------------------------------------------- #
# Data files
# --------------------------------------------------------------------------- #
datas = [
    (str(ROOT / "assets"), "assets"),
    # i18n .mo catalogs (see src/ctld_launcher/i18n.py's _locale_dir(),
    # which looks for this exact "locale" prefix under sys._MEIPASS)
    (str(ROOT / "locale"), "locale"),
] + hamlib_datas

hidden_imports = [
    "PySide6.QtSvg",
]

# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
a = Analysis(
    [str(SRC / "ctld_launcher" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

# --------------------------------------------------------------------------- #
# Executable
# --------------------------------------------------------------------------- #
_icon_dir = ROOT / "assets"
if sys.platform == "win32":
    _exe_icon = str(_icon_dir / "icon.ico") if (_icon_dir / "icon.ico").exists() else None
elif sys.platform == "darwin":
    _exe_icon = str(_icon_dir / "icon.icns") if (_icon_dir / "icon.icns").exists() else None
else:
    _exe_icon = str(_icon_dir / "icon_256.png") if (_icon_dir / "icon_256.png").exists() else None

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ctld-launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no terminal window on Windows/macOS
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_exe_icon,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ctld-launcher",
)

# macOS: also build an .app bundle
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="ctld-launcher.app",
        icon=_exe_icon,
        bundle_identifier="com.jf9som.ctld-launcher",
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "LSUIElement": True,  # tray-only app: no Dock icon needed
        },
    )
