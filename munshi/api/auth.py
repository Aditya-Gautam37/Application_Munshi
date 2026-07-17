"""Auth & Setup routes.

Plain view functions registered onto app.py's `app` object via
`app.add_url_rule(...)` in register(app) below — deliberately NOT a Flask
Blueprint. A Blueprint namespaces every endpoint as 'auth.login',
'auth.setup', etc., which would break all 25 `url_for('login')`-style calls
still in app.py (and 2 in templates) for routes that haven't migrated yet —
Flask blueprint endpoint-prefixing can't be disabled per-route. Registering
explicitly with the original endpoint names keeps every existing url_for()
call working unchanged; this is still the API layer the plan calls for
(route logic lives here, not inline in app.py), just without the blueprint
namespacing mechanism.

Thin routes: parse the request via a schema, call auth_service, render/redirect.
Business logic (validation, password hashing, lockout, audit side effects)
lives in services/auth_service.py; data access in repositories/user_repository.py.
"""
from flask import flash, redirect, render_template, request, session, url_for

from munshi.schemas.auth import (
    SetupForm, LoginForm, ChangePasswordForm, UserCreateForm,
)
from munshi.services import auth_service
from munshi.utils.i18n import t


def setup():
    """First-run wizard: the buyer names their firm and creates the owner login.
       If setup is already complete, there's nothing to do here — go home."""
    if auth_service.is_setup_complete():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        form = SetupForm.from_form(request.form)
        ok, error, gstin_note = auth_service.complete_setup(form)
        if not ok:
            return render_template('setup.html', error=error, form=request.form)

        session.clear()
        session['user'] = form.username
        session['role'] = 'admin'
        session['must_change_password'] = False
        session.permanent = True
        if gstin_note:
            flash(gstin_note)
        flash(f'Welcome to Munshi, {form.company_name}! Your account is ready.')
        return redirect(url_for('dashboard'))

    return render_template('setup.html', error=None, form={})


def setup_demo():
    """Load the sample demo dataset for a sales pitch, then hand off to login
       (demo user is 'Demo' / 'Demo')."""
    if auth_service.is_setup_complete():
        return redirect(url_for('login'))

    import app as _app  # APP_DIR — deferred import, see services/__init__.py
    ok, message = auth_service.load_demo_data(_app.APP_DIR)
    if not ok:
        flash(message)
        return redirect(url_for('setup'))

    flash('Sample demo data loaded. Sign in with username "Demo" and password "Demo".')
    return redirect(url_for('login'))


def login():
    raw_next = request.args.get('next') or request.form.get('next') or ''
    # Only allow relative in-site redirects (block open-redirect phishing):
    # a next URL must start with a single '/', not '//' (protocol-relative)
    # and not an absolute URL like https://evil.com.
    next_url = raw_next if (raw_next.startswith('/') and not raw_next.startswith('//')) else url_for('dashboard')

    if request.method == 'POST':
        form = LoginForm.from_request(request.form, request.args)
        status, payload = auth_service.attempt_login(form.username, form.password)

        if status == 'locked':
            mins = max(1, payload // 60)
            flash(f'Too many wrong attempts. Please wait about {mins} minute(s) before trying again.')
            return render_template('login.html', next_url=next_url)

        if status == 'ok':
            row = payload
            _lang = session.get('lang')          # preserve chosen language across the reset
            session.clear()
            if _lang:
                session['lang'] = _lang
            session['user'] = row.username
            session['role'] = row.role or 'operator'
            session['must_change_password'] = bool(row.must_change_password)
            session.permanent = True  # respect PERMANENT_SESSION_LIFETIME
            return redirect(next_url)

        flash(t('Invalid username or password.'))

    return render_template('login.html', next_url=next_url)


def logout():
    user = auth_service.current_user()
    auth_service.log_logout(user)
    _lang = session.get('lang')                  # keep the language choice after sign-out
    session.clear()
    if _lang:
        session['lang'] = _lang
    flash(t('Signed out.'))
    return redirect(url_for('login'))


def change_password():
    if not session.get('user'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        form = ChangePasswordForm.from_form(request.form)
        ok, message = auth_service.change_password(
            session['user'], form.old_password, form.new_password, form.confirm_password)
        if not ok:
            flash(t(message))
            return redirect(url_for('change_password'))
        session['must_change_password'] = False
        flash(t(message))
        return redirect(url_for('dashboard'))
    return render_template('change_password.html',
                           must_change=session.get('must_change_password'))


# ── Admin user management ────────────────────────────────────────────────────

def users_index():
    guard = auth_service.require_admin()
    if guard:
        return guard
    rows = auth_service.list_users()
    users_view = [{
        'username': u.username, 'full_name': u.full_name, 'role': u.role,
        'is_active': u.is_active, 'must_change_password': u.must_change_password,
        'created_at': u.created_at, 'last_login': u.last_login,
    } for u in rows]
    return render_template('users.html', users=users_view)


def users_add():
    guard = auth_service.require_admin()
    if guard:
        return guard
    form = UserCreateForm.from_form(request.form)
    ok, message = auth_service.create_user(form)
    flash(message)
    return redirect(url_for('users_index'))


def users_reset_password(username):
    guard = auth_service.require_admin()
    if guard:
        return guard
    ok, message = auth_service.reset_user_password(username)
    flash(message)
    return redirect(url_for('users_index'))


def users_deactivate(username):
    guard = auth_service.require_admin()
    if guard:
        return guard
    ok, message = auth_service.deactivate_user(username)
    flash(message)
    return redirect(url_for('users_index'))


def users_activate(username):
    guard = auth_service.require_admin()
    if guard:
        return guard
    ok, message = auth_service.activate_user(username)
    flash(message)
    return redirect(url_for('users_index'))


def users_change_role(username):
    guard = auth_service.require_admin()
    if guard:
        return guard
    new_role = request.form.get('role') or 'operator'
    ok, message = auth_service.change_user_role(username, new_role)
    flash(message)
    return redirect(url_for('users_index'))


def register(app):
    """Wire every route above onto `app` with its ORIGINAL endpoint name (the
    name every existing url_for(...) call site — 25 in app.py, 2 in templates
    — already expects). See this module's docstring for why a Blueprint isn't
    used here."""
    app.add_url_rule('/setup', 'setup', setup, methods=['GET', 'POST'])
    app.add_url_rule('/setup/demo', 'setup_demo', setup_demo, methods=['POST'])
    app.add_url_rule('/login', 'login', login, methods=['GET', 'POST'])
    app.add_url_rule('/logout', 'logout', logout, methods=['GET', 'POST'])
    app.add_url_rule('/change-password', 'change_password', change_password, methods=['GET', 'POST'])
    app.add_url_rule('/users', 'users_index', users_index)
    app.add_url_rule('/users/add', 'users_add', users_add, methods=['POST'])
    app.add_url_rule('/users/<username>/reset-password', 'users_reset_password',
                      users_reset_password, methods=['POST'])
    app.add_url_rule('/users/<username>/deactivate', 'users_deactivate',
                      users_deactivate, methods=['POST'])
    app.add_url_rule('/users/<username>/activate', 'users_activate',
                      users_activate, methods=['POST'])
    app.add_url_rule('/users/<username>/role', 'users_change_role',
                      users_change_role, methods=['POST'])
