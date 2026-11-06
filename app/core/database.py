import os
import sys
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

Base = declarative_base()


def is_test_environment() -> bool:
    if os.getenv("TESTING", "False").lower() == "true":
        return True
    if any("pytest" in str(arg).lower() for arg in sys.argv):
        return True
    if any(m.startswith("pytest") for m in sys.modules):
        return True
    return False


def create_db_engine():
    if is_test_environment():
        test_url = "sqlite:///./ledgerline_test.db"
        eng = create_engine(
            test_url,
            connect_args={"check_same_thread": False},
            echo=False,
        )

        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return eng

    raw_url = settings.DATABASE_URL or "sqlite:///./ledgerline.db"
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif raw_url.startswith("postgresql://") and not raw_url.startswith("postgresql+"):
        raw_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

    if raw_url.startswith("sqlite"):
        eng = create_engine(
            raw_url,
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )

        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return eng

    # PostgreSQL with fast timeout fallback
    try:
        eng = create_engine(
            raw_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            connect_args={"connect_timeout": 3},
            echo=settings.DEBUG,
        )
        # Test connection fast
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return eng
    except Exception:
        # Fallback to local SQLite if cloud postgres is unreachable
        sqlite_url = "sqlite:///./ledgerline.db"
        eng = create_engine(
            sqlite_url,
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )

        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return eng


engine = create_db_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
