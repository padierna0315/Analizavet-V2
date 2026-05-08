
import asyncio
import os
import sys

from sqlmodel import SQLModel, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

# Add the project root to the sys.path to allow importing 'app' modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from app.config import settings
from app.shared.models.patient import Patient, TestResult, LabValue, PatientImage # Import all models to populate SQLModel.metadata

DATABASE_URL = settings.DATABASE_URL
engine = create_async_engine(DATABASE_URL, echo=True)

async def clear_and_create_db():
    print(f"Connecting to database: {DATABASE_URL}")
    async with engine.begin() as conn:
        print("Dropping all tables...")
        await conn.run_sync(SQLModel.metadata.drop_all)
        print("Creating all tables...")
        await conn.run_sync(SQLModel.metadata.create_all)
    print("Database cleared and tables recreated successfully!")

if __name__ == "__main__":
    asyncio.run(clear_and_create_db())
