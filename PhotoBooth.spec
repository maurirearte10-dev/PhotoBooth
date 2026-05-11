# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Datos a empaquetar ─────────────────────────────────────────────────────────
datas = [
    ('assets',  'assets'),
    ('locales', 'locales'),
]
icon_path = os.path.join('assets', 'photobooth.ico')
datas += collect_data_files('customtkinter')

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports = [
    # CustomTkinter
    'customtkinter',
    *collect_submodules('customtkinter'),
    # PIL
    'PIL',
    'PIL._tkinter_finder',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageFilter',
    # OpenCV
    'cv2',
    # Requests / JWT
    'requests',
    'jwt',
    'charset_normalizer',
    'idna',
    'certifi',
    'urllib3',
    # Win32 (impresora)
    'win32print',
    'win32api',
    'win32con',
    'win32ui',
    'pywintypes',
    # Tkinter
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'tkinter.colorchooser',
    # Stdlib
    'threading',
    'subprocess',
    'json',
    'sqlite3',
    'hashlib',
    'uuid',
    'platform',
    'socket',
    'tempfile',
    'shutil',
    'time',
    'datetime',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'notebook'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhotoBooth',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon_path,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhotoBooth',
)
