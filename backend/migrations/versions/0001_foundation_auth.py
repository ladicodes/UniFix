"""Foundation: users, sessions, refresh tokens, user tokens, audit log, rate limits.

Revision ID: 0001
Revises:
Create Date: 2026-11-17 13:28:32.902094
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPEND_ONLY_FUNCTION = """
CREATE FUNCTION unifix_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only (% blocked)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END
$$;
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute(APPEND_ONLY_FUNCTION)
    op.create_table('rate_limit_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('bucket', sa.String(length=64), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rate_limit_events'))
    )
    op.create_index('ix_rate_limit_events_bucket_key_at', 'rate_limit_events', ['bucket', 'key', 'at'], unique=False)
    op.create_table('users',
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('phone', sa.String(length=16), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='ACTIVE', nullable=False),
    sa.Column('city', sa.String(length=80), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("country IN ('NG', 'GH')", name=op.f('ck_users_country_valid')),
    sa.CheckConstraint("role IN ('CUSTOMER', 'PROFESSIONAL', 'ADMIN')", name=op.f('ck_users_role_valid')),
    sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED', 'DEACTIVATED')", name=op.f('ck_users_status_valid')),
    sa.CheckConstraint('char_length(full_name) BETWEEN 2 AND 120', name=op.f('ck_users_full_name_length')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_index('ix_users_role_status', 'users', ['role', 'status'], unique=False)
    op.create_index('uq_users_phone', 'users', ['phone'], unique=True, postgresql_where=sa.text('phone IS NOT NULL'))
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.Uuid(), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_logs_actor_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action', 'occurred_at'], unique=False)
    op.create_index('ix_audit_logs_actor', 'audit_logs', ['actor_user_id', 'occurred_at'], unique=False)
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id', 'occurred_at'], unique=False)
    op.create_table('auth_session_families',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=32), nullable=True),
    sa.Column('user_agent', sa.String(length=512), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("revoked_reason IS NULL OR revoked_reason IN ('LOGOUT', 'LOGOUT_ALL', 'SESSION_REVOKED', 'REFRESH_REUSE', 'PASSWORD_CHANGED', 'PASSWORD_RESET', 'ACCOUNT_STATUS')", name=op.f('ck_auth_session_families_revoked_reason_valid')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_session_families_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_session_families'))
    )
    op.create_index('ix_auth_session_families_user_active', 'auth_session_families', ['user_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('user_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("purpose IN ('VERIFY_EMAIL', 'RESET_PASSWORD')", name=op.f('ck_user_tokens_purpose_valid')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_user_tokens_token_hash'))
    )
    op.create_index('ix_user_tokens_user_purpose', 'user_tokens', ['user_id', 'purpose'], unique=False)
    op.create_table('auth_refresh_tokens',
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('successor_id', sa.Uuid(), nullable=True),
    sa.Column('idle_expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['family_id'], ['auth_session_families.id'], name=op.f('fk_auth_refresh_tokens_family_id_auth_session_families'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['auth_refresh_tokens.id'], name=op.f('fk_auth_refresh_tokens_parent_id_auth_refresh_tokens'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['successor_id'], ['auth_refresh_tokens.id'], name=op.f('fk_auth_refresh_tokens_successor_id_auth_refresh_tokens'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_refresh_tokens_token_hash'))
    )
    op.create_index('ix_auth_refresh_tokens_family_id', 'auth_refresh_tokens', ['family_id'], unique=False)
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION unifix_forbid_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.drop_index('ix_auth_refresh_tokens_family_id', table_name='auth_refresh_tokens')
    op.drop_table('auth_refresh_tokens')
    op.drop_index('ix_user_tokens_user_purpose', table_name='user_tokens')
    op.drop_table('user_tokens')
    op.drop_index('ix_auth_session_families_user_active', table_name='auth_session_families', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_table('auth_session_families')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('uq_users_phone', table_name='users', postgresql_where=sa.text('phone IS NOT NULL'))
    op.drop_index('ix_users_role_status', table_name='users')
    op.drop_table('users')
    op.drop_index('ix_rate_limit_events_bucket_key_at', table_name='rate_limit_events')
    op.drop_table('rate_limit_events')
    op.execute("DROP FUNCTION IF EXISTS unifix_forbid_mutation()")
    op.execute("DROP EXTENSION IF EXISTS citext")
