"""Business logic. Route handlers (api/) should be thin: parse a request via a
schema, call a service function, render/redirect on the result.

Several functions here still reach back into app.py (via a deferred `import
app` inside the function body, not at module load time) for get_db(),
get_setting()/set_setting(), and log_audit() — those haven't migrated out of
app.py yet (settings is Phase 2, audit is Phase 10). A deferred import avoids
a circular import (app.py imports these services at module load) while still
letting an already-fully-loaded app.py be called back into once the app is
actually running. This seam disappears domain-by-domain as later phases land.
"""
