from __future__ import annotations

import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import Application, ContextTypes

from .i18n import I18N, t


log = logging.getLogger(__name__)


def register_error_handler(app: Application) -> None:
    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:  # type: ignore[override]
        # Ignore harmless Telegram API error when editing with identical content
        err = context.error
        if isinstance(err, BadRequest) and "Message is not modified" in str(err):
            # Reduce noise: this happens when users click the same button repeatedly
            log.debug("Ignored BadRequest: %s", err)
            return
        log.exception("Unhandled error: %s", err)
        if isinstance(update, Update) and update.effective_chat:
            lang = I18N.pick_lang(update)
            try:
                await update.effective_chat.send_message(t(lang, "errors.generic"))
            except Exception:  # pragma: no cover
                pass

    app.add_error_handler(on_error)
