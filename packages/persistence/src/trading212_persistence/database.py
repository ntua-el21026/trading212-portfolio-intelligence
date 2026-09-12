"""Engine, session, and atomic unit-of-work boundaries."""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Self

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from .query_telemetry import DatabaseQueryTiming, QueryObserver

if TYPE_CHECKING:
    from .repositories import ReconciliationRepository, SnapshotRepository


def validate_database_url(url: str | URL) -> URL:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or parsed.get_driver_name() != "psycopg":
        raise ValueError("Phase 1 persistence requires an explicit postgresql+psycopg URL")
    if parsed.database is None:
        raise ValueError("database name is required")
    return parsed


def create_database_engine(
    url: str | URL, *, echo: bool = False, query_observer: QueryObserver | None = None
) -> Engine:
    engine = create_engine(
        validate_database_url(url),
        echo=echo,
        pool_pre_ping=True,
        future=True,
    )
    if query_observer is not None:
        DatabaseQueryTiming(engine, query_observer)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


class UnitOfWork:
    """One transaction; failures always roll back checkpoint and records together."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> Self:
        if self.session is not None:
            raise RuntimeError("unit of work cannot be re-entered")
        self.session = self._session_factory()
        self.session.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None

    def require_session(self) -> Session:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        return self.session

    def snapshots(self) -> SnapshotRepository:
        from .repositories import SnapshotRepository

        return SnapshotRepository(self.require_session())

    def reconciliations(self) -> ReconciliationRepository:
        from .repositories import ReconciliationRepository

        return ReconciliationRepository(self.require_session())
