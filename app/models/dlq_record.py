"""Dead-letter queue persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.delivery_attempt import DeliveryAttempt


class DLQRecord(Base):
    __tablename__ = "dlq_records"
    __table_args__ = (UniqueConstraint("event_id", "subscription_id", name="uq_dlq_event_subscription"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id"), nullable=False)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"), nullable=False)
    final_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("delivery_attempts.id")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    final_attempt: Mapped[DeliveryAttempt | None] = relationship(back_populates="dlq_record")
