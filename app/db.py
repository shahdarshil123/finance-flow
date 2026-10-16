from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Deterministic constraint names keep Alembic migrations stable and reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_settings = get_settings()

# create_engine does not connect; the first connection is opened on first use.
engine = create_engine(
    _settings.database_url,
    echo=_settings.database_echo,
    pool_pre_ping=True,
    connect_args={"connect_timeout": _settings.database_connect_timeout_seconds},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request."""
    with SessionLocal() as session:
        yield session


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the PostgreSQL constraint behind an IntegrityError, if reported."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
