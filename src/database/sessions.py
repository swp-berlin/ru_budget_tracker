"""Relational database setup."""

from contextlib import contextmanager
from typing import Iterator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from settings import settings

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_engine(
    url=settings.database.sync_dsn,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1_800,
    connect_args={"timeout": 60},
)


# SQLite performance pragmas: WAL mode for concurrent reads, larger cache.
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Configure SQLite pragmas for better performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
    cursor.close()


@event.listens_for(engine, "first_connect")
def _optimize_on_startup(dbapi_connection, connection_record):
    """Update query planner statistics once at startup."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA optimize")
    cursor.close()


LocalSyncSession = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)

async_engine = create_async_engine(
    url=settings.database.async_dsn,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1_800,
)

LocalAsyncSession = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


@contextmanager
def get_sync_session() -> Iterator[Session]:
    """Start context manager for a complete session lifecycle.

    Example:
        with get_sync_session() as session:
            do_stuff()

    Yields
    ------
    Session
        SQLAlchemy Session object.
    """
    session = LocalSyncSession()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Create an asynchronous SQLAlchemy session.
    Use as a dependency in FastAPI routes or other async contexts in dashboard,
    for example database calls.

    Yields
    ------
    AsyncSession
        SQLAlchemy asynchronous Session object.
    """

    async with LocalAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logging.exception(e)
            await session.rollback()
            raise
