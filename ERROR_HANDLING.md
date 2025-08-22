# Professional Error Handling System

## Features

### 1. **Smart Error Classification**
- Automatically ignores known harmless errors (e.g., "Message not modified")
- Differentiates between critical and non-critical errors
- Handles network timeouts gracefully

### 2. **Admin Notifications**
When an error occurs, bot admins receive:
- 🚨 **Error Report** with:
  - Timestamp (UTC)
  - Error type and message
  - User information (if available)
  - Chat information (if available)
  - Full traceback
  - Update data (truncated if too long)

### 3. **User-Friendly Messages**
- Users receive a generic error message in their language
- No technical details exposed to users
- Graceful degradation when errors occur

### 4. **Logging Configuration**

#### Console Output (Clean & Colored)
- **INFO**: General bot operations (green)
- **WARNING**: Important but non-critical issues (yellow)
- **ERROR**: Errors that need attention (red)

#### File Logging
- Daily rotating log files in `logs/` directory
- Maximum 10MB per file, keeps last 5 files
- Detailed format with file names and line numbers

#### Component Log Levels
```
bot.*           → INFO     (Your bot code)
telegram.*      → WARNING  (Reduce library noise)
httpx/httpcore  → WARNING  (Reduce HTTP noise)
apscheduler     → WARNING  (Reduce scheduler noise)
sqlalchemy      → WARNING  (Reduce database noise)
asyncio         → ERROR    (Only critical issues)
```

## Configuration

### Environment Variables
- `DEBUG=true` - Enable debug logging (shows all messages)
- `OWNER_IDS` - Comma-separated admin IDs who receive error reports

### Example .env
```env
BOT_TOKEN=your_token_here
OWNER_IDS=123456789,987654321
DEBUG=false
```

## Error Types Handled

### 1. **Telegram API Errors**
- `BadRequest` - Invalid API calls
- `Forbidden` - Bot blocked/kicked
- `ChatMigrated` - Group upgraded to supergroup
- `NetworkError` - Connection issues
- `TimedOut` - Request timeouts

### 2. **Application Errors**
- Database errors
- Permission errors
- Validation errors
- Unexpected exceptions

## Monitoring

### Log Files Location
```
logs/
├── bot_20250822.log    # Today's log
├── bot_20250821.log    # Yesterday's log
└── ...
```

### Viewing Logs
```bash
# View today's errors only
grep ERROR logs/bot_$(date +%Y%m%d).log

# Follow log in real-time
tail -f logs/bot_$(date +%Y%m%d).log

# View with color in terminal
python -m bot.main  # Console output is colored
```

## Error Recovery

The bot includes automatic recovery for:
- Database connection issues (reconnects)
- Telegram API rate limits (uses built-in rate limiter)
- Network timeouts (automatic retry)
- Message sending failures (silent fail with logging)

## Admin Commands

When admins receive error notifications, they can:
1. Check the error details in the notification
2. Review full logs in the `logs/` directory
3. Restart the bot if needed
4. Update error handling rules in `bot/core/error_handler.py`

## Customization

### Adding Ignored Errors
Edit `IGNORE_ERRORS` in `bot/core/error_handler.py`:
```python
IGNORE_ERRORS = (
    "Message is not modified",
    "Your custom error to ignore",
    # ...
)
```

### Changing Log Format
Edit `ColoredFormatter` in `bot/core/logging_config.py`

### Adjusting Component Log Levels
Edit `LOGGING_CONFIG` in `bot/core/logging_config.py`