"""Inbound event persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.delivery_attempt import DeliveryAttempt
    from app.models.outbox import OutboxRecord


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("idx_events_idempotency_key", "idempotency_key", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, server_default=func.gen_random_uuid())
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    delivery_attempts: Mapped[list[DeliveryAttempt]] = relationship(back_populates="event")
    outbox_records: Mapped[list[OutboxRecord]] = relationship(back_populates="event")
