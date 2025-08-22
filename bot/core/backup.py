"""Database backup system with Telegram delivery."""

from __future__ import annotations

import os
import shutil
import gzip
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram.ext import ContextTypes, Application

from .config import settings
from .logging_config import get_logger

log = get_logger(__name__)


class BackupManager:
    """Manages database backups and sends them to admins."""
    
    BACKUP_DIR = Path("backups")
    DB_PATH = Path("data/bot.db")
    
    def __init__(self):
        """Initialize backup manager."""
        self.BACKUP_DIR.mkdir(exist_ok=True)
        
    async def create_backup(self) -> Optional[Path]:
        """Create a compressed backup of the database."""
        try:
            # Check if database exists
            if not self.DB_PATH.exists():
                log.error(f"Database not found at {self.DB_PATH}")
                return None
            
            # Generate backup filename with timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_name = f"bot_backup_{timestamp}.db"
            backup_path = self.BACKUP_DIR / backup_name
            compressed_path = self.BACKUP_DIR / f"{backup_name}.gz"
            
            # Copy database file
            log.info(f"Creating backup: {backup_name}")
            shutil.copy2(self.DB_PATH, backup_path)
            
            # Get file sizes
            original_size = backup_path.stat().st_size
            
            # Compress the backup
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb', compresslevel=9) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove uncompressed backup
            backup_path.unlink()
            
            compressed_size = compressed_path.stat().st_size
            compression_ratio = (1 - compressed_size / original_size) * 100
            
            log.info(
                f"Backup created: {compressed_path.name} "
                f"(compressed {compression_ratio:.1f}%, "
                f"{self._format_size(original_size)} → {self._format_size(compressed_size)})"
            )
            
            return compressed_path
            
        except Exception as e:
            log.error(f"Failed to create backup: {e}")
            return None
    
    async def send_backup_to_admins(
        self, 
        context: ContextTypes.DEFAULT_TYPE,
        backup_path: Path
    ) -> None:
        """Send backup file to all bot admins."""
        if not settings.OWNER_IDS:
            log.warning("No admin IDs configured for backup delivery")
            return
        
        # Prepare backup info
        file_size = backup_path.stat().st_size
        creation_time = datetime.fromtimestamp(backup_path.stat().st_ctime)
        
        # Get database stats
        stats = await self._get_db_stats()
        
        caption = (
            "📦 <b>Daily Database Backup</b>\n"
            f"📅 Date: {creation_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"📊 Size: {self._format_size(file_size)} (compressed)\n"
            f"\n<b>Database Statistics:</b>\n"
            f"👥 Users: {stats.get('users', 0)}\n"
            f"💬 Groups: {stats.get('groups', 0)}\n"
            f"🤖 Automations: {stats.get('automations', 0)}\n"
            f"📝 Audit Logs: {stats.get('audit_logs', 0)}\n"
            f"🚫 Global Violators: {stats.get('violators', 0)}\n"
            f"\n💡 <i>Backup is compressed with gzip</i>"
        )
        
        # Send to each admin
        sent_count = 0
        failed_count = 0
        
        for admin_id in settings.OWNER_IDS:
            try:
                with open(backup_path, 'rb') as backup_file:
                    await context.bot.send_document(
                        chat_id=admin_id,
                        document=backup_file,
                        filename=backup_path.name,
                        caption=caption,
                        parse_mode="HTML",
                        disable_notification=True,
                    )
                sent_count += 1
                log.info(f"Backup sent to admin {admin_id}")
                
            except Exception as e:
                failed_count += 1
                log.error(f"Failed to send backup to admin {admin_id}: {e}")
        
        if sent_count > 0:
            log.info(f"Backup sent to {sent_count} admin(s)")
        if failed_count > 0:
            log.warning(f"Failed to send backup to {failed_count} admin(s)")
    
    async def cleanup_old_backups(self, keep_days: int = 7) -> None:
        """Remove old backup files."""
        try:
            cutoff_time = datetime.utcnow().timestamp() - (keep_days * 86400)
            
            for backup_file in self.BACKUP_DIR.glob("bot_backup_*.db.gz"):
                if backup_file.stat().st_mtime < cutoff_time:
                    backup_file.unlink()
                    log.info(f"Deleted old backup: {backup_file.name}")
                    
        except Exception as e:
            log.error(f"Failed to cleanup old backups: {e}")
    
    async def perform_backup(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Perform a complete backup cycle."""
        log.info("Starting scheduled backup")
        
        # Create backup
        backup_path = await self.create_backup()
        if not backup_path:
            log.error("Backup creation failed")
            
            # Notify admins of failure
            for admin_id in settings.OWNER_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text="⚠️ <b>Backup Failed</b>\n\nDatabase backup could not be created. Please check the logs.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            return
        
        # Send to admins
        await self.send_backup_to_admins(context, backup_path)
        
        # Cleanup old backups
        await self.cleanup_old_backups(keep_days=7)
        
        log.info("Backup cycle completed")
    
    async def _get_db_stats(self) -> dict:
        """Get database statistics."""
        try:
            from ..infra import db
            from sqlalchemy import select, func
            from ..infra.models import User, Group, Job, AuditLog, GlobalViolator
            
            stats = {}
            
            async with db.SessionLocal() as session:  # type: ignore
                stats['users'] = await session.scalar(
                    select(func.count()).select_from(User)
                ) or 0
                stats['groups'] = await session.scalar(
                    select(func.count()).select_from(Group)
                ) or 0
                stats['automations'] = await session.scalar(
                    select(func.count()).select_from(Job)
                ) or 0
                stats['audit_logs'] = await session.scalar(
                    select(func.count()).select_from(AuditLog)
                ) or 0
                stats['violators'] = await session.scalar(
                    select(func.count()).select_from(GlobalViolator)
                ) or 0
            
            return stats
            
        except Exception as e:
            log.error(f"Failed to get database stats: {e}")
            return {}
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


def schedule_backups(app: Application) -> None:
    """Schedule daily backups using Telegram's job queue."""
    manager = BackupManager()
    
    # Wrapper to pass the context properly
    async def backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await manager.perform_backup(context)
    
    # Schedule daily backup (every 24 hours)
    app.job_queue.run_repeating(
        backup_job,
        interval=86400,  # 24 hours in seconds
        first=60,  # First backup 1 minute after startup
        name="daily_backup",
    )
    
    log.info("Backup schedule configured (every 24 hours, first in 1 minute)")


async def manual_backup_command(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle manual backup command from admins."""
    if not update.effective_user or update.effective_user.id not in settings.OWNER_IDS:
        return
    
    await update.message.reply_text("🔄 Creating backup...")
    
    manager = BackupManager()
    backup_path = await manager.create_backup()
    
    if backup_path:
        await manager.send_backup_to_admins(context, backup_path)
        await update.message.reply_text("✅ Backup created and sent!")
    else:
        await update.message.reply_text("❌ Backup failed. Check logs for details.")