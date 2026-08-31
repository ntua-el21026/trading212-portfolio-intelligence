"""SQLAlchemy types preserving exact decimals and aware UTC instants."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator
from trading212_domain import exact_decimal, require_utc


class ExactNumeric(TypeDecorator[Decimal]):
    """NUMERIC(38,18) that rejects binary floats on every bind."""

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Decimal]:
        return dialect.type_descriptor(Numeric(precision=38, scale=18, asdecimal=True))

    def process_bind_param(
        self, value: Decimal | int | str | None, dialect: Dialect
    ) -> Decimal | None:
        del dialect
        return None if value is None else exact_decimal(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        del dialect
        return None if value is None else exact_decimal(value)


class UTCDateTime(TypeDecorator[datetime]):
    """TIMESTAMPTZ boundary that rejects naive datetimes and returns UTC."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[datetime]:
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        return None if value is None else require_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        return None if value is None else require_utc(value)
