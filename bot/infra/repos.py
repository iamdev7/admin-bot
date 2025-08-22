from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Group, GroupAdmin, User, AuditLog, Filter, Job


class GroupsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert_group(self, gid: int, title: str, username: Optional[str], gtype: str) -> None:
        g = await self.s.get(Group, gid)
        if g is None:
            self.s.add(Group(id=gid, title=title, username=username, type=gtype))
        else:
            g.title = title
            g.username = username

    async def list_admin_groups(self, user_id: int) -> list[Group]:
        q = select(Group).join(GroupAdmin, GroupAdmin.group_id == Group.id).where(
            GroupAdmin.user_id == user_id
        )
        rows = (await self.s.execute(q)).scalars().all()
        return list(rows)


class GroupAdminsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert_admin(self, group_id: int, user_id: int, status: str, rights: dict) -> None:
        admin = await self.s.get(GroupAdmin, {"group_id": group_id, "user_id": user_id})
        if admin is None:
            self.s.add(
                GroupAdmin(
                    group_id=group_id, user_id=user_id, status=status, rights=rights, updated_at=datetime.utcnow()
                )
            )
        else:
            admin.status = status
            admin.rights = rights
            admin.updated_at = datetime.utcnow()

    async def delete_admin(self, group_id: int, user_id: int) -> None:
        admin = await self.s.get(GroupAdmin, {"group_id": group_id, "user_id": user_id})
        if admin is not None:
            await self.s.delete(admin)


class UsersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def upsert_user(
        self,
        uid: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        language: Optional[str],
    ) -> None:
        from sqlalchemy.exc import IntegrityError
        
        # Try to get existing user first
        u = await self.s.get(User, uid)
        if u is None:
            # User doesn't exist, try to create
            try:
                self.s.add(
                    User(
                        id=uid,
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        language=language,
                        seen_at=datetime.utcnow(),  # Explicitly set seen_at for new users
                    )
                )
                # Flush to catch IntegrityError before commit
                await self.s.flush()
            except IntegrityError:
                # Another request already created the user, rollback and fetch it
                await self.s.rollback()
                u = await self.s.get(User, uid)
                if u:
                    # Update the existing user
                    u.username = username
                    u.first_name = first_name
                    u.last_name = last_name
                    u.language = language
                    u.seen_at = datetime.utcnow()
        else:
            # User exists, update it
            u.username = username
            u.first_name = first_name
            u.last_name = last_name
            u.language = language
            u.seen_at = datetime.utcnow()  # Update seen_at for existing users


class AuditRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def log(
        self, group_id: int, actor_id: int, action: str, target_user_id: Optional[int], extra: dict
    ) -> None:
        self.s.add(
            AuditLog(
                group_id=group_id,
                actor_id=actor_id,
                action=action,
                target_user_id=target_user_id,
                extra=extra,
            )
        )


class FiltersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add_rule(
        self, group_id: int, ftype: str, pattern: str, action: str, added_by: int, extra: dict | None = None
    ) -> Filter:
        f = Filter(
            group_id=group_id, type=ftype, pattern=pattern, action=action, added_by=added_by, extra=extra or {}
        )
        self.s.add(f)
        await self.s.flush()
        return f
    
    async def list_rules(self, group_id: int, limit: int = 100) -> list[Filter]:
        q = select(Filter).where(Filter.group_id == group_id).limit(limit)
        rows = (await self.s.execute(q)).scalars().all()
        return list(rows)

    async def delete_rule(self, group_id: int, rule_id: int) -> bool:
        f = await self.s.get(Filter, rule_id)
        if f and f.group_id == group_id:
            await self.s.delete(f)
            return True
        return False


class WarnsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(self, group_id: int, user_id: int, reason: str | None, created_by: int) -> None:
        from .models import Warn

        self.s.add(Warn(group_id=group_id, user_id=user_id, reason=reason, created_by=created_by))

    async def remove_one(self, group_id: int, user_id: int) -> bool:
        from sqlalchemy import select
        from .models import Warn

        q = select(Warn).where(Warn.group_id == group_id, Warn.user_id == user_id).order_by(Warn.id.desc())
        row = (await self.s.execute(q)).scalars().first()
        if row:
            await self.s.delete(row)
            return True
        return False

    async def count(self, group_id: int, user_id: int) -> int:
        from sqlalchemy import func, select
        from .models import Warn

        q = select(func.count()).select_from(Warn).where(Warn.group_id == group_id, Warn.user_id == user_id)
        return int((await self.s.execute(q)).scalar_one())

    async def reset(self, group_id: int, user_id: int) -> None:
        from sqlalchemy import select
        from .models import Warn

        q = select(Warn).where(Warn.group_id == group_id, Warn.user_id == user_id)
        rows = (await self.s.execute(q)).scalars().all()
        for r in rows:
            await self.s.delete(r)


class JobsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(self, group_id: int, kind: str, payload: dict, run_at, interval_sec: int | None) -> Job:
        j = Job(group_id=group_id, kind=kind, payload=payload, run_at=run_at, interval_sec=interval_sec)
        self.s.add(j)
        await self.s.flush()
        return j

    async def list_by_group(self, group_id: int, limit: int = 50) -> list[Job]:
        q = select(Job).where(Job.group_id == group_id).order_by(Job.run_at.asc()).limit(limit)
        return list((await self.s.execute(q)).scalars().all())

    async def get(self, job_id: int) -> Job | None:
        return await self.s.get(Job, job_id)

    async def delete(self, job_id: int) -> bool:
        j = await self.s.get(Job, job_id)
        if j is not None:
            await self.s.delete(j)
            return True
        return False

    async def update_next_run(self, job_id: int, next_run) -> None:
        j = await self.s.get(Job, job_id)
        if j is not None:
            j.run_at = next_run

    async def update_payload(self, job_id: int, payload: dict) -> None:
        j = await self.s.get(Job, job_id)
        if j is not None:
            j.payload = payload

    async def list_rules(self, group_id: int, limit: int = 50) -> list[Filter]:
        q = select(Filter).where(Filter.group_id == group_id).order_by(Filter.id.desc()).limit(limit)
        rows = (await self.s.execute(q)).scalars().all()
        return list(rows)

    async def delete_rule(self, group_id: int, rule_id: int) -> bool:
        f = await self.s.get(Filter, rule_id)
        if f and f.group_id == group_id:
            await self.s.delete(f)
            return True
        return False
