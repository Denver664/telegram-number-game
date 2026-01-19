#!/usr/bin/env python3
"""
Скрипт для швидкого завантаження бота на Railway
Використовуйте цей скрипт, якщо у вас проблеми з Git
"""

import os
import json
import shutil
import subprocess
from pathlib import Path

def create_zip():
    """Створює ZIP архів для завантаження на Railway"""
    print("📦 Створюю архів для Railway...")
    
    files_to_include = [
        "aibot.py",
        "requirements.txt",
        "Procfile",
        ".gitignore",
        "leaderboard.json"
    ]
    
    # Створюємо папку для архіву
    archive_name = "telegram-bot"
    
    # Архівуємо файли
    try:
        shutil.make_archive(archive_name, 'zip', '.', base_name='.')
        print(f"✅ Архів створено: {archive_name}.zip")
        print(f"\n📤 Завантажте файл на Railway:")
        print(f"   1. Зайдіть на https://railway.app")
        print(f"   2. Натисніть 'New Project'")
        print(f"   3. Виберіть 'Deploy from GitHub' або завантажте ZIP")
        print(f"\n💾 Файл знаходиться у поточній папці: {archive_name}.zip")
    except Exception as e:
        print(f"❌ Помилка: {e}")

if __name__ == "__main__":
    create_zip()
