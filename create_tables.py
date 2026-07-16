"""
Database initialization script.

Creates the pgvector extension (required by the Vector columns) and all
tables defined in database/models.py.

Usage:
    python create_tables.py
"""
from sqlalchemy import create_engine, text

from config import config
from database.models import Base


def main():
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

    engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)

    # pgvector must exist before create_all() tries to build vector(1536) columns.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.create_all(engine)
    print("✅ pgvector extension ensured and all tables created.")


if __name__ == "__main__":
    main()
