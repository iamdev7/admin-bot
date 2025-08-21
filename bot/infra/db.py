from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker, AsyncSession


engine: Optional[AsyncEngine] = None
SessionLocal: Optional[async_sessionmaker[AsyncSession]] = None


async def init_engine(dsn: str) -> None:
    global engine
    if engine is None:
        engine = create_async_engine(dsn, future=True, echo=False)


def init_sessionmaker() -> None:
    global SessionLocal
    if SessionLocal is None:
        assert engine is not None, "Engine not initialized"
        SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def set_sqlite_pragmas() -> None:
    assert engine is not None
    if not engine.url.database:
        return
    async with engine.begin() as conn:  # type: ignore
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON;")

