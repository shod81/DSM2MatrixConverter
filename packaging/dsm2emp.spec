# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Dsm2Empirum single-EXE distribution (Task T-100).

Builds two self-contained onefile executables (Chapter 9.6):

* ``Dsm2Empirum.exe``    - GUI (windowed, no console), falls back to the CLI
                           when started with arguments.
* ``Dsm2EmpirumCmd.exe`` - CLI (console), used for scripting and selftest.

Bundled read-only resources (resolved via ``dsm2emp._resources.resource_root``):

* ``dsm2emp/data/assets/`` (report template, prompts, schemas, icon)
* ``dsm2emp/data/rules/dsm_to_empirum.yaml``
* ``dsm2emp/data/reference/*.yaml`` (Empirum syntax reference)

AV hardening (Risk R-08): UPX is disabled and no packer/compression beyond
zlib is used - see docs/BUILD.md.
"""

import os

ROOT = os.path.normpath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

datas = [
    (os.path.join(SRC, "dsm2emp", "data"), "dsm2emp/data"),
    (os.path.join(SRC, "dsm2emp", "reference", "*.yaml"), "dsm2emp/reference"),
]

# Qt slimming: the GUI only uses QtCore/QtGui/QtWidgets. Everything else is
# excluded so PyInstaller neither pulls the modules nor their plugins/binaries
# (hooks-contrib selects the remaining Qt plugins from actual imports).
qt_excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtAxContainer",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
]
tooling_excludes = [
    "hypothesis",
    "pytest",
    "pytest_cov",
    "pytestqt",
    "respx",
    "setuptools",
    "tkinter",
]

common_kwargs = dict(
    pathex=[SRC],
    datas=datas,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=qt_excludes + tooling_excludes,
    noarchive=False,
    optimize=1,
)

icon_path = os.path.join(SRC, "dsm2emp", "data", "assets", "icon.ico")
icon = icon_path if os.path.exists(icon_path) else None

gui_a = Analysis(
    [os.path.join(SPECPATH, "gui_main.py")],
    binaries=[],
    **common_kwargs,
)
cmd_a = Analysis(
    [os.path.join(SPECPATH, "cmd_main.py")],
    binaries=[],
    **common_kwargs,
)

gui_pyz = PYZ(gui_a.pure)
cmd_pyz = PYZ(cmd_a.pure)

EXE(
    gui_pyz,
    gui_a.scripts,
    gui_a.binaries,
    gui_a.datas,
    [],
    name="Dsm2Empirum",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

EXE(
    cmd_pyz,
    cmd_a.scripts,
    cmd_a.binaries,
    cmd_a.datas,
    [],
    name="Dsm2EmpirumCmd",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
