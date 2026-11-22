from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebsiteEditorGrant(Base):
    __tablename__ = "website_editor_grants"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_profiles.id", ondelete="CASCADE"), primary_key=True
    )


class WebsiteDocument(Base):
    __tablename__ = "website_documents"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    draft: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int]
    published_revision: Mapped[int | None]


class WebsiteRevision(Base):
    __tablename__ = "website_revisions"

    key: Mapped[str] = mapped_column(
        String(160), ForeignKey("website_documents.key"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[UUID]
