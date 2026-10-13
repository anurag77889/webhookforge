"""Async database engine, session factory and declarative base."""

from collections.abc import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_async_engine(settings.POSTGRES_URL, pool_pre_ping=True)
sync_engine = create_engine(settings.postgres_url_sync, pool_pre_ping=True)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
SyncSessionFactory = sessionmaker(sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
