#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from bot.core.config import settings
from bot.infra import db
from bot.infra.migrate import migrate
from bot.infra.models import User


async def main() -> None:
    # Ensure data directory exists for SQLite path
    from pathlib import Path
    Path("data").mkdir(exist_ok=True)
    
    await db.init_engine(settings.DATABASE_URL)
    db.init_sessionmaker()
    await migrate()
    async with db.SessionLocal() as s:  # type: ignore
        for uid in settings.OWNER_IDS:
            if await s.get(User, uid) is None:
                s.add(User(id=uid, username=None, first_name=None, last_name=None, language="en"))
        await s.commit()


if __name__ == "__main__":
    asyncio.run(main())

