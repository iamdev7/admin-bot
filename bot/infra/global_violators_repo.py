"""Repository for managing global violators (users who triggered global blacklist)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GlobalViolator

log = logging.getLogger(__name__)


class GlobalViolatorsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add_violation(
        self,
        user_id: int,
        matched_word: str,
        action: str,
        duration_seconds: Optional[int] = None
    ) -> GlobalViolator:
        """Add or update a global violator record."""
        violator = await self.s.get(GlobalViolator, user_id)
        
        if violator is None:
            # First violation
            expires_at = None
            if duration_seconds:
                expires_at = datetime.utcnow() + timedelta(seconds=duration_seconds)
            
            violator = GlobalViolator(
                user_id=user_id,
                violation_count=1,
                first_violation=datetime.utcnow(),
                last_violation=datetime.utcnow(),
                matched_words=[matched_word],
                action=action,
                expires_at=expires_at
            )
            self.s.add(violator)
        else:
            # Additional violation - update the record
            violator.violation_count += 1
            violator.last_violation = datetime.utcnow()
            
            # Track matched words (keep last 10)
            if matched_word not in violator.matched_words:
                violator.matched_words = (violator.matched_words or []) + [matched_word]
                violator.matched_words = violator.matched_words[-10:]  # Keep last 10
            
            # Update action if it's more severe
            severity_order = {"warn": 0, "mute": 1, "ban": 2}
            if severity_order.get(action, 0) > severity_order.get(violator.action, 0):
                violator.action = action
            
            # Update expiry if new duration is longer
            if duration_seconds:
                new_expires = datetime.utcnow() + timedelta(seconds=duration_seconds)
                if violator.expires_at is None or new_expires > violator.expires_at:
                    violator.expires_at = new_expires
        
        return violator

    async def get_violator(self, user_id: int) -> Optional[GlobalViolator]:
        """Get a global violator record."""
        violator = await self.s.get(GlobalViolator, user_id)
        
        # Check if expired
        if violator and violator.expires_at:
            if datetime.utcnow() > violator.expires_at:
                # Expired - remove the record
                await self.s.delete(violator)
                await self.s.commit()
                return None
        
        return violator

    async def is_violator(self, user_id: int) -> bool:
        """Check if user is a current global violator."""
        violator = await self.get_violator(user_id)
        return violator is not None

    async def remove_violator(self, user_id: int) -> bool:
        """Remove a user from global violators list."""
        violator = await self.s.get(GlobalViolator, user_id)
        if violator:
            await self.s.delete(violator)
            return True
        return False

    async def list_violators(self, limit: int = 100) -> List[GlobalViolator]:
        """List all current global violators."""
        result = await self.s.execute(
            select(GlobalViolator)
            .order_by(GlobalViolator.last_violation.desc())
            .limit(limit)
        )
        violators = result.scalars().all()
        
        # Filter out expired ones
        current_time = datetime.utcnow()
        active_violators = []
        for v in violators:
            if v.expires_at is None or v.expires_at > current_time:
                active_violators.append(v)
            else:
                # Clean up expired
                await self.s.delete(v)
        
        if len(active_violators) < len(violators):
            await self.s.commit()
        
        return active_violators

    async def cleanup_expired(self) -> int:
        """Remove all expired violator records."""
        current_time = datetime.utcnow()
        result = await self.s.execute(
            delete(GlobalViolator).where(
                GlobalViolator.expires_at.isnot(None),
                GlobalViolator.expires_at < current_time
            )
        )
        return result.rowcount