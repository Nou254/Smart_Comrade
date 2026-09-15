"""Add user_type, verification, sessions tables

Revision ID: 809838633a0d
Revises: 6f8846b74544
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '809838633a0d'
down_revision: Union[str, None] = '6f8846b74544'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # New tables
    # ------------------------------------------------------------------
    op.create_table(
        'email_verifications',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('otp_hash', sa.String(length=255), nullable=False),
        sa.Column('purpose', sa.String(length=30), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_verifications_email', 'email_verifications', ['email'])
    op.create_index('ix_email_verifications_id', 'email_verifications', ['id'], unique=True)
    op.create_index('ix_email_verifications_user_id', 'email_verifications', ['user_id'])

    op.create_table(
        'password_resets',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('requested_ip', sa.String(length=45), nullable=True),
        sa.Column('used_ip', sa.String(length=45), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_password_resets_id', 'password_resets', ['id'], unique=True)
    op.create_index('ix_password_resets_token_hash', 'password_resets', ['token_hash'])
    op.create_index('ix_password_resets_user_id', 'password_resets', ['user_id'])

    op.create_table(
        'sessions',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('device_label', sa.String(length=100), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sessions_id', 'sessions', ['id'], unique=True)
    op.create_index('ix_sessions_token_hash', 'sessions', ['token_hash'])
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])

    # ------------------------------------------------------------------
    # New columns on users
    # ------------------------------------------------------------------
    # NOT NULL columns get a server_default so existing rows can be filled.
    op.add_column(
        'users',
        sa.Column('user_type', sa.String(length=20), nullable=False, server_default='student'),
    )
    op.add_column('users', sa.Column('external_subtype', sa.String(length=30), nullable=True))
    op.add_column('users', sa.Column('institution_id', sa.String(length=36), nullable=True))
    op.add_column('users', sa.Column('institutional_email', sa.String(length=255), nullable=True))
    op.add_column(
        'users',
        sa.Column('domain_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('users', sa.Column('department', sa.String(length=150), nullable=True))
    op.add_column('users', sa.Column('title', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('approved_by', sa.String(length=36), nullable=True))
    op.add_column('users', sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('rejection_reason', sa.String(length=500), nullable=True))
    op.add_column(
        'users',
        sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))

    # ------------------------------------------------------------------
    # Indexes and foreign keys
    # ------------------------------------------------------------------
    op.create_index('ix_users_account_status', 'users', ['account_status'])
    op.create_index('ix_users_institution_id', 'users', ['institution_id'])
    op.create_index('ix_users_user_type', 'users', ['user_type'])
    op.create_foreign_key(
        'fk_users_institution_id', 'users', 'institutions',
        ['institution_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_users_approved_by', 'users', 'users',
        ['approved_by'], ['id'], ondelete='SET NULL',
    )

    # ------------------------------------------------------------------
    # Drop server defaults now that existing rows are populated
    # ------------------------------------------------------------------
    op.alter_column('users', 'user_type', server_default=None)
    op.alter_column('users', 'domain_verified', server_default=None)
    op.alter_column('users', 'failed_login_attempts', server_default=None)
    op.alter_column('email_verifications', 'attempts', server_default=None)
    op.alter_column('email_verifications', 'max_attempts', server_default=None)
    op.alter_column('email_verifications', 'is_used', server_default=None)
    op.alter_column('password_resets', 'is_used', server_default=None)
    op.alter_column('sessions', 'is_revoked', server_default=None)


def downgrade() -> None:
    # Drop FKs and indexes on users
    op.drop_constraint('fk_users_approved_by', 'users', type_='foreignkey')
    op.drop_constraint('fk_users_institution_id', 'users', type_='foreignkey')
    op.drop_index('ix_users_user_type', table_name='users')
    op.drop_index('ix_users_institution_id', table_name='users')
    op.drop_index('ix_users_account_status', table_name='users')

    # Drop columns from users
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'rejection_reason')
    op.drop_column('users', 'approved_at')
    op.drop_column('users', 'approved_by')
    op.drop_column('users', 'title')
    op.drop_column('users', 'department')
    op.drop_column('users', 'domain_verified')
    op.drop_column('users', 'institutional_email')
    op.drop_column('users', 'institution_id')
    op.drop_column('users', 'external_subtype')
    op.drop_column('users', 'user_type')

    # Drop new tables
    op.drop_table('sessions')
    op.drop_table('password_resets')
    op.drop_table('email_verifications')