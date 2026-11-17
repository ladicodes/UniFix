"""Discovery: campuses, service categories, files, professional profiles, verification, portfolio.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17 14:45:07.544664
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JOIN_TEXT_ARRAY = """
CREATE FUNCTION unifix_join_text_array(text[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT coalesce(array_to_string($1, ' '), '') $$;
"""


def upgrade() -> None:
    # array_to_string() is STABLE; the generated search column needs an IMMUTABLE expression.
    op.execute(JOIN_TEXT_ARRAY)
    op.create_table('campuses',
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('short_name', sa.String(length=32), nullable=False),
    sa.Column('city', sa.String(length=80), nullable=False),
    sa.Column('state', sa.String(length=80), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("country IN ('NG', 'GH')", name=op.f('ck_campuses_country_valid')),
    sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f('ck_campuses_slug_format')),
    sa.CheckConstraint('latitude IS NULL OR latitude BETWEEN -90 AND 90', name=op.f('ck_campuses_latitude_range')),
    sa.CheckConstraint('longitude IS NULL OR longitude BETWEEN -180 AND 180', name=op.f('ck_campuses_longitude_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_campuses')),
    sa.UniqueConstraint('slug', name=op.f('uq_campuses_slug'))
    )
    op.create_table('files',
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('storage_key', sa.String(length=128), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("purpose IN ('AVATAR', 'PORTFOLIO', 'VERIFICATION_DOCUMENT', 'REQUEST_MEDIA', 'MESSAGE_ATTACHMENT', 'COMPLETION_EVIDENCE', 'DISPUTE_EVIDENCE')", name=op.f('ck_files_purpose_valid')),
    sa.CheckConstraint("visibility IN ('PUBLIC', 'PRIVATE')", name=op.f('ck_files_visibility_valid')),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_files_size_positive')),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_files_owner_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_files')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_files_storage_key'))
    )
    op.create_index('ix_files_owner_purpose', 'files', ['owner_user_id', 'purpose'], unique=False)
    op.create_table('service_categories',
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f('ck_service_categories_slug_format')),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name=op.f('ck_service_categories_not_own_parent')),
    sa.ForeignKeyConstraint(['parent_id'], ['service_categories.id'], name=op.f('fk_service_categories_parent_id_service_categories'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_categories')),
    sa.UniqueConstraint('slug', name=op.f('uq_service_categories_slug'))
    )
    op.create_table('professional_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('primary_category_id', sa.Uuid(), nullable=False),
    sa.Column('headline', sa.String(length=120), nullable=False),
    sa.Column('bio', sa.Text(), server_default='', nullable=False),
    sa.Column('city', sa.String(length=80), nullable=False),
    sa.Column('area', sa.String(length=120), server_default='', nullable=False),
    sa.Column('country', sa.String(length=2), nullable=False),
    sa.Column('latitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('longitude', sa.Numeric(precision=9, scale=6), nullable=True),
    sa.Column('years_experience', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('availability', sa.String(length=16), nullable=False),
    sa.Column('starting_price_minor', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('skills', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('languages', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('coverage', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('is_listed', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('verification_status', sa.String(length=16), server_default='NOT_SUBMITTED', nullable=False),
    sa.Column('rating_avg', sa.Numeric(precision=3, scale=2), server_default='0', nullable=False),
    sa.Column('rating_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('rating_quality', sa.Numeric(precision=3, scale=2), server_default='0', nullable=False),
    sa.Column('rating_punctuality', sa.Numeric(precision=3, scale=2), server_default='0', nullable=False),
    sa.Column('rating_communication', sa.Numeric(precision=3, scale=2), server_default='0', nullable=False),
    sa.Column('rating_professionalism', sa.Numeric(precision=3, scale=2), server_default='0', nullable=False),
    sa.Column('rating_value', sa.Numeric(precision=3, scale=2), server_default='0', nullable=False),
    sa.Column('completed_jobs', sa.Integer(), server_default='0', nullable=False),
    sa.Column('response_minutes', sa.Integer(), nullable=True),
    sa.Column('search_vector', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', coalesce(headline, '') || ' ' || coalesce(bio, '') || ' ' || coalesce(area, '') || ' ' || coalesce(city, '') || ' ' || unifix_join_text_array(skills))", persisted=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("availability IN ('NOW', 'TODAY', 'THIS_WEEK', 'UNAVAILABLE')", name=op.f('ck_professional_profiles_availability_valid')),
    sa.CheckConstraint("country IN ('NG', 'GH')", name=op.f('ck_professional_profiles_country_valid')),
    sa.CheckConstraint("currency IN ('NGN', 'GHS')", name=op.f('ck_professional_profiles_currency_valid')),
    sa.CheckConstraint("verification_status IN ('NOT_SUBMITTED', 'PENDING', 'VERIFIED', 'REJECTED')", name=op.f('ck_professional_profiles_verification_status_valid')),
    sa.CheckConstraint('(latitude IS NULL) = (longitude IS NULL)', name=op.f('ck_professional_profiles_coordinates_paired')),
    sa.CheckConstraint('rating_avg BETWEEN 0 AND 5', name=op.f('ck_professional_profiles_rating_avg_range')),
    sa.CheckConstraint('rating_count >= 0 AND completed_jobs >= 0', name=op.f('ck_professional_profiles_counters_non_negative')),
    sa.CheckConstraint('starting_price_minor >= 0', name=op.f('ck_professional_profiles_starting_price_non_negative')),
    sa.CheckConstraint('years_experience BETWEEN 0 AND 60', name=op.f('ck_professional_profiles_years_experience_range')),
    sa.ForeignKeyConstraint(['primary_category_id'], ['service_categories.id'], name=op.f('fk_professional_profiles_primary_category_id_service_categories'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_professional_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_professional_profiles')),
    sa.UniqueConstraint('user_id', name=op.f('uq_professional_profiles_user_id'))
    )
    op.create_index('ix_professional_profiles_completed_jobs', 'professional_profiles', ['completed_jobs'], unique=False)
    op.create_index('ix_professional_profiles_primary_category_listed', 'professional_profiles', ['primary_category_id', 'is_listed'], unique=False)
    op.create_index('ix_professional_profiles_rating_avg', 'professional_profiles', ['rating_avg'], unique=False)
    op.create_index('ix_professional_profiles_search_vector', 'professional_profiles', ['search_vector'], unique=False, postgresql_using='gin')
    op.create_table('portfolio_items',
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('caption', sa.String(length=500), server_default='', nullable=False),
    sa.Column('category_id', sa.Uuid(), nullable=True),
    sa.Column('image_file_id', sa.Uuid(), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['service_categories.id'], name=op.f('fk_portfolio_items_category_id_service_categories'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['image_file_id'], ['files.id'], name=op.f('fk_portfolio_items_image_file_id_files'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_portfolio_items_professional_id_professional_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_portfolio_items'))
    )
    op.create_index('ix_portfolio_items_professional_sort', 'portfolio_items', ['professional_id', 'sort_order'], unique=False)
    op.create_table('professional_campuses',
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('campus_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['campus_id'], ['campuses.id'], name=op.f('fk_professional_campuses_campus_id_campuses'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_professional_campuses_professional_id_professional_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('professional_id', 'campus_id', name=op.f('pk_professional_campuses'))
    )
    op.create_index('ix_professional_campuses_campus_id', 'professional_campuses', ['campus_id'], unique=False)
    op.create_table('professional_categories',
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('category_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['service_categories.id'], name=op.f('fk_professional_categories_category_id_service_categories'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_professional_categories_professional_id_professional_profiles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('professional_id', 'category_id', name=op.f('pk_professional_categories'))
    )
    op.create_index('ix_professional_categories_category_id', 'professional_categories', ['category_id'], unique=False)
    op.create_table('professional_verifications',
    sa.Column('professional_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('file_ids', postgresql.ARRAY(sa.Uuid()), server_default='{}', nullable=False),
    sa.Column('note', sa.String(length=1000), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'VERIFIED', 'REJECTED')", name=op.f('ck_professional_verifications_status_valid')),
    sa.CheckConstraint("type IN ('IDENTITY', 'TRADE', 'PHONE')", name=op.f('ck_professional_verifications_type_valid')),
    sa.ForeignKeyConstraint(['professional_id'], ['professional_profiles.id'], name=op.f('fk_professional_verifications_professional_id_professional_profiles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_professional_verifications_reviewed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_professional_verifications'))
    )
    op.create_index('ix_professional_verifications_status', 'professional_verifications', ['status', 'submitted_at'], unique=False)
    op.create_index('uq_professional_verifications_professional_type', 'professional_verifications', ['professional_id', 'type'], unique=True)
    op.add_column('users', sa.Column('campus_id', sa.Uuid(), nullable=True))
    op.add_column('users', sa.Column('avatar_file_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_users_campus_id'), 'users', ['campus_id'], unique=False)
    op.create_foreign_key(op.f('fk_users_campus_id_campuses'), 'users', 'campuses', ['campus_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_users_avatar_file_id_files'), 'users', 'files', ['avatar_file_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_users_avatar_file_id_files'), 'users', type_='foreignkey')
    op.drop_constraint(op.f('fk_users_campus_id_campuses'), 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_campus_id'), table_name='users')
    op.drop_column('users', 'avatar_file_id')
    op.drop_column('users', 'campus_id')
    op.drop_index('uq_professional_verifications_professional_type', table_name='professional_verifications')
    op.drop_index('ix_professional_verifications_status', table_name='professional_verifications')
    op.drop_table('professional_verifications')
    op.drop_index('ix_professional_categories_category_id', table_name='professional_categories')
    op.drop_table('professional_categories')
    op.drop_index('ix_professional_campuses_campus_id', table_name='professional_campuses')
    op.drop_table('professional_campuses')
    op.drop_index('ix_portfolio_items_professional_sort', table_name='portfolio_items')
    op.drop_table('portfolio_items')
    op.drop_index('ix_professional_profiles_search_vector', table_name='professional_profiles', postgresql_using='gin')
    op.drop_index('ix_professional_profiles_rating_avg', table_name='professional_profiles')
    op.drop_index('ix_professional_profiles_primary_category_listed', table_name='professional_profiles')
    op.drop_index('ix_professional_profiles_completed_jobs', table_name='professional_profiles')
    op.drop_table('professional_profiles')
    op.drop_table('service_categories')
    op.drop_index('ix_files_owner_purpose', table_name='files')
    op.drop_table('files')
    op.drop_table('campuses')
    op.execute("DROP FUNCTION IF EXISTS unifix_join_text_array(text[])")
