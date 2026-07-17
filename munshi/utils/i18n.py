"""English/Hindi translation loading and lookup — relocated from app.py.

Parameterized on `app_dir` (rather than closing over app.py's APP_DIR global)
for the same reason as config.resolve_app_dir: this module's own location
inside munshi/ is not where translations/hi.json lives relative to.

`t()` reads Flask's `session`, so it isn't fully dependency-free like
utils/formatting.py or utils/gst.py — that's inherent to being a
request-scoped language lookup, not something worth engineering around.
"""
import json
import logging
import os
import sys

from flask import session

logger = logging.getLogger('munshi.i18n')

SUPPORTED_LANGS = ('en', 'hi')
_TRANSLATIONS = {}


def load_translations(app_dir):
    """Load translations/hi.json (a flat English→Hindi map). Looks alongside
       the script (dev runs) and inside the PyInstaller _MEIPASS bundle
       (packaged runs). Any failure just leaves the map empty → all-English."""
    global _TRANSLATIONS
    candidates = []
    bundle_dir = getattr(sys, '_MEIPASS', None)
    if bundle_dir:
        candidates.append(os.path.join(bundle_dir, 'translations', 'hi.json'))
    candidates.append(os.path.join(app_dir, 'translations', 'hi.json'))
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _TRANSLATIONS = data
                    return
        except Exception as e:
            logger.warning(f'Could not load translations from {path}: {e}')
    _TRANSLATIONS = {}


def t(s):
    """Translate English source string `s` to Hindi when the current session
       language is 'hi' and a translation exists; otherwise return `s`
       unchanged. Safe to call outside a request context."""
    if not s:
        return s
    try:
        if session.get('lang') == 'hi':
            return _TRANSLATIONS.get(s, s)
    except Exception:
        pass
    return s
