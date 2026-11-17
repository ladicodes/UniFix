"""Real-time communication: conversations, members, messages, reports, WebSocket tickets, call sessions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17 14:56:18.452955
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('conversations',
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_message_preview', sa.String(length=140), server_default='', nullable=False),
    sa.Column('first_response_seconds', sa.Integer(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], name=op.f('fk_conversations_customer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_conversations_professional_id_professional_profiles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversations'))
    )
    op.create_index('ix_conversations_customer_last', 'conversations', ['customer_id', 'last_message_at'], unique=False)
    op.create_index('ix_conversations_professional_last', 'conversations', ['professional_id', 'last_message_at'], unique=False)
    op.create_index('uq_conversations_direct', 'conversations', ['customer_id', 'professional_id'], unique=True)
    op.create_table('call_sessions',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('initiator_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_reason', sa.String(length=64), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('RINGING', 'ACTIVE', 'ENDED', 'MISSED', 'DECLINED')", name=op.f('ck_call_sessions_status_valid')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_call_sessions_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['initiator_id'], ['users.id'], name=op.f('fk_call_sessions_initiator_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_call_sessions'))
    )
    op.create_index('uq_call_sessions_live_per_conversation', 'call_sessions', ['conversation_id'], unique=True, postgresql_where=sa.text("status IN ('RINGING', 'ACTIVE')"))
    op.create_table('conversation_members',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('last_read_seq', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('last_read_message_id', sa.Uuid(), nullable=True),
    sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('CUSTOMER', 'PROFESSIONAL')", name=op.f('ck_conversation_members_role_valid')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_conversation_members_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_conversation_members_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('conversation_id', 'user_id', name=op.f('pk_conversation_members'))
    )
    op.create_index('ix_conversation_members_user_id', 'conversation_members', ['user_id'], unique=False)
    op.create_table('messages',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('sender_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('body', sa.Text(), server_default='', nullable=False),
    sa.Column('attachment_file_id', sa.Uuid(), nullable=True),
    sa.Column('client_message_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind <> 'IMAGE' OR attachment_file_id IS NOT NULL", name=op.f('ck_messages_image_has_attachment')),
    sa.CheckConstraint("kind <> 'SYSTEM' OR sender_id IS NULL", name=op.f('ck_messages_system_has_no_sender')),
    sa.CheckConstraint("kind IN ('TEXT', 'IMAGE', 'QUOTE', 'SYSTEM')", name=op.f('ck_messages_kind_valid')),
    sa.CheckConstraint('char_length(body) <= 4000', name=op.f('ck_messages_body_length')),
    sa.ForeignKeyConstraint(['attachment_file_id'], ['files.id'], name=op.f('fk_messages_attachment_file_id_files'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_messages_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], name=op.f('fk_messages_sender_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages')),
    sa.UniqueConstraint('seq', name=op.f('uq_messages_seq'))
    )
    op.create_index('ix_messages_attachment_file_id', 'messages', ['attachment_file_id'], unique=False)
    op.create_index('ix_messages_conversation_seq', 'messages', ['conversation_id', 'seq'], unique=False)
    op.create_index('uq_messages_sender_client_id', 'messages', ['sender_id', 'client_message_id'], unique=True, postgresql_where=sa.text('client_message_id IS NOT NULL'))
    op.create_table('reports',
    sa.Column('reporter_id', sa.Uuid(), nullable=False),
    sa.Column('target_type', sa.String(length=16), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=64), nullable=False),
    sa.Column('details', sa.String(length=2000), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='OPEN', nullable=False),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('OPEN', 'DISMISSED', 'ACTIONED')", name=op.f('ck_reports_status_valid')),
    sa.CheckConstraint("target_type IN ('MESSAGE', 'CONVERSATION', 'USER', 'REVIEW')", name=op.f('ck_reports_target_type_valid')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_reports_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], name=op.f('fk_reports_reporter_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_reports_resolved_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports'))
    )
    op.create_index('ix_reports_status_created', 'reports', ['status', 'created_at'], unique=False)
    op.create_index('uq_reports_reporter_target', 'reports', ['reporter_id', 'target_type', 'target_id'], unique=True)
    op.create_table('ws_tickets',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("scope <> 'CONVERSATION' OR conversation_id IS NOT NULL", name=op.f('ck_ws_tickets_conversation_scoped')),
    sa.CheckConstraint("scope IN ('CONVERSATION')", name=op.f('ck_ws_tickets_scope_valid')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_ws_tickets_conversation_id_conversations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['family_id'], ['auth_session_families.id'], name=op.f('fk_ws_tickets_family_id_auth_session_families'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ws_tickets_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ws_tickets')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_ws_tickets_token_hash'))
    )
    op.create_index('ix_ws_tickets_expires_at', 'ws_tickets', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ws_tickets_expires_at', table_name='ws_tickets')
    op.drop_table('ws_tickets')
    op.drop_index('uq_reports_reporter_target', table_name='reports')
    op.drop_index('ix_reports_status_created', table_name='reports')
    op.drop_table('reports')
    op.drop_index('uq_messages_sender_client_id', table_name='messages', postgresql_where=sa.text('client_message_id IS NOT NULL'))
    op.drop_index('ix_messages_conversation_seq', table_name='messages')
    op.drop_index('ix_messages_attachment_file_id', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_conversation_members_user_id', table_name='conversation_members')
    op.drop_table('conversation_members')
    op.drop_index('uq_call_sessions_live_per_conversation', table_name='call_sessions', postgresql_where=sa.text("status IN ('RINGING', 'ACTIVE')"))
    op.drop_table('call_sessions')
    op.drop_index('uq_conversations_direct', table_name='conversations')
    op.drop_index('ix_conversations_professional_last', table_name='conversations')
    op.drop_index('ix_conversations_customer_last', table_name='conversations')
    op.drop_table('conversations')
