"""Configuration layer.

Mechanical relocation of the module-level constants that used to live at the
top of app.py (APP_DIR/DB_PATH/UPLOAD_DIR/BACKUP_DIR resolution, the per-install
Flask secret key, upload limits). Behavior is unchanged — see app.py's own
comments (now here) for why each of these is resolved the way it is.

`resolve_app_dir()` takes the caller's `__file__` explicitly rather than using
its own: this module's `__file__` is inside `munshi/`, not the project root, so
closing over it here would silently point a dev run at the wrong directory.
"""
import os
import sys
from datetime import timedelta


def resolve_app_dir(caller_file):
    """APP_DIR resolution:
         - Cloud/container mode: MUNSHI_APP_DIR env var wins outright, if set.
           Lets a hosted tenant's data (bills.db/uploads/backups/.flask_secret)
           live on a mounted volume (e.g. /data) while the code itself ships
           baked into the image — those must be separate directories, or every
           redeploy either wipes tenant data or requires baking the volume
           with a full code copy.
         - In source-run mode (`python3 app.py`): the caller's own directory.
         - In PyInstaller bundle mode: the directory of the EXECUTABLE (next to
           the customer's bills.db / uploads / backups). NOT sys._MEIPASS, which
           is a throwaway temp dir that gets a new random name every launch —
           using _MEIPASS would silently wipe the customer's data on every
           restart.
       `caller_file` must be the `__file__` of the top-level entrypoint
       (app.py), passed in explicitly — this module's own `__file__` lives
       inside the munshi/ package, not the project root.
    """
    env_dir = os.environ.get('MUNSHI_APP_DIR', '').strip()
    if env_dir:
        return os.path.abspath(env_dir)
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(caller_file))


def resolve_secret_key(app_dir, logger=None):
    """Per-install Flask secret_key. Three sources, first hit wins:
       1) FLASK_SECRET_KEY env var (production deploy, explicit control)
       2) APP_DIR/.flask_secret file (persisted random key, auto-generated
          on first run of a fresh install — different per customer)
       3) Fall back to a generated key + warn (the file write must have failed)
       This is critical for Munshi: every customer's session cookies must be
       signed with a UNIQUE secret, otherwise stealing one .exe + bills.db
       lets an attacker forge logins on every other customer's install."""
    env_val = os.environ.get('FLASK_SECRET_KEY', '').strip()
    if env_val:
        return env_val
    secret_path = os.path.join(app_dir, '.flask_secret')
    try:
        if os.path.exists(secret_path):
            with open(secret_path, 'r') as f:
                val = f.read().strip()
                if val and len(val) >= 32:
                    return val
        import secrets as _secrets
        val = _secrets.token_urlsafe(48)
        with open(secret_path, 'w') as f:
            f.write(val)
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass     # best-effort on Windows
        return val
    except Exception as e:
        import secrets as _secrets
        if logger:
            logger.warning(f'Could not persist .flask_secret: {e}; using ephemeral key (sessions reset on restart)')
        return _secrets.token_urlsafe(48)


class Config:
    """Paths and constants derived from a given APP_DIR. One instance per
       process; app.py builds it once at import time exactly as it built these
       as bare module globals before."""

    def __init__(self, app_dir):
        self.APP_DIR = app_dir
        self.DB_PATH = os.path.join(app_dir, 'bills.db')
        self.UPLOAD_DIR = os.path.join(app_dir, 'uploads')
        self.BACKUP_DIR = os.path.join(app_dir, 'backups')

        # Max upload size: 25 MB (one big photo of a multi-row ledger page is ~3 MB)
        self.MAX_CONTENT_LENGTH = 25 * 1024 * 1024
        # Stay signed in for 30 days when "session.permanent = True" is set on login
        self.PERMANENT_SESSION_LIFETIME = timedelta(days=30)

        self.ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.pdf', '.webp', '.gif', '.heic'}

        # Max files accepted in one /extract (photo -> bilty) batch. Unbounded
        # uploads would let one submit spawn a huge background job (each image
        # is fully decoded into memory + sent to Gemini one at a time), tying
        # up the extraction slot for a very long time.
        self.MAX_EXTRACTION_FILES = 25
