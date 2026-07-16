# PyInstaller spec for Munshi (Jainpur Logistic) desktop bundle.
# Builds a self-contained executable that includes Python + all Flask deps +
# templates + static assets. Customer's data (bills.db, uploads/, backups/)
# is intentionally NOT bundled — it lives next to the executable on disk so
# the customer always owns and can see their data.
#
# Build with:
#   pyinstaller --noconfirm build/munshi.spec
#
# Output:
#   dist/Munshi/Munshi(.exe)      ← the launcher
#   dist/Munshi/_internal/        ← bundled Python + libs + templates + static
#
# Resulting directory is what gets copied to a USB pendrive.

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Project root is one level up from this spec file
ROOT = os.path.abspath(os.path.dirname(SPECPATH))
APP_PY = os.path.join(ROOT, 'app.py')

# Hidden imports — modules PyInstaller can't auto-detect because they're
# loaded dynamically by Flask/Jinja or by our extension code paths.
hidden = [
    # Jinja2 lazy-loaded filters / extensions
    'jinja2.ext',
    # google-genai
    *collect_submodules('google.genai'),
    # google-auth-oauthlib and api client
    *collect_submodules('google_auth_oauthlib'),
    *collect_submodules('googleapiclient'),
    *collect_submodules('google.auth'),
    *collect_submodules('google.oauth2'),
    # PIL/Pillow lazy-loaded codecs
    'PIL._imagingft',
    # openpyxl
    *collect_submodules('openpyxl'),
    # pymupdf
    'fitz',
]

# Data files — anything not a .py that the app reads at runtime
datas = [
    (os.path.join(ROOT, 'templates'), 'templates'),
    (os.path.join(ROOT, 'static'),    'static'),
]
# Seed DB — committed to the repo. The app copies it to bills.db on first run
# if no bills.db exists yet. It must contain NO real identity, customers, or
# users — only generic rate-list + master-data scaffolding and GTA defaults.
# Operational tables (bills, challans, ledger, payments, audit) are empty, and
# supplier identity is blank so a fresh install's setup wizard fills it in.
_seed_path = os.path.join(ROOT, 'data', 'seed.db')
if os.path.exists(_seed_path):
    datas.append((_seed_path, 'data'))
# google-api-python-client ships its API discovery docs inside the package
datas += collect_data_files('googleapiclient')

block_cipher = None

a = Analysis(
    [APP_PY],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Trim — none of these are used by us
        'matplotlib', 'numpy', 'pandas', 'scipy', 'tk', 'tkinter',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython',
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Munshi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,   # keep console window so customer can see "running on http://..."
    disable_windowed_traceback=False,
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
    upx=False,
    upx_exclude=[],
    name='Munshi',
)
