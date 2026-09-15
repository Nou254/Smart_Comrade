"""upload pipeline: timetable_uploads, upload_files, upload_scanned_pages, extracted_units

Revision ID: 0003_upload_pipeline
Revises: e1a6574a87d8
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_upload_pipeline"
down_revision = "e1a6574a87d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # timetable_uploads
    # ------------------------------------------------------------------
    op.create_table(
        "timetable_uploads",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("scan_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"],
                                name="fk_timetable_uploads_group_id_groups",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"],
                                name="fk_timetable_uploads_uploaded_by_users",
                                ondelete="SET NULL"),
    )
    op.create_index("ix_timetable_uploads_group_id", "timetable_uploads", ["group_id"])
    op.create_index("ix_timetable_uploads_uploaded_by", "timetable_uploads", ["uploaded_by"])
    op.create_index("ix_timetable_uploads_status", "timetable_uploads", ["status"])

    # ------------------------------------------------------------------
    # upload_files
    # ------------------------------------------------------------------
    op.create_table(
        "upload_files",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("upload_id", sa.String(36), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("extension", sa.String(16), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_url", sa.String(512), nullable=False),
        sa.Column("s3_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["upload_id"], ["timetable_uploads.id"],
                                name="fk_upload_files_upload_id_timetable_uploads",
                                ondelete="CASCADE"),
    )
    op.create_index("ix_upload_files_upload_id", "upload_files", ["upload_id"])

    # ------------------------------------------------------------------
    # upload_scanned_pages
    # ------------------------------------------------------------------
    op.create_table(
        "upload_scanned_pages",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("upload_id", sa.String(36), nullable=False),
        sa.Column("file_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("ocr_confidence_avg", sa.Float(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["upload_id"], ["timetable_uploads.id"],
                                name="fk_usp_upload_id_timetable_uploads",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["upload_files.id"],
                                name="fk_usp_file_id_upload_files",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("file_id", "page_number", name="uq_usp_file_page"),
    )
    op.create_index("ix_usp_upload_id", "upload_scanned_pages", ["upload_id"])
    op.create_index("ix_usp_file_id", "upload_scanned_pages", ["file_id"])

    # ------------------------------------------------------------------
    # extracted_units
    # ------------------------------------------------------------------
    op.create_table(
        "extracted_units",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("upload_id", sa.String(36), nullable=False),
        sa.Column("source_file_id", sa.String(36), nullable=True),
        sa.Column("source_page_number", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("day_of_week", sa.String(16), nullable=True),
        sa.Column("start_time", sa.String(8), nullable=True),   # HH:MM
        sa.Column("end_time", sa.String(8), nullable=True),     # HH:MM
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["upload_id"], ["timetable_uploads.id"],
                                name="fk_extracted_units_upload_id_timetable_uploads",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["upload_files.id"],
                                name="fk_extracted_units_source_file_id",
                                ondelete="SET NULL"),
    )
    op.create_index("ix_extracted_units_upload_id", "extracted_units", ["upload_id"])
    op.create_index("ix_extracted_units_code", "extracted_units", ["code"])
    op.create_index("ix_extracted_units_status", "extracted_units", ["status"])


def downgrade() -> None:
    op.drop_index("ix_extracted_units_status", table_name="extracted_units")
    op.drop_index("ix_extracted_units_code", table_name="extracted_units")
    op.drop_index("ix_extracted_units_upload_id", table_name="extracted_units")
    op.drop_table("extracted_units")

    op.drop_index("ix_usp_file_id", table_name="upload_scanned_pages")
    op.drop_index("ix_usp_upload_id", table_name="upload_scanned_pages")
    op.drop_table("upload_scanned_pages")

    op.drop_index("ix_upload_files_upload_id", table_name="upload_files")
    op.drop_table("upload_files")

    op.drop_index("ix_timetable_uploads_status", table_name="timetable_uploads")
    op.drop_index("ix_timetable_uploads_uploaded_by", table_name="timetable_uploads")
    op.drop_index("ix_timetable_uploads_group_id", table_name="timetable_uploads")
    op.drop_table("timetable_uploads")