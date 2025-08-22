from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import db
from .models import Base, Group

log = logging.getLogger(__name__)


async def migrate() -> None:
    assert db.engine is not None, "Engine not initialized"
    async with db.engine.begin() as conn:  # type: ignore
        await conn.run_sync(Base.metadata.create_all)
    await db.set_sqlite_pragmas()
    
    # Create special group entry for global settings (group_id=0)
    await ensure_global_group()


async def ensure_global_group() -> None:
    """Ensure the special global settings group (id=0) exists."""
    try:
        async with db.SessionLocal() as session:  # type: ignore
            # Check if global group exists
            result = await session.execute(
                select(Group).where(Group.id == 0)
            )
            global_group = result.scalar_one_or_none()
            
            if not global_group:
                # Create global group for bot-wide settings
                global_group = Group(
                    id=0,
                    title="__GLOBAL_SETTINGS__",
                    type="private"  # Use private type since it's not a real group
                )
                session.add(global_group)
                await session.commit()
                log.info("Created global settings group (id=0)")
            else:
                log.debug("Global settings group already exists")
                
    except Exception as e:
        log.error(f"Error ensuring global group: {e}")
