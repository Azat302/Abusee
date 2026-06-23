#!/usr/bin/env python3
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
print(f"Project root: {BASE_DIR}")
print(f".env file exists: {(BASE_DIR / '.env').exists()}")

# Read .env directly
with open(BASE_DIR / ".env", "r") as f:
    print("\n.env file contents:")
    print(f.read())

# Load env with override
load_dotenv(BASE_DIR / ".env", override=True)
print("\nLoaded TELEGRAM_BOT_TOKEN:", os.getenv("TELEGRAM_BOT_TOKEN"))
print("Loaded TELEGRAM_ADMIN_ID:", os.getenv("TELEGRAM_ADMIN_ID"))
