#!/usr/bin/env python3
import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from pathlib import Path
from app.models.user import Base
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "vpn_service.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

async def main():
    try:
        logger.info(f"Создаю таблицы в БД: {DATABASE_URL}")
        engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=True)
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("✅ База данных и таблицы успешно созданы!")
    except Exception as e:
        logger.exception(f"Ошибка при создании БД: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
