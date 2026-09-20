"""
database.py
Royal Metal Allocation System — Python port

SQLAlchemy engine, session factory, declarative base, and the get_db()
dependency every router/service uses to obtain a session. No models and no
business logic here (CLAUDE.md section 2, "Where things belong").
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

# check_same_thread=False: FastAPI runs sync routes in a threadpool, so a
# request's DB session may be used from a different thread than the one
# that created it. Only meaningful for SQLite — ignored by other dialects.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
