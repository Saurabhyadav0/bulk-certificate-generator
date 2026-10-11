from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if url.startswith("sqlite"):
        # SQLite connections are used from the API threads and the worker
        # threads, and writers may briefly wait on each other.
        return create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    # Accept plain "postgresql://" URLs (as copied from Neon/Heroku/etc.) and
    # use the psycopg 3 driver for them.
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")

    return create_engine(
        url,
        # Hosted Postgres (e.g. Neon) closes idle connections; check a pooled
        # connection before using it instead of failing the request.
        pool_pre_ping=True,
        pool_recycle=300,
        # Server-side prepared statements don't work through PgBouncer-style
        # poolers in transaction mode (Neon's "-pooler" endpoint).
        connect_args={"prepare_threshold": None},
    )


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    # Importing models registers the tables on Base.metadata.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session per request."""
    with SessionLocal() as db:
        yield db
