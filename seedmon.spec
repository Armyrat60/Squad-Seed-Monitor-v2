# PyInstaller spec for Squad Seed Monitor.
# CustomTkinter ships theme/asset data files that MUST be bundled or the app
# crashes at launch looking for them. collect_data_files handles that.
#
# Build:  pyinstaller seedmon.spec
# Output: dist/SquadSeedMonitor.exe  (one file, windowed)

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

import os

# Bundle CustomTkinter's data (themes, assets) and its submodules.
ctk_datas = collect_data_files("customtkinter")

# Bundle the app icon so the running window can set it too (not just the exe).
icon_path = os.path.join("assets", "icon.ico")
app_datas = [(icon_path, "assets")] if os.path.exists(icon_path) else []

# Optional runtime deps: include if installed so the exe has full features,
# but the app degrades gracefully if a user built without them.
hidden = []
for mod in ("plyer", "plyer.platforms", "plyer.platforms.win",
            "plyer.platforms.win.notification", "pystray", "PIL"):
    try:
        hidden += collect_submodules(mod)
    except Exception:
        pass

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=ctk_datas + app_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas"],  # keep the exe lean
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SquadSeedMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app, no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)
