"""
Break-glass singleton config.

Holds only the SHA-256 hash of the split unlock token. The token itself is
never stored. The shares exist only in the hands of the custodians.
"""
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class BreakGlassConfig(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "break_glass_config"

    unlock_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    last_used_at: Mapped["object | None"] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )