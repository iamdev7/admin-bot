# Telegram Admin Bot

A production-grade, extensible Telegram group management bot built with modern async Python. Designed to help administrators maintain order, automate tasks, and enhance group security.

## Features

### Core Moderation
- **User Management**: Warn, mute, ban/unban users with granular control
- **Message Control**: Bulk message deletion (purge), content filtering
- **Permission System**: Role-based access for owners and admins

### Anti-Spam Protection
- Configurable spam detection and prevention
- User join flood protection
- Link and forward filtering
- Automatic blacklist enforcement

### Group Onboarding
- Custom welcome messages with user mentions
- Join request handling with rule acceptance workflow
- Automatic rule distribution via DM
- Topic-based organization support

### Automation
- Scheduled announcements and broadcasts
- Automated moderation actions
- Database backups with configurable schedules
- Admin synchronization across groups

### AI-Powered Responses (Optional)
- Intelligent message replies using OpenAI
- Context-aware group interactions
- Configurable per-group settings

### Multi-Language Support
- English and Arabic translations included
- Easy-to-extend i18n system
- Per-user language preferences

## Tech Stack

- **Python 3.11+**: Modern async/await syntax
- **python-telegram-bot v22**: Latest async Telegram Bot API wrapper
- **SQLAlchemy 2.0**: Async ORM with SQLite backend
- **Pydantic**: Configuration validation
- **OpenAI API**: Optional AI response capabilities

## Installation

### Prerequisites
- Python 3.11 or higher
- A Telegram Bot Token (get one from [@BotFather](https://t.me/BotFather))

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd admin-bot
   ```

2. **Create a virtual environment**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -e .
   ```

4. **Configure environment variables**
   Edit `.env` and set your configuration:
   ```env
   BOT_TOKEN=your_bot_token_from_botfather
   OWNER_IDS=123456789  # Your Telegram user ID (comma-separated for multiple owners)
   DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
   DEFAULT_LANG=en

   # Optional: For AI features
   # GEMINI_API_KEY=your-gemini-api-key
   # OPENAI_API_KEY=sk-your-openai-api-key
   ```

5. **Initialize the database**
   ```bash
   python -m bot.infra.migrate
   ```

6. **Seed initial data** (optional)
   ```bash
   python scripts/seed.py
   ```

7. **Run the bot**
   ```bash
   python -m bot.main
   ```

## Configuration

### Environment Variables

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `BOT_TOKEN` | Yes | Telegram Bot API token from BotFather | - |
| `OWNER_IDS` | Yes | Comma-separated list of bot owner Telegram IDs | - |
| `DATABASE_URL` | No | SQLAlchemy database connection URL | `sqlite+aiosqlite:///./data/bot.db` |
| `DEFAULT_LANG` | No | Default language (en/ar) | `en` |
| `GEMINI_API_KEY` | No | Google Gemini API key for AI responses | - |
| `OPENAI_API_KEY` | No | OpenAI API key for AI responses | - |

### Getting Your Telegram User ID

1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. Copy your user ID
3. Add it to `OWNER_IDS` in `.env`

## Usage

### Basic Commands

**Private Chat:**
- `/start` - Welcome message and control panel
- `/panel` - Group management interface
- `/help` - Command list and documentation
- `/privacy` - Privacy policy

**Group Admin Commands:**
- `/warn @user` - Issue a warning to a user
- `/unwarn @user` - Remove warnings from a user
- `/mute @user [duration]` - Mute a user (e.g., `/mute @user 1h`)
- `/unmute @user` - Unmute a user
- `/ban @user` - Ban a user from the group
- `/unban @user` - Unban a user
- `/purge` - Delete messages (reply to start message)
- `/rules` - Display group rules
- `/setrules` - Set group rules (reply with text)
- `/settings` - Open settings panel

**Bot Owner Commands:**
- `/bot` - Bot administration panel
- `/backup` - Create manual database backup
- `/broadcast` - Send announcements to all groups

### Setting Up Your First Group

1. Add the bot to your Telegram group
2. Promote the bot to admin with all permissions
3. Send `/panel` to the bot in private chat
4. Configure welcome messages, rules, and anti-spam settings
5. Test with a new user join

## Project Structure

```
admin-bot/
├── bot/
│   ├── core/              # Core utilities and configuration
│   │   ├── config.py      # Pydantic settings
│   │   ├── i18n.py        # Internationalization
│   │   ├── permissions.py # Access control
│   │   └── ...
│   ├── features/          # Feature modules
│   │   ├── moderation/    # Ban, warn, mute commands
│   │   ├── antispam/      # Spam detection
│   │   ├── welcome/       # Welcome messages
│   │   ├── rules/         # Rules management
│   │   ├── automations/   # Scheduled tasks
│   │   ├── ai_response/   # AI-powered responses
│   │   └── ...
│   ├── infra/             # Infrastructure layer
│   │   ├── db.py          # Database engine
│   │   ├── models.py      # SQLAlchemy models
│   │   ├── repos.py       # Data repositories
│   │   └── migrate.py     # Database migrations
│   ├── locales/           # Translation files
│   │   ├── en.json        # English translations
│   │   └── ar.json        # Arabic translations
│   └── main.py            # Application entry point
├── scripts/               # Utility scripts
├── .env                   # Environment configuration (sample values)
├── .gitignore             # Git ignore rules
├── pyproject.toml         # Project metadata and dependencies
└── README.md              # This file
```

## Development

### Installing Development Dependencies

```bash
pip install -e ".[dev]"
```

### Code Quality Tools

**Linting:**
```bash
ruff check .
```

**Formatting:**
```bash
black .
```

**Type Checking:**
```bash
mypy bot
```

### Database Migrations

The bot automatically runs migrations on startup. To manually run migrations:

```bash
python -m bot.infra.migrate
```

### Adding New Features

1. Create a new module in `bot/features/`
2. Implement handlers following the existing pattern
3. Register handlers in `bot/main.py`
4. Add translations to `bot/locales/en.json` and `bot/locales/ar.json`

## Deployment

### Running in Production

**Using systemd (Linux):**

1. Create a service file at `/etc/systemd/system/admin-bot.service`:
   ```ini
   [Unit]
   Description=Telegram Admin Bot
   After=network.target

   [Service]
   Type=simple
   User=your-user
   WorkingDirectory=/path/to/admin-bot
   Environment="PATH=/path/to/admin-bot/.venv/bin"
   ExecStart=/path/to/admin-bot/.venv/bin/python -m bot.main
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

2. Enable and start:
   ```bash
   sudo systemctl enable admin-bot
   sudo systemctl start admin-bot
   sudo systemctl status admin-bot
   ```

**Using Docker:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install -e .

COPY . .

CMD ["python", "-m", "bot.main"]
```

```bash
docker build -t admin-bot .
docker run -d --name admin-bot --env-file .env admin-bot
```

## Security & Privacy

- **Data Storage**: All data is stored locally in SQLite (no external services)
- **Secrets Management**: Use `.env` for sensitive configuration (never commit to git)
- **Permissions**: Bot respects Telegram's permission system
- **Privacy**: Minimal data collection (only what's necessary for functionality)

### Security Best Practices

1. **Regenerate Bot Token**: If your bot token is ever exposed, regenerate it via @BotFather
2. **Restrict Owner IDs**: Only add trusted user IDs to `OWNER_IDS`
3. **Keep Dependencies Updated**: Regularly update Python packages
4. **Review Logs**: Monitor `logs/` directory for suspicious activity
5. **Backup Database**: Regular backups are created in `backups/` directory

## Troubleshooting

### Common Issues

**Bot doesn't respond:**
- Verify `BOT_TOKEN` is correct
- Check bot is admin in the group
- Review logs in `logs/` directory

**Database errors:**
- Ensure `data/` directory exists and is writable
- Run migrations: `python -m bot.infra.migrate`

**Permission errors:**
- Verify your user ID is in `OWNER_IDS`
- Ensure bot has admin rights in the group

**AI responses not working:**
- Verify either `GEMINI_API_KEY` or `OPENAI_API_KEY` is set in `.env`
- Check provider quota and billing

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes following the existing code style
4. Run linters and type checkers
5. Add tests if applicable
6. Commit with clear messages
7. Push and create a Pull Request

## License

This project is provided as-is for educational and personal use.

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Contact: [@codei8](https://t.me/codei8)

## Acknowledgments

Built with:
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [OpenAI API](https://openai.com/)

---

**Developer**: altmemy
**Updates Channel**: [@codei8](https://t.me/codei8)
