from __future__ import annotations

from telegram.ext import Application, CommandHandler

from .handlers import start_panel, settings_cmd, register_callbacks


def register(app: Application) -> None:
    app.add_handler(CommandHandler("panel", start_panel))
    app.add_handler(CommandHandler("settings", settings_cmd))
    register_callbacks(app)
