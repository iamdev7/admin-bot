#!/usr/bin/env python3
"""Fix script to add the global settings group to existing databases."""

import asyncio
import sqlite3
from pathlib import Path

DB_PATH = Path("data/bot.db")


def fix_global_group():
    """Add global settings group directly using sqlite3."""
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Check if global group exists
        cursor.execute("SELECT id FROM groups WHERE id = 0")
        result = cursor.fetchone()
        
        if result:
            print("Global settings group already exists")
            return True
        
        # Insert global settings group
        cursor.execute("""
            INSERT INTO groups (id, title, type, created_at)
            VALUES (0, '__GLOBAL_SETTINGS__', 'private', datetime('now'))
        """)
        
        conn.commit()
        print("✅ Successfully added global settings group (id=0)")
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
        
    finally:
        conn.close()


if __name__ == "__main__":
    success = fix_global_group()
    exit(0 if success else 1)