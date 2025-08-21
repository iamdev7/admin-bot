from __future__ import annotations

from telegram.ext import Application, CommandHandler

from .handlers import register_handlers, add_rule_cmd, list_rules_cmd, del_rule_cmd


def register(app: Application) -> None:
    register_handlers(app)
    app.add_handler(CommandHandler("addrule", add_rule_cmd))
    app.add_handler(CommandHandler("listrules", list_rules_cmd))
    app.add_handler(CommandHandler("delrule", del_rule_cmd))
