"""Sealed GET-only Trading 212 client with bounded retries and strict DTO parsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar, cast
from urllib.parse import parse_qsl, urlsplit

import httpx
from pydantic import TypeAdapter, ValidationError

from .allowlist import CAPABILITIES, Capability
from .configuration import Trading212Settings
from .credentials import CredentialProvider
from .errors import (
    CapabilityError,
    MethodNotAllowedError,
    ProviderError,
    ProviderErrorKind,
)
from .models import (
    AccountSummaryDTO,
    DividendDTO,
    ExchangeDTO,
    HistoricalExportDTO,
    HistoricalOrderDTO,
    InstrumentDTO,
    OrderDTO,
    PaginatedDTO,
    PositionDTO,
    ProviderResponse,
    TransactionDTO,
    parse_rate_limit_headers,
)

_LOG = logging.getLogger("trading212_provider")
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_Sleep = Callable[[float], Awaitable[None]]
_Now = Callable[[], datetime]
_T = TypeVar("_T")


class _ReadOnlyRequestBuilder:
    """The only path from a capability to an outbound provider request."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    def build(
        self,
        *,
        method: str,
        capability: Capability,
        authorization: str,
        correlation_id: str,
        query: Mapping[str, str],
        order_id: str | None,
    ) -> httpx.Request:
        if method != "GET":
            raise MethodNotAllowedError()
        path = capability.resolve_path(order_id=order_id)
        return self._client.build_request(
            "GET",
            path,
            params=dict(query),
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "X-Correlation-ID": correlation_id,
                "User-Agent": "trading212-portfolio-intelligence/0.1.0",
            },
        )


class Trading212Client:
    """Typed capability client; it exposes neither arbitrary paths nor generic requests."""

    def __init__(
        self,
        *,
        settings: Trading212Settings,
        credential_provider: CredentialProvider,
        credential_reference: str,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: _Sleep = asyncio.sleep,
        now: _Now | None = None,
        random_source: random.Random | None = None,
    ) -> None:
        if not credential_reference or len(credential_reference) > 512:
            raise ProviderError(
                ProviderErrorKind.CONFIGURATION,
                "a bounded opaque credential reference is required",
            )
        self._settings = settings
        self._credential_provider = credential_provider
        self._credential_reference = credential_reference
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._random: random.Random = random_source or secrets.SystemRandom()
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=settings.connect_timeout_seconds,
                pool=settings.connect_timeout_seconds,
            ),
            follow_redirects=False,
            transport=transport,
        )
        self._request_builder = _ReadOnlyRequestBuilder(self._client)

    async def __aenter__(self) -> Trading212Client:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_account_summary(
        self, *, correlation_id: str | None = None
    ) -> ProviderResponse[AccountSummaryDTO]:
        return await self._read(
            capability_name="account_summary",
            adapter=TypeAdapter(AccountSummaryDTO),
            correlation_id=correlation_id,
        )

    async def get_instruments(
        self, *, correlation_id: str | None = None
    ) -> ProviderResponse[tuple[InstrumentDTO, ...]]:
        return await self._read(
            capability_name="metadata_instruments",
            adapter=TypeAdapter(tuple[InstrumentDTO, ...]),
            correlation_id=correlation_id,
        )

    async def get_exchanges(
        self, *, correlation_id: str | None = None
    ) -> ProviderResponse[tuple[ExchangeDTO, ...]]:
        return await self._read(
            capability_name="metadata_exchanges",
            adapter=TypeAdapter(tuple[ExchangeDTO, ...]),
            correlation_id=correlation_id,
        )

    async def get_positions(
        self,
        *,
        ticker: str | None = None,
        correlation_id: str | None = None,
    ) -> ProviderResponse[tuple[PositionDTO, ...]]:
        return await self._read(
            capability_name="portfolio_positions",
            adapter=TypeAdapter(tuple[PositionDTO, ...]),
            query={"ticker": ticker},
            correlation_id=correlation_id,
        )

    async def get_pending_orders(
        self, *, correlation_id: str | None = None
    ) -> ProviderResponse[tuple[OrderDTO, ...]]:
        return await self._read(
            capability_name="pending_orders",
            adapter=TypeAdapter(tuple[OrderDTO, ...]),
            correlation_id=correlation_id,
        )

    async def get_order(
        self,
        *,
        order_id: str,
        correlation_id: str | None = None,
    ) -> ProviderResponse[OrderDTO]:
        return await self._read(
            capability_name="order_detail",
            adapter=TypeAdapter(OrderDTO),
            order_id=order_id,
            correlation_id=correlation_id,
        )

    async def get_historical_orders_page(
        self,
        *,
        cursor: int | None = None,
        ticker: str | None = None,
        limit: int = 50,
        correlation_id: str | None = None,
    ) -> ProviderResponse[PaginatedDTO[HistoricalOrderDTO]]:
        return await self._read(
            capability_name="historical_orders",
            adapter=TypeAdapter(PaginatedDTO[HistoricalOrderDTO]),
            query={"cursor": cursor, "ticker": ticker, "limit": limit},
            correlation_id=correlation_id,
        )

    async def get_transactions_page(
        self,
        *,
        cursor: str | None = None,
        time: datetime | None = None,
        limit: int = 50,
        correlation_id: str | None = None,
    ) -> ProviderResponse[PaginatedDTO[TransactionDTO]]:
        return await self._read(
            capability_name="historical_transactions",
            adapter=TypeAdapter(PaginatedDTO[TransactionDTO]),
            query={"cursor": cursor, "time": time, "limit": limit},
            correlation_id=correlation_id,
        )

    async def get_dividends_page(
        self,
        *,
        cursor: int | None = None,
        ticker: str | None = None,
        limit: int = 50,
        correlation_id: str | None = None,
    ) -> ProviderResponse[PaginatedDTO[DividendDTO]]:
        return await self._read(
            capability_name="historical_dividends",
            adapter=TypeAdapter(PaginatedDTO[DividendDTO]),
            query={"cursor": cursor, "ticker": ticker, "limit": limit},
            correlation_id=correlation_id,
        )

    async def get_historical_exports(
        self, *, correlation_id: str | None = None
    ) -> ProviderResponse[tuple[HistoricalExportDTO, ...]]:
        """Observe report metadata only; download links are data and are never followed."""
        return await self._read(
            capability_name="historical_exports",
            adapter=TypeAdapter(tuple[HistoricalExportDTO, ...]),
            correlation_id=correlation_id,
        )

    async def iter_historical_orders(
        self, *, ticker: str | None = None, limit: int = 50
    ) -> AsyncIterator[ProviderResponse[PaginatedDTO[HistoricalOrderDTO]]]:
        async for page in self._iter_pages(
            capability_name="historical_orders",
            adapter=TypeAdapter(PaginatedDTO[HistoricalOrderDTO]),
            initial_query={"ticker": ticker, "limit": limit},
        ):
            yield page

    async def iter_transactions(
        self, *, time: datetime | None = None, limit: int = 50
    ) -> AsyncIterator[ProviderResponse[PaginatedDTO[TransactionDTO]]]:
        async for page in self._iter_pages(
            capability_name="historical_transactions",
            adapter=TypeAdapter(PaginatedDTO[TransactionDTO]),
            initial_query={"time": time, "limit": limit},
        ):
            yield page

    async def iter_dividends(
        self, *, ticker: str | None = None, limit: int = 50
    ) -> AsyncIterator[ProviderResponse[PaginatedDTO[DividendDTO]]]:
        async for page in self._iter_pages(
            capability_name="historical_dividends",
            adapter=TypeAdapter(PaginatedDTO[DividendDTO]),
            initial_query={"ticker": ticker, "limit": limit},
        ):
            yield page

    async def _iter_pages(
        self,
        *,
        capability_name: str,
        adapter: TypeAdapter[PaginatedDTO[_T]],
        initial_query: Mapping[str, object],
    ) -> AsyncIterator[ProviderResponse[PaginatedDTO[_T]]]:
        capability = CAPABILITIES[capability_name]
        original = capability.normalize_query(initial_query)
        query = original
        visited: set[str] = set()
        records = 0
        correlation_id = str(uuid.uuid4())
        for _ in range(self._settings.max_pages):
            page = await self._read(
                capability_name=capability_name,
                adapter=adapter,
                query=query,
                correlation_id=correlation_id,
                query_already_validated=True,
            )
            records += len(page.data.items)
            if records > self._settings.max_records:
                raise ProviderError(
                    ProviderErrorKind.PAGINATION,
                    "provider pagination exceeded the configured record bound",
                )
            yield page
            next_path = page.data.next_page_path
            if next_path is None:
                return
            if next_path in visited:
                raise ProviderError(
                    ProviderErrorKind.PAGINATION,
                    "provider pagination loop detected",
                )
            visited.add(next_path)
            query = self._reconstruct_next_query(
                capability=capability,
                next_page_path=next_path,
                original_query=original,
            )
        raise ProviderError(
            ProviderErrorKind.PAGINATION,
            "provider pagination exceeded the configured page bound",
        )

    @staticmethod
    def _reconstruct_next_query(
        *,
        capability: Capability,
        next_page_path: str,
        original_query: Mapping[str, str],
    ) -> dict[str, str]:
        if not next_page_path or len(next_page_path) > 2_048:
            raise ProviderError(ProviderErrorKind.PAGINATION, "invalid next-page reference")
        parsed = urlsplit(next_page_path)
        if parsed.scheme or parsed.netloc or parsed.fragment or parsed.username or parsed.password:
            raise ProviderError(ProviderErrorKind.PAGINATION, "unsafe next-page reference")
        expected_path = capability.resolve_path()
        observed_path = parsed.path
        if observed_path.startswith("/api/v0/"):
            observed_path = observed_path.removeprefix("/api/v0")
        if observed_path != expected_path:
            raise ProviderError(ProviderErrorKind.PAGINATION, "next-page capability changed")
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        names = [name for name, _ in pairs]
        if len(names) != len(set(names)):
            raise ProviderError(ProviderErrorKind.PAGINATION, "duplicate next-page query field")
        try:
            raw: dict[str, object] = dict(pairs)
            if "limit" in raw:
                raw["limit"] = int(cast(str, raw["limit"]))
            if capability.name != "historical_transactions" and "cursor" in raw:
                raw["cursor"] = int(cast(str, raw["cursor"]))
            if "time" in raw:
                raw["time"] = datetime.fromisoformat(cast(str, raw["time"]))
            normalized = capability.normalize_query(raw)
        except (CapabilityError, ValueError) as exc:
            raise ProviderError(
                ProviderErrorKind.PAGINATION,
                "invalid next-page query",
            ) from exc
        for stable_filter in ("ticker", "time"):
            if original_query.get(stable_filter) != normalized.get(stable_filter):
                raise ProviderError(
                    ProviderErrorKind.PAGINATION,
                    "next-page reference changed the original filter",
                )
        return normalized

    async def _read(
        self,
        *,
        capability_name: str,
        adapter: TypeAdapter[_T],
        query: Mapping[str, object] | None = None,
        order_id: str | None = None,
        correlation_id: str | None = None,
        query_already_validated: bool = False,
    ) -> ProviderResponse[_T]:
        capability = CAPABILITIES[capability_name]
        if query_already_validated:
            if query is None or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in query.items()
            ):
                raise ProviderError(
                    ProviderErrorKind.CONFIGURATION,
                    "internal normalized query contract was violated",
                )
            safe_query = cast(dict[str, str], dict(query))
        else:
            safe_query = capability.normalize_query(query)
        safe_correlation_id = correlation_id or str(uuid.uuid4())
        if not _CORRELATION_PATTERN.fullmatch(safe_correlation_id):
            raise ProviderError(ProviderErrorKind.CONFIGURATION, "invalid correlation identifier")
        credentials = await self._credential_provider.resolve_trading212(
            credential_reference=self._credential_reference,
            environment=self._settings.environment,
        )
        if credentials.environment is not self._settings.environment:
            raise ProviderError(
                ProviderErrorKind.AUTHENTICATION,
                "credential environment does not match selected provider environment",
            )
        request = self._request_builder.build(
            method="GET",
            capability=capability,
            authorization=credentials.authorization_header(),
            correlation_id=safe_correlation_id,
            query=safe_query,
            order_id=order_id,
        )
        response = await self._send_with_retry(
            request=request,
            capability_name=capability_name,
            correlation_id=safe_correlation_id,
        )
        content = await response.aread()
        if len(content) > self._settings.max_response_bytes:
            raise ProviderError(ProviderErrorKind.CONTRACT, "provider response exceeded size bound")
        parse_failed = False
        try:
            raw = json.loads(content, parse_float=Decimal, parse_int=int)
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_failed = True
        if parse_failed:
            raise ProviderError(
                ProviderErrorKind.CONTRACT,
                "provider returned malformed JSON",
            )
        validation_failed = False
        try:
            data = adapter.validate_python(raw)
            rate_limit = parse_rate_limit_headers(dict(response.headers))
        except (ValidationError, ValueError):
            validation_failed = True
        if validation_failed:
            # Raising outside the handler prevents URL-bearing validation input
            # from remaining in the public exception cause/context or traceback.
            raise ProviderError(
                ProviderErrorKind.CONTRACT,
                "provider response did not satisfy the pinned semantic contract",
            )
        fingerprint_content = content
        if capability_name == "historical_exports":
            exports = cast(tuple[HistoricalExportDTO, ...], data)
            fingerprint_content = json.dumps(
                [item.retained_metadata() for item in exports],
                default=str,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        return ProviderResponse[_T](
            data=data,
            observed_at=self._now().astimezone(UTC),
            correlation_id=safe_correlation_id,
            status_code=response.status_code,
            rate_limit=rate_limit,
            source_sha256=hashlib.sha256(fingerprint_content).hexdigest(),
        )

    async def _send_with_retry(
        self,
        *,
        request: httpx.Request,
        capability_name: str,
        correlation_id: str,
    ) -> httpx.Response:
        last_error: ProviderError | None = None
        for attempt in range(1, self._settings.max_attempts + 1):
            try:
                response = await self._client.send(request)
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    ProviderErrorKind.TIMEOUT,
                    "Trading 212 read timed out",
                    retryable=True,
                )
                if attempt == self._settings.max_attempts:
                    raise last_error from exc
                await self._sleep(self._backoff(attempt))
                continue
            except httpx.TransportError as exc:
                last_error = ProviderError(
                    ProviderErrorKind.TRANSIENT,
                    "Trading 212 transport failed",
                    retryable=True,
                )
                if attempt == self._settings.max_attempts:
                    raise last_error from exc
                await self._sleep(self._backoff(attempt))
                continue
            _LOG.info(
                "trading212_read_completed",
                extra={
                    "capability": capability_name,
                    "correlation_id": correlation_id,
                    "status_code": response.status_code,
                    "attempt": attempt,
                },
            )
            if 200 <= response.status_code < 300:
                return response
            error = _map_status(response.status_code)
            if (
                response.status_code not in _TRANSIENT_STATUSES
                or attempt == self._settings.max_attempts
            ):
                raise error
            last_error = error
            await self._sleep(_retry_delay(response, self._backoff(attempt), self._now()))
        assert last_error is not None  # pragma: no cover
        raise last_error  # pragma: no cover

    def _backoff(self, attempt: int) -> float:
        maximum = float(self._settings.max_backoff_seconds)
        ceiling = min(maximum, float(2 ** (attempt - 1)))
        jittered: float = ceiling * (0.75 + float(self._random.random()) * 0.5)
        return float(min(maximum, jittered))


def _map_status(status_code: int) -> ProviderError:
    if status_code == 401:
        return ProviderError(
            ProviderErrorKind.AUTHENTICATION,
            "Trading 212 authentication failed",
            status_code=status_code,
        )
    if status_code == 403:
        return ProviderError(
            ProviderErrorKind.AUTHORIZATION,
            "Trading 212 permission or environment check failed",
            status_code=status_code,
        )
    if status_code == 404:
        return ProviderError(
            ProviderErrorKind.NOT_FOUND,
            "Trading 212 record was not found",
            status_code=status_code,
        )
    if status_code == 429:
        return ProviderError(
            ProviderErrorKind.RATE_LIMITED,
            "Trading 212 rate limit was reached",
            retryable=True,
            status_code=status_code,
        )
    if status_code in _TRANSIENT_STATUSES:
        return ProviderError(
            ProviderErrorKind.TRANSIENT,
            "Trading 212 service is temporarily unavailable",
            retryable=True,
            status_code=status_code,
        )
    return ProviderError(
        ProviderErrorKind.PERMANENT,
        "Trading 212 rejected the read request",
        status_code=status_code,
    )


def _retry_delay(response: httpx.Response, fallback: float, now: datetime) -> float:
    header = response.headers.get("retry-after")
    if header is not None:
        try:
            return max(0.0, min(30.0, float(int(header))))
        except ValueError:
            pass
    reset = response.headers.get("x-ratelimit-reset")
    if reset is not None:
        try:
            reset_at = datetime.fromtimestamp(int(reset), tz=UTC)
            return max(0.0, min(30.0, (reset_at - now.astimezone(UTC)).total_seconds()))
        except (OverflowError, OSError, ValueError):
            pass
    return fallback
