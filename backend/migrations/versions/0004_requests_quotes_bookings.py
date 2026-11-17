"""Requests, quotes, immutable agreements, bookings, booking timeline, idempotency keys.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17 15:08:10.062332
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


QUOTE_IMMUTABILITY = """
CREATE FUNCTION unifix_quotes_terms_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'quotes are never deleted' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status <> 'PENDING' THEN
        RAISE EXCEPTION 'quote % is %, its row can no longer change', OLD.id, OLD.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (OLD.conversation_id, OLD.service_request_id, OLD.professional_id, OLD.customer_id, OLD.version, OLD.title, OLD.description, OLD.labour_minor, OLD.materials_minor, OLD.total_minor, OLD.currency, OLD.completion_date, OLD.payment_terms, OLD.service_method, OLD.milestones, OLD.valid_until, OLD.created_at) IS DISTINCT FROM (NEW.conversation_id, NEW.service_request_id, NEW.professional_id, NEW.customer_id, NEW.version, NEW.title, NEW.description, NEW.labour_minor, NEW.materials_minor, NEW.total_minor, NEW.currency, NEW.completion_date, NEW.payment_terms, NEW.service_method, NEW.milestones, NEW.valid_until, NEW.created_at) THEN
        RAISE EXCEPTION 'quote terms are immutable; send a new version instead'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;
"""


def upgrade() -> None:
    op.execute(QUOTE_IMMUTABILITY)
    op.create_table('idempotency_keys',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('method', sa.String(length=8), nullable=False),
    sa.Column('path', sa.String(length=300), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('IN_PROGRESS', 'COMPLETED')", name=op.f('ck_idempotency_keys_status_valid')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_idempotency_keys_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_keys'))
    )
    op.create_index('ix_idempotency_keys_expires_at', 'idempotency_keys', ['expires_at'], unique=False)
    op.create_index('uq_idempotency_keys_user_key', 'idempotency_keys', ['user_id', 'key'], unique=True)
    op.create_table('service_requests',
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('category_id', sa.Uuid(), nullable=False),
    sa.Column('campus_id', sa.Uuid(), nullable=True),
    sa.Column('target_professional_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('item', sa.String(length=120), nullable=True),
    sa.Column('location_text', sa.String(length=300), nullable=True),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('preferred_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('preferred_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='OPEN', nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('OPEN', 'BOOKED', 'CANCELLED', 'EXPIRED')", name=op.f('ck_service_requests_status_valid')),
    sa.CheckConstraint('(latitude IS NULL) = (longitude IS NULL)', name=op.f('ck_service_requests_coordinates_paired')),
    sa.CheckConstraint('preferred_end IS NULL OR preferred_start IS NULL OR preferred_end >= preferred_start', name=op.f('ck_service_requests_window_order')),
    sa.ForeignKeyConstraint(['campus_id'], ['campuses.id'], name=op.f('fk_service_requests_campus_id_campuses'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['category_id'], ['service_categories.id'], name=op.f('fk_service_requests_category_id_service_categories'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], name=op.f('fk_service_requests_customer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['target_professional_id'], ['professional_profiles.id'], name=op.f('fk_service_requests_target_professional_id_professional_profiles'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_requests'))
    )
    op.create_index('ix_service_requests_customer', 'service_requests', ['customer_id', 'created_at'], unique=False)
    op.create_index('ix_service_requests_feed', 'service_requests', ['status', 'category_id', 'campus_id', 'created_at'], unique=False)
    op.create_table('service_request_media',
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('file_id', sa.Uuid(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['file_id'], ['files.id'], name=op.f('fk_service_request_media_file_id_files'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['request_id'], ['service_requests.id'], name=op.f('fk_service_request_media_request_id_service_requests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('request_id', 'file_id', name=op.f('pk_service_request_media'))
    )
    op.create_index('ix_service_request_media_file_id', 'service_request_media', ['file_id'], unique=False)
    op.create_table('quotes',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('service_request_id', sa.Uuid(), nullable=True),
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('labour_minor', sa.BigInteger(), nullable=False),
    sa.Column('materials_minor', sa.BigInteger(), nullable=False),
    sa.Column('total_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('completion_date', sa.Date(), nullable=False),
    sa.Column('payment_terms', sa.String(length=500), server_default='', nullable=False),
    sa.Column('service_method', sa.String(length=24), nullable=False),
    sa.Column('milestones', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency IN ('NGN', 'GHS')", name=op.f('ck_quotes_currency_valid')),
    sa.CheckConstraint("service_method IN ('CUSTOMER_TO_PRO', 'PRO_TO_CUSTOMER', 'EITHER', 'REMOTE')", name=op.f('ck_quotes_service_method_valid')),
    sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'SUPERSEDED', 'WITHDRAWN')", name=op.f('ck_quotes_status_valid')),
    sa.CheckConstraint('labour_minor >= 0 AND materials_minor >= 0', name=op.f('ck_quotes_amounts_non_negative')),
    sa.CheckConstraint('total_minor = labour_minor + materials_minor', name=op.f('ck_quotes_total_is_sum')),
    sa.CheckConstraint('total_minor > 0', name=op.f('ck_quotes_total_positive')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_quotes_conversation_id_conversations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], name=op.f('fk_quotes_customer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_quotes_professional_id_professional_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id'], name=op.f('fk_quotes_service_request_id_service_requests'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quotes'))
    )
    op.create_index('ix_quotes_service_request', 'quotes', ['service_request_id', 'status'], unique=False)
    op.create_index('uq_quotes_conversation_version', 'quotes', ['conversation_id', 'version'], unique=True)
    op.create_index('uq_quotes_one_pending_per_conversation', 'quotes', ['conversation_id'], unique=True, postgresql_where=sa.text("status = 'PENDING'"))
    op.create_table('agreements',
    sa.Column('booking_id', sa.Uuid(), nullable=False),
    sa.Column('quote_id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('canonical_json', sa.Text(), nullable=False),
    sa.Column('agreement_hash', sa.String(length=64), nullable=False),
    sa.Column('total_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('accepted_by', sa.Uuid(), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("agreement_hash = encode(sha256(convert_to(canonical_json, 'UTF8')), 'hex')", name=op.f('ck_agreements_hash_matches_document')),
    sa.ForeignKeyConstraint(['accepted_by'], ['users.id'], name=op.f('fk_agreements_accepted_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], name=op.f('fk_agreements_customer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_agreements_professional_id_professional_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['quote_id'], ['quotes.id'], name=op.f('fk_agreements_quote_id_quotes'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agreements')),
    sa.UniqueConstraint('agreement_hash', name=op.f('uq_agreements_agreement_hash')),
    sa.UniqueConstraint('booking_id', name=op.f('uq_agreements_booking_id')),
    sa.UniqueConstraint('quote_id', name=op.f('uq_agreements_quote_id'))
    )
    op.create_table('bookings',
    sa.Column('agreement_id', sa.Uuid(), nullable=False),
    sa.Column('quote_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('service_request_id', sa.Uuid(), nullable=True),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('service_address', sa.String(length=300), nullable=True),
    sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('payment_due_by', sa.DateTime(timezone=True), nullable=False),
    sa.Column('funded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completion_submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_by', sa.Uuid(), nullable=True),
    sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency IN ('NGN', 'GHS')", name=op.f('ck_bookings_currency_valid')),
    sa.CheckConstraint("status IN ('PENDING_PAYMENT', 'FUNDED', 'IN_PROGRESS', 'COMPLETION_SUBMITTED', 'COMPLETED', 'DISPUTED', 'CANCELLED', 'REFUNDED', 'RESOLVED')", name=op.f('ck_bookings_status_valid')),
    sa.CheckConstraint('amount_minor > 0', name=op.f('ck_bookings_amount_positive')),
    sa.ForeignKeyConstraint(['agreement_id'], ['agreements.id'], name=op.f('fk_bookings_agreement_id_agreements'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cancelled_by'], ['users.id'], name=op.f('fk_bookings_cancelled_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_bookings_conversation_id_conversations'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], name=op.f('fk_bookings_customer_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_bookings_professional_id_professional_profiles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['quote_id'], ['quotes.id'], name=op.f('fk_bookings_quote_id_quotes'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['service_request_id'], ['service_requests.id'], name=op.f('fk_bookings_service_request_id_service_requests'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings')),
    sa.UniqueConstraint('agreement_id', name=op.f('uq_bookings_agreement_id')),
    sa.UniqueConstraint('quote_id', name=op.f('uq_bookings_quote_id'))
    )
    op.create_index('ix_bookings_customer_status', 'bookings', ['customer_id', 'status'], unique=False)
    op.create_index('ix_bookings_professional_status', 'bookings', ['professional_id', 'status'], unique=False)
    op.create_index('uq_bookings_active_per_conversation', 'bookings', ['conversation_id'], unique=True, postgresql_where=sa.text("status IN ('PENDING_PAYMENT', 'FUNDED', 'IN_PROGRESS', 'COMPLETION_SUBMITTED', 'DISPUTED')"))
    op.create_index('uq_bookings_per_service_request', 'bookings', ['service_request_id'], unique=True, postgresql_where=sa.text("service_request_id IS NOT NULL AND status <> 'CANCELLED'"))
    op.create_table('booking_events',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('booking_id', sa.Uuid(), nullable=False),
    sa.Column('from_status', sa.String(length=24), nullable=True),
    sa.Column('to_status', sa.String(length=24), nullable=True),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type IN ('CUSTOMER', 'PROFESSIONAL', 'SYSTEM', 'CHAIN', 'ADMIN')", name=op.f('ck_booking_events_actor_type_valid')),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_booking_events_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name=op.f('fk_booking_events_booking_id_bookings'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_booking_events')),
    sa.UniqueConstraint('seq', name=op.f('uq_booking_events_seq'))
    )
    op.create_index('ix_booking_events_booking_seq', 'booking_events', ['booking_id', 'seq'], unique=False)
    op.add_column('conversations', sa.Column('service_request_id', sa.Uuid(), nullable=True))
    op.create_index('uq_conversations_request_professional', 'conversations', ['service_request_id', 'professional_id'], unique=True, postgresql_where=sa.text('service_request_id IS NOT NULL'))
    op.create_foreign_key(op.f('fk_conversations_service_request_id_service_requests'), 'conversations', 'service_requests', ['service_request_id'], ['id'], ondelete='RESTRICT')
    op.add_column('messages', sa.Column('quote_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_messages_quote_id_quotes'), 'messages', 'quotes', ['quote_id'], ['id'], ondelete='RESTRICT')

    op.execute(
        "CREATE TRIGGER quotes_terms_immutable BEFORE UPDATE OR DELETE ON quotes "
        "FOR EACH ROW EXECUTE FUNCTION unifix_quotes_terms_immutable()"
    )
    for table in ("agreements", "booking_events"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION unifix_forbid_mutation()"
        )
    # A direct thread is unique per (customer, professional) only when not tied to a request.
    op.drop_index("uq_conversations_direct", table_name="conversations")
    op.create_index(
        "uq_conversations_direct", "conversations", ["customer_id", "professional_id"], unique=True,
        postgresql_where=sa.text("service_request_id IS NULL"),
    )
    op.create_check_constraint("quote_message_has_quote", "messages", "kind <> 'QUOTE' OR quote_id IS NOT NULL")


def downgrade() -> None:
    op.drop_constraint("quote_message_has_quote", "messages", type_="check")
    op.drop_index("uq_conversations_direct", table_name="conversations")
    op.create_index("uq_conversations_direct", "conversations", ["customer_id", "professional_id"], unique=True)
    for table in ("agreements", "booking_events"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP TRIGGER IF EXISTS quotes_terms_immutable ON quotes")
    op.drop_constraint(op.f('fk_messages_quote_id_quotes'), 'messages', type_='foreignkey')
    op.drop_column('messages', 'quote_id')
    op.drop_constraint(op.f('fk_conversations_service_request_id_service_requests'), 'conversations', type_='foreignkey')
    op.drop_index('uq_conversations_request_professional', table_name='conversations', postgresql_where=sa.text('service_request_id IS NOT NULL'))
    op.drop_column('conversations', 'service_request_id')
    op.drop_index('ix_booking_events_booking_seq', table_name='booking_events')
    op.drop_table('booking_events')
    op.drop_index('uq_bookings_per_service_request', table_name='bookings', postgresql_where=sa.text("service_request_id IS NOT NULL AND status <> 'CANCELLED'"))
    op.drop_index('uq_bookings_active_per_conversation', table_name='bookings', postgresql_where=sa.text("status IN ('PENDING_PAYMENT', 'FUNDED', 'IN_PROGRESS', 'COMPLETION_SUBMITTED', 'DISPUTED')"))
    op.drop_index('ix_bookings_professional_status', table_name='bookings')
    op.drop_index('ix_bookings_customer_status', table_name='bookings')
    op.drop_table('bookings')
    op.drop_table('agreements')
    op.drop_index('uq_quotes_one_pending_per_conversation', table_name='quotes', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_index('uq_quotes_conversation_version', table_name='quotes')
    op.drop_index('ix_quotes_service_request', table_name='quotes')
    op.drop_table('quotes')
    op.drop_index('ix_service_request_media_file_id', table_name='service_request_media')
    op.drop_table('service_request_media')
    op.drop_index('ix_service_requests_feed', table_name='service_requests')
    op.drop_index('ix_service_requests_customer', table_name='service_requests')
    op.drop_table('service_requests')
    op.drop_index('uq_idempotency_keys_user_key', table_name='idempotency_keys')
    op.drop_index('ix_idempotency_keys_expires_at', table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
    op.execute("DROP FUNCTION IF EXISTS unifix_quotes_terms_immutable()")
