"""Professional error handling system with admin notifications."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from telegram import Update
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.ext import ContextTypes

from .config import settings
from .i18n import I18N, t

# Configure logger
log = logging.getLogger(__name__)

# Error types that should not be reported to admins
IGNORE_ERRORS = (
    "Message is not modified",
    "Message to delete not found",
    "Message can't be deleted",
    "Message identifier is not specified",
    "Chat not found",
    "Not enough rights",
    "User is an administrator of the chat",
    "Can't restrict self",
    "Group chat was upgraded to a supergroup",
)


T = TypeVar("T")


class ErrorHandler:
    """Centralized error handling with admin notifications."""
    
    @staticmethod
    async def handle_error(update: Update | None, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors and notify admins."""
        try:
            # Log the error with traceback
            log.error("Exception while handling an update:", exc_info=context.error)
            
            # Get error details
            error = context.error
            if not error:
                return
                
            # Check if we should ignore this error
            error_message = str(error)
            if any(ignore in error_message for ignore in IGNORE_ERRORS):
                log.debug(f"Ignoring known error: {error_message}")
                return
            
            # Build error report
            tb_list = traceback.format_exception(None, error, error.__traceback__)
            tb_string = "".join(tb_list)
            
            # Build update details
            update_str = ""
            if update:
                update_str = json.dumps(update.to_dict(), indent=2, ensure_ascii=False)
            
            # Create error message for admins
            error_text = await ErrorHandler._format_error_message(
                error, tb_string, update_str, update
            )
            
            # Send to admins
            await ErrorHandler._notify_admins(context, error_text)
            
            # Send user-friendly message if possible
            if update and update.effective_message:
                lang = I18N.pick_lang(update)
                await ErrorHandler._send_with_retry(
                    update.effective_message.reply_text,
                    t(lang, "errors.generic"),
                    retry_label="reply_text",
                )
                    
        except Exception as e:
            log.error(f"Error in error handler: {e}")
    
    @staticmethod
    async def _format_error_message(
        error: Exception,
        tb_string: str,
        update_str: str,
        update: Update | None
    ) -> str:
        """Format error message for admin notification."""
        # Get user and chat info
        user_info = ""
        chat_info = ""
        
        if update:
            if update.effective_user:
                user = update.effective_user
                user_info = f"User: {user.mention_html()} (ID: {user.id})"
            
            if update.effective_chat:
                chat = update.effective_chat
                chat_type = chat.type
                chat_title = html.escape(chat.title or "Private")
                chat_info = f"Chat: {chat_title} ({chat_type}, ID: {chat.id})"
        
        # Truncate traceback if too long
        if len(tb_string) > 2000:
            tb_string = tb_string[-2000:]
        
        # Truncate update if too long
        if len(update_str) > 1000:
            update_str = update_str[:1000] + "..."
        
        # Format timestamp
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Build message
        message_parts = [
            "<b>🚨 Bot Error Report</b>",
            f"<b>Time:</b> {timestamp}",
            f"<b>Error:</b> <code>{html.escape(str(error))}</code>",
        ]
        
        if user_info:
            message_parts.append(user_info)
        if chat_info:
            message_parts.append(chat_info)
        
        message_parts.extend([
            "",
            "<b>Traceback:</b>",
            f"<pre>{html.escape(tb_string)}</pre>",
        ])
        
        if update_str and len(update_str) < 500:  # Only include if not too long
            message_parts.extend([
                "",
                "<b>Update data:</b>",
                f"<pre>{html.escape(update_str)}</pre>",
            ])
        
        return "\n".join(message_parts)
    
    @staticmethod
    async def _notify_admins(context: ContextTypes.DEFAULT_TYPE, error_text: str) -> None:
        """Send error notification to bot admins."""
        for admin_id in settings.OWNER_IDS:
            try:
                # Split message if too long
                if len(error_text) > 4000:
                    # Send first part with main info
                    await ErrorHandler._send_with_retry(
                        context.bot.send_message,
                        chat_id=admin_id,
                        text=error_text[:4000],
                        parse_mode="HTML",
                        disable_notification=False,
                        retry_label=f"notify_admin_{admin_id}",
                    )
                    # Send rest as follow-up
                    remaining = error_text[4000:]
                    if remaining:
                        await ErrorHandler._send_with_retry(
                            context.bot.send_message,
                            chat_id=admin_id,
                            text=f"<b>Continued...</b>\n{remaining[:4000]}",
                            parse_mode="HTML",
                            disable_notification=True,
                            retry_label=f"notify_admin_{admin_id}_continued",
                        )
                else:
                    await ErrorHandler._send_with_retry(
                        context.bot.send_message,
                        chat_id=admin_id,
                        text=error_text,
                        parse_mode="HTML",
                        disable_notification=False,
                        retry_label=f"notify_admin_{admin_id}",
                    )
            except Exception as e:
                log.error(f"Could not send error to admin {admin_id}: {e}")

    @staticmethod
    async def _send_with_retry(
        func: Callable[..., Awaitable[T]],
        *args: Any,
        retry_label: str = "send_message",
        max_attempts: int = 3,
        **kwargs: Any,
    ) -> T | None:
        """Best-effort wrapper around Telegram API calls with backoff."""
        attempt = 0
        while attempt < max_attempts:
            try:
                return await func(*args, **kwargs)
            except RetryAfter as exc:
                attempt += 1
                wait_time = int(exc.retry_after) + 1
                log.warning(
                    "Flood control on %s, retrying in %ss (attempt %s/%s)",
                    retry_label,
                    wait_time,
                    attempt,
                    max_attempts,
                )
                await asyncio.sleep(wait_time)
            except TimedOut:
                attempt += 1
                wait_time = 2 ** attempt
                log.warning(
                    "Timeout on %s, retrying in %ss (attempt %s/%s)",
                    retry_label,
                    wait_time,
                    attempt,
                    max_attempts,
                )
                await asyncio.sleep(wait_time)
            except TelegramError as exc:
                log.error("Telegram error on %s: %s", retry_label, exc)
                break
            except Exception as exc:  # noqa: BLE001 - final safeguard
                log.error("Unexpected error on %s: %s", retry_label, exc)
                break
        return None
    
    @staticmethod
    def handle_bad_request(error: BadRequest) -> bool:
        """Handle BadRequest errors specifically."""
        message = str(error)
        
        # Known ignorable BadRequest errors
        if any(ignore in message for ignore in IGNORE_ERRORS):
            return True  # Handled silently
        
        return False  # Not handled, should be reported
    
    @staticmethod  
    def handle_network_error(error: NetworkError) -> bool:
        """Handle network errors with retry logic."""
        if isinstance(error, TimedOut):
            log.warning("Request timed out, will retry automatically")
            return True
        
        return False
    
    @staticmethod
    def handle_forbidden(error: Forbidden) -> bool:
        """Handle forbidden errors (bot blocked, etc)."""
        message = str(error)
        
        if "bot was blocked by the user" in message:
            log.info("Bot was blocked by a user")
            return True
        
        if "bot was kicked from" in message:
            log.info("Bot was kicked from a chat")
            return True
            
        return False


def setup_error_handlers(application) -> None:
    """Set up error handlers for the application."""
    # Add the main error handler
    application.add_error_handler(ErrorHandler.handle_error)
    
    log.info("Error handlers configured")
