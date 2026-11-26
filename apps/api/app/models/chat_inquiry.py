from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatInquiry(Base):
    __tablename__ = "chat_inquiries"

    reference: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[UUID] = mapped_column(unique=True)
    # An opaque receipt may have no lead if the mobile belongs to an operational
    # identity. In that case the submitted contact and preferences are discarded.
    lead_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    service: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    name: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(120))
    preferences: Mapped[dict[str, str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
