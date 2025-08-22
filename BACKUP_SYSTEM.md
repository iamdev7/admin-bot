# Database Backup System

## Overview
The bot includes an automated database backup system that sends compressed backups directly to bot administrators via Telegram.

## Features

### 🔄 **Automatic Daily Backups**
- Backups are created automatically every 24 hours
- First backup occurs 1 minute after bot startup
- Subsequent backups every 24 hours from startup time

### 📦 **Backup Contents**
Each backup includes:
- Complete SQLite database
- All user data
- All group settings
- Automation configurations
- Audit logs
- Global blacklist and violators

### 🗜️ **Compression**
- Backups are compressed using gzip (level 9)
- Typical compression ratio: 60-80%
- Reduces file size for faster Telegram uploads

### 📊 **Statistics**
Each backup includes database statistics:
- Total users
- Total groups
- Active automations
- Audit log entries
- Global violators

### 🗑️ **Automatic Cleanup**
- Old backups are automatically deleted after 7 days
- Keeps disk usage under control
- Maintains only recent backups

## Manual Backup

Bot owners can create a backup anytime using:
```
/backup
```

This will:
1. Create a compressed backup immediately
2. Send it to all configured bot owners
3. Clean up old backups

## Backup Storage

### Local Storage
```
backups/
├── bot_backup_20250822_020000.db.gz
├── bot_backup_20250821_020000.db.gz
└── ...
```

### Telegram Storage
- Backups are sent as documents to admin accounts
- Stored in Telegram's cloud indefinitely
- Can be downloaded anytime from chat history

## Configuration

### Required Settings
In your `.env` file:
```env
OWNER_IDS=123456789,987654321  # Admins who receive backups
```

### Backup Schedule
- **Interval**: Every 24 hours
- **First backup**: 1 minute after startup
- **Cleanup**: Removes backups older than 7 days

## Restoring from Backup

To restore a database from backup:

1. **Download the backup** from Telegram
2. **Extract the database**:
   ```bash
   gunzip bot_backup_20250822_020000.db.gz
   ```
3. **Stop the bot**
4. **Replace the database**:
   ```bash
   cp bot_backup_20250822_020000.db data/bot.db
   ```
5. **Restart the bot**

## Backup Notifications

Admins receive a Telegram message with:
- 📦 **Backup file** (compressed .db.gz)
- 📅 **Timestamp** of backup creation
- 📊 **File size** (compressed)
- 📈 **Database statistics**

Example notification:
```
📦 Daily Database Backup
📅 Date: 2025-08-22 02:00:00 UTC
📊 Size: 245.3 KB (compressed)

Database Statistics:
👥 Users: 1,234
💬 Groups: 56
🤖 Automations: 12
📝 Audit Logs: 5,678
🚫 Global Violators: 23

💡 Backup is compressed with gzip
```

## Error Handling

If a backup fails:
- Error is logged to file
- Admins receive failure notification
- Next scheduled backup will retry
- Manual `/backup` can be used as fallback

## Security Considerations

### Access Control
- Only bot owners receive backups
- `/backup` command restricted to owners
- Backups contain sensitive data

### Data Protection
- Keep Telegram accounts secure
- Use 2FA on admin accounts
- Regularly download backups for offline storage
- Consider encrypting sensitive backups

## Troubleshooting

### Backup Not Received
1. Check `OWNER_IDS` in `.env`
2. Verify bot has permission to send files
3. Check logs for errors
4. Try manual `/backup` command

### Large Database Issues
- Backups may fail if database > 50MB (Telegram limit)
- Consider more aggressive compression
- Implement database cleanup routines
- Archive old audit logs

### Restore Issues
1. Ensure bot is stopped before restore
2. Check file permissions after restore
3. Verify database integrity:
   ```bash
   sqlite3 data/bot.db "PRAGMA integrity_check;"
   ```

## Best Practices

1. **Regular Downloads**: Download backups weekly to local storage
2. **Test Restores**: Periodically test restore process
3. **Monitor Size**: Watch database growth trends
4. **Secure Storage**: Keep offline copies in secure location
5. **Documentation**: Document your restore procedures