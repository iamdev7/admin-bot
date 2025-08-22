"""Professional logging configuration."""

import logging
import logging.handlers
import sys
from pathlib import Path
from datetime import datetime

# Log levels for different components
LOGGING_CONFIG = {
    # Core bot logging
    "bot": logging.INFO,
    "bot.core": logging.INFO,
    "bot.features": logging.INFO,
    "bot.infra": logging.WARNING,
    
    # Reduce noise from libraries
    "telegram": logging.WARNING,
    "telegram.ext": logging.WARNING,
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "apscheduler": logging.WARNING,
    "sqlalchemy": logging.WARNING,
    "aiosqlite": logging.WARNING,
    
    # Silence very noisy components
    "asyncio": logging.ERROR,
    "urllib3": logging.ERROR,
}


class ColoredFormatter(logging.Formatter):
    """Colored log formatter for console output."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green  
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        
        # Format the message
        result = super().format(record)
        
        # Reset levelname for other handlers
        record.levelname = levelname
        
        return result


def setup_logging(log_file: bool = True, debug: bool = False) -> None:
    """Configure logging for the bot."""
    
    # Create logs directory if needed
    if log_file:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler with color
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Use colored formatter for console
    console_format = "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    console_formatter = ColoredFormatter(
        console_format,
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if enabled)
    if log_file:
        # Create daily rotating log file
        log_filename = log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            log_filename,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Detailed format for file
        file_format = "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) - %(message)s"
        file_formatter = logging.Formatter(
            file_format,
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # Apply specific log levels to components
    for logger_name, level in LOGGING_CONFIG.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
    
    # Log startup
    logging.getLogger(__name__).info(
        f"Logging configured (console={'DEBUG' if debug else 'INFO'}, "
        f"file={'ENABLED' if log_file else 'DISABLED'})"
    )


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with proper configuration."""
    return logging.getLogger(name)