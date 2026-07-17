"""Request shapes for the Auth & Setup domain. See schemas/__init__.py for why
these don't enforce business-rule validation themselves.
"""
from pydantic import BaseModel


def _s(form, key):
    return (form.get(key) or '').strip()


class SetupForm(BaseModel):
    company_name: str = ''
    gstin: str = ''
    pan: str = ''
    address: str = ''
    state_code: str = ''
    phone: str = ''
    username: str = ''
    password: str = ''
    confirm_password: str = ''

    @classmethod
    def from_form(cls, form):
        return cls(
            company_name=_s(form, 'company_name'),
            gstin=_s(form, 'gstin').upper(),
            pan=_s(form, 'pan').upper(),
            address=_s(form, 'address'),
            state_code=_s(form, 'state_code'),
            phone=_s(form, 'phone'),
            username=_s(form, 'username'),
            password=form.get('password') or '',            # not stripped — a
            confirm_password=form.get('confirm_password') or '',  # password may start/end with spaces
        )


class LoginForm(BaseModel):
    username: str = ''
    password: str = ''
    next: str = ''

    @classmethod
    def from_request(cls, form, args):
        return cls(
            username=_s(form, 'username'),
            password=form.get('password') or '',
            next=(args.get('next') or form.get('next') or ''),
        )


class ChangePasswordForm(BaseModel):
    old_password: str = ''
    new_password: str = ''
    confirm_password: str = ''

    @classmethod
    def from_form(cls, form):
        return cls(
            old_password=form.get('old_password') or '',
            new_password=form.get('new_password') or '',
            confirm_password=form.get('confirm_password') or '',
        )


class UserCreateForm(BaseModel):
    username: str = ''
    full_name: str = ''
    role: str = 'operator'

    @classmethod
    def from_form(cls, form):
        username = _s(form, 'username')
        full_name = _s(form, 'full_name') or username
        role = form.get('role') or 'operator'
        if role not in ('admin', 'operator'):
            role = 'operator'
        return cls(username=username, full_name=full_name, role=role)
