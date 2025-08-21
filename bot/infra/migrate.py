from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .models import Base


async def migrate() -> None:
    assert db.engine is not None, "Engine not initialized"
    async with db.engine.begin() as conn:  # type: ignore
        await conn.run_sync(Base.metadata.create_all)
    await db.set_sqlite_pragmas()
