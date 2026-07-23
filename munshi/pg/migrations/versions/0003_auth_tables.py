"""non-tenant auth table (users)

Mirrors munshi/pg/auth_models.py. A deliberate exception to every other
table in this schema: no organization_id column, no RLS policy — this
single-business deployment keeps its existing homegrown username+password
login (not Supabase Auth), so there is no tenant to scope by. See
auth_models.py's module docstring for the full reasoning, including why
login-failure/lockout tracking reuses the EXISTING `login_failures` table
from 0001_baseline.py rather than getting a duplicate table here.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('username', sa.Text, primary_key=True),
        sa.Column('password_hash', sa.Text, nullable=False),
        sa.Column('full_name', sa.Text),
        sa.Column('role', sa.Text, nullable=False, server_default='operator'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('must_change_password', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.Text),
        sa.Column('last_login', sa.Text),
    )
    # No enable_rls() call — deliberate, see module docstring.


def downgrade():
    op.drop_table('users')
