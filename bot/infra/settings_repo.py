from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GroupSetting


class SettingsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get(self, group_id: int, key: str) -> Optional[dict]:
        q = select(GroupSetting).where(GroupSetting.group_id == group_id, GroupSetting.key == key)
        row = (await self.s.execute(q)).scalars().first()
        return row.value if row else None

    async def set(self, group_id: int, key: str, value: dict) -> None:
        q = select(GroupSetting).where(GroupSetting.group_id == group_id, GroupSetting.key == key)
        row = (await self.s.execute(q)).scalars().first()
        if row is None:
            self.s.add(GroupSetting(group_id=group_id, key=key, value=value))
        else:
            row.value = value

    async def get_text(self, group_id: int, key: str) -> Optional[str]:
        v = await self.get(group_id, key)
        return None if v is None else v.get("text")  # type: ignore[return-value]

    async def set_text(self, group_id: int, key: str, text: str) -> None:
        await self.set(group_id, key, {"text": text})

