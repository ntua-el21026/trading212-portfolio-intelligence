"""Authenticated FastAPI composition root for the complete Phase 1 HTTP surface."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    Query,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response as StarletteResponse
from trading212_application.ingestion import (
    RefreshScope,
    RunMode,
    capabilities_for_scope,
)
from trading212_application.planning import PlanningService, PlanningServiceError
from trading212_application.queries import (
    ActivityQuery,
    ActivityTypeFilter,
    CollectionSnapshotCapacityError,
    CursorValidationError,
    DirectAllocationQuery,
    DividendQuery,
    InstrumentQuery,
    PageQuery,
    PositionQuery,
    PositionSort,
)
from trading212_application.refresh_semantics import RefreshIdempotencyConflictError
from trading212_application.services import (
    PortfolioService,
    RefreshUnavailableError,
)
from trading212_application.sources import SourceService, SourceServiceError
from trading212_application.targets import TargetService, TargetServiceError
from trading212_application.views import Page
from trading212_domain.errors import DomainError
from trading212_observability import (
    AuthenticationMethod,
    OperationalMetrics,
    SecurityAuditAction,
    SecurityAuditEvent,
    SecurityAuditOutcome,
    SecurityAuditSink,
    StructuredLogSecurityAuditSink,
    bind_correlation_id,
    clear_request_context,
    configure_logging,
    configure_tracing,
    opaque_audit_reference,
)
from trading212_persistence import (
    PostgresPortfolioService,
    create_database_engine,
    create_session_factory,
    refresh_dispatcher_is_ready,
)
from trading212_persistence.target_service import PostgresTargetService
from trading212_security.principals import (
    AuthenticationError,
    AuthorizationError,
    Authorizer,
    Principal,
    Scope,
)
from trading212_security.sessions import InMemorySessionStore, SessionManager
from trading212_security.settings import RuntimeEnvironment, SecuritySettings
from trading212_security.tokens import BearerAuthenticator, LocalSyntheticAuthenticator

from .planning_routes import register_planning_routes
from .refresh_queue import PostgresRefreshQueue
from .schemas import (
    AccountResponse,
    AccountSummaryResponse,
    ActivityResponse,
    BrokerConnectionResponse,
    DataQualitySummaryResponse,
    DirectAllocationResponse,
    DividendResponse,
    ErrorBody,
    ErrorEnvelope,
    HealthResponse,
    InstrumentResponse,
    LocalSessionResponse,
    OrderResponse,
    PageResponse,
    PerformanceSummaryResponse,
    PositionResponse,
    PrincipalResponse,
    ReconciliationIssueResponse,
    ReconciliationResponse,
    RefreshRequest,
    RefreshRunResponse,
    SnapshotComparisonResponse,
    SnapshotDetailResponse,
    SnapshotResponse,
)
from .source_routes import register_source_routes
from .target_routes import register_target_routes

SESSION_COOKIE = "t212pi_session"
CORRELATION_HEADER = "X-Correlation-ID"
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_LOCAL_DATABASE_URL = "postgresql+psycopg://portfolio:portfolio@127.0.0.1:5432/portfolio"
_LOCAL_CURSOR_SIGNING_KEY = hashlib.sha256(
    b"trading212-portfolio-intelligence/local-cursor-signing-key/v1"
).digest()
CursorParameter = Annotated[
    str | None,
    Query(max_length=2048, pattern=r"^[A-Za-z0-9_-]+$"),
]


async def _ready() -> bool:
    return True


@dataclass(slots=True)
class ApiContext:
    settings: SecuritySettings
    service: PortfolioService
    target_service: TargetService | None
    planning_service: PlanningService | None
    source_service: SourceService | None
    sessions: SessionManager
    local_authenticator: LocalSyntheticAuthenticator | None
    bearer_authenticator: BearerAuthenticator | None
    clock: Callable[[], datetime]
    readiness_probe: Callable[[], Awaitable[bool]]
    metrics: OperationalMetrics
    audit_sink: SecurityAuditSink


def create_app(
    *,
    settings: SecuritySettings | None = None,
    service: PortfolioService | None = None,
    target_service: TargetService | None = None,
    planning_service: PlanningService | None = None,
    source_service: SourceService | None = None,
    session_manager: SessionManager | None = None,
    bearer_authenticator: BearerAuthenticator | None = None,
    clock: Callable[[], datetime] | None = None,
    readiness_probe: Callable[[], Awaitable[bool]] | None = None,
    audit_sink: SecurityAuditSink | None = None,
    cursor_signing_key: bytes | None = None,
) -> FastAPI:
    runtime_clock = clock or (lambda: datetime.now(UTC))
    security_settings = settings or SecuritySettings()
    deployed = security_settings.environment in {
        RuntimeEnvironment.STAGING,
        RuntimeEnvironment.PRODUCTION,
    }
    if deployed and (
        service is None
        or session_manager is None
        or bearer_authenticator is None
        or readiness_probe is None
    ):
        raise ValueError(
            "deployed API requires explicit service, durable session manager, "
            "bearer authenticator, and dispatcher-aware readiness probe"
        )
    if service is None:
        portfolio_service, default_targets, default_planning, default_sources, default_readiness = (
            _local_runtime_defaults(
                security_settings,
                runtime_clock,
                cursor_signing_key=cursor_signing_key,
            )
        )
        target_service = target_service or default_targets
        planning_service = planning_service or default_planning
        source_service = source_service or default_sources
    else:
        portfolio_service = service
        default_readiness = _ready
    sessions = session_manager or SessionManager(
        store=InMemorySessionStore(),
        signing_key=secrets.token_bytes(32),
        clock=runtime_clock,
    )
    local_authenticator = (
        LocalSyntheticAuthenticator(security_settings, clock=runtime_clock)
        if security_settings.local_synthetic_auth_enabled
        else None
    )
    context = ApiContext(
        settings=security_settings,
        service=portfolio_service,
        target_service=target_service,
        planning_service=planning_service,
        source_service=source_service,
        sessions=sessions,
        local_authenticator=local_authenticator,
        bearer_authenticator=bearer_authenticator,
        clock=runtime_clock,
        readiness_probe=readiness_probe or default_readiness,
        metrics=OperationalMetrics(service="api"),
        audit_sink=audit_sink or StructuredLogSecurityAuditSink(),
    )
    application = FastAPI(
        title="Trading 212 Portfolio Intelligence API",
        description=(
            "Private portfolio analytics and internal planning; Trading 212 access is read-only."
        ),
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    application.state.context = context
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(security_settings.allowed_hosts),
    )
    if security_settings.allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(security_settings.allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                CORRELATION_HEADER,
                "X-CSRF-Token",
                "X-Idempotency-Key",
                "If-Match",
                "If-None-Match",
            ],
            expose_headers=["ETag", CORRELATION_HEADER],
        )
    _register_error_handlers(application)
    _register_middleware(application)
    _register_routes(application)
    register_target_routes(application, _principal, _context)
    register_planning_routes(application, _principal, _context)
    register_source_routes(application, _principal, _context)
    _install_openapi_contract(application)
    return application


def _local_runtime_defaults(
    settings: SecuritySettings,
    clock: Callable[[], datetime],
    *,
    cursor_signing_key: bytes | None,
) -> tuple[
    PortfolioService, TargetService, PlanningService, SourceService, Callable[[], Awaitable[bool]]
]:
    from trading212_persistence.planning_service import PostgresPlanningService
    from trading212_persistence.source_service import PostgresSourceService

    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        database_url = _LOCAL_DATABASE_URL
    if not database_url:
        raise ValueError("DATABASE_URL must be configured")
    if settings.environment not in {RuntimeEnvironment.LOCAL, RuntimeEnvironment.TEST}:
        raise ValueError("implicit PostgreSQL runtime is restricted to local/test")
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    queue = PostgresRefreshQueue(sessions=sessions, clock=clock)

    async def database_readiness() -> bool:
        try:
            with engine.connect() as connection:
                value = cast(int | None, connection.scalar(sql_text("SELECT 1")))
                if value != 1 or not settings.outbox_dispatcher_configured:
                    return False
            return refresh_dispatcher_is_ready(
                sessions,
                now=clock(),
                max_age=timedelta(seconds=settings.dispatcher_heartbeat_max_age_seconds),
            )
        except Exception:
            return False

    return (
        PostgresPortfolioService(
            sessions=sessions,
            clock=clock,
            refresh_queue=queue,
            cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
            cursor_ttl_seconds=settings.cursor_ttl_seconds,
        ),
        PostgresTargetService(
            sessions=sessions,
            clock=clock,
            cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
            cursor_ttl_seconds=settings.cursor_ttl_seconds,
        ),
        PostgresPlanningService(
            sessions=sessions,
            clock=clock,
            cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
            cursor_ttl_seconds=settings.cursor_ttl_seconds,
        ),
        PostgresSourceService(
            sessions=sessions,
            clock=clock,
            cursor_signing_key=cursor_signing_key or _LOCAL_CURSOR_SIGNING_KEY,
            cursor_ttl_seconds=settings.cursor_ttl_seconds,
        ),
        database_readiness,
    )


def _install_openapi_contract(application: FastAPI) -> None:
    """Document both supported client authentication mechanisms explicitly."""

    def openapi_schema() -> dict[str, Any]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        components = schema.setdefault("components", {})
        schemes = components.setdefault("securitySchemes", {})
        schemes.update(
            {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "Validated external identity-provider access token.",
                },
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": SESSION_COOKIE,
                    "description": "Opaque, signed, revocable server-side browser session.",
                },
            }
        )
        for path, path_item in schema.get("paths", {}).items():
            if path == "/api/v1/auth/local-session":
                continue
            if not path.startswith("/api/v1/"):
                continue
            security: list[dict[str, list[str]]] = (
                [{"sessionCookie": []}]
                if path == "/api/v1/auth/logout"
                else [{"bearerAuth": []}, {"sessionCookie": []}]
            )
            for method, operation in path_item.items():
                if method in {"get", "post", "put", "patch", "delete"}:
                    operation["security"] = security
        application.openapi_schema = schema
        return schema

    application.openapi = openapi_schema  # type: ignore[method-assign]


def _context(request: Request) -> ApiContext:
    return cast(ApiContext, request.app.state.context)


async def _principal(request: Request) -> Principal:
    context = _context(request)
    authorization = request.headers.get("authorization")
    if authorization is not None:
        request.state.authentication_method = AuthenticationMethod.BEARER
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token:
            raise AuthenticationError("invalid bearer credential")
        if context.bearer_authenticator is None:
            raise AuthenticationError("bearer authentication is unavailable")
        principal = await context.bearer_authenticator.authenticate(token)
        request.state.principal = principal
        return principal
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is None:
        request.state.authentication_method = AuthenticationMethod.NONE
        raise AuthenticationError("authentication required")
    request.state.authentication_method = AuthenticationMethod.SESSION
    principal = await context.sessions.authenticate(cookie)
    request.state.principal = principal
    return principal


PrincipalDependency = Annotated[Principal, Depends(_principal)]


def _safe_operation(request: Request) -> str:
    route = request.scope.get("route")
    operation = getattr(route, "name", "unmatched")
    if not isinstance(operation, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", operation):
        return "unmatched"
    return operation


def _authentication_method(request: Request) -> AuthenticationMethod:
    value = getattr(request.state, "authentication_method", AuthenticationMethod.NONE)
    return value if isinstance(value, AuthenticationMethod) else AuthenticationMethod.NONE


async def _record_security_audit(
    request: Request,
    *,
    action: SecurityAuditAction,
    outcome: SecurityAuditOutcome,
    principal: Principal | None = None,
) -> None:
    context = _context(request)
    actor = principal or getattr(request.state, "principal", None)
    event = SecurityAuditEvent(
        event_id=str(uuid.uuid4()),
        action=action,
        outcome=outcome,
        occurred_at=context.clock(),
        correlation_id=getattr(request.state, "correlation_id", str(uuid.uuid4())),
        operation=_safe_operation(request),
        authentication_method=_authentication_method(request),
        actor_ref=(
            opaque_audit_reference(actor.principal_id) if isinstance(actor, Principal) else None
        ),
        owner_ref=(
            opaque_audit_reference(actor.owner_id) if isinstance(actor, Principal) else None
        ),
    )
    try:
        await context.audit_sink.record(event)
    except Exception:
        # Audit transport failure must never convert an access denial into access.
        logging.getLogger("trading212_api.security_audit").error(
            "security_audit_delivery_failed action=%s correlation_id=%s",
            event.action.value,
            event.correlation_id,
        )


def _register_middleware(application: FastAPI) -> None:
    @application.middleware("http")
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        supplied = request.headers.get(CORRELATION_HEADER)
        correlation_id = (
            supplied
            if supplied is not None and _CORRELATION_PATTERN.fullmatch(supplied)
            else str(uuid.uuid4())
        )
        request.state.correlation_id = correlation_id
        bind_correlation_id(correlation_id)
        started = time.perf_counter()
        outcome = "error"
        try:
            response = await call_next(request)
            outcome = "success" if response.status_code < 500 else "error"
            response.headers[CORRELATION_HEADER] = correlation_id
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        finally:
            operation = _safe_operation(request)
            context = _context(request)
            context.metrics.requests.labels(operation=operation, outcome=outcome).inc()
            context.metrics.duration.labels(operation=operation).observe(
                time.perf_counter() - started
            )
            clear_request_context()


def _register_error_handlers(application: FastAPI) -> None:
    def envelope(
        request: Request,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return ErrorEnvelope(
            error=ErrorBody(
                code=code,
                message=message,
                correlation_id=getattr(request.state, "correlation_id", str(uuid.uuid4())),
                retryable=retryable,
            )
        ).model_dump(mode="json")

    @application.exception_handler(AuthenticationError)
    async def authentication_error(request: Request, _: AuthenticationError) -> JSONResponse:
        await _record_security_audit(
            request,
            action=SecurityAuditAction.AUTHENTICATION_DENIED,
            outcome=SecurityAuditOutcome.DENIED,
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=envelope(request, "AUTHENTICATION_REQUIRED", "Authentication is required."),
            headers={"WWW-Authenticate": "Bearer"},
        )

    @application.exception_handler(AuthorizationError)
    async def authorization_error(request: Request, _: AuthorizationError) -> JSONResponse:
        await _record_security_audit(
            request,
            action=SecurityAuditAction.AUTHORIZATION_DENIED,
            outcome=SecurityAuditOutcome.DENIED,
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=envelope(request, "ACCESS_DENIED", "Access denied."),
        )

    @application.exception_handler(LookupError)
    async def not_found(request: Request, _: LookupError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=envelope(request, "NOT_FOUND", "The requested resource was not found."),
        )

    @application.exception_handler(CursorValidationError)
    async def invalid_cursor(request: Request, _: CursorValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=envelope(request, "CURSOR_INVALID", "The pagination cursor is invalid."),
        )

    @application.exception_handler(CollectionSnapshotCapacityError)
    async def collection_snapshot_capacity(
        request: Request, _: CollectionSnapshotCapacityError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=envelope(
                request,
                CollectionSnapshotCapacityError.code,
                "Active pagination capacity is temporarily exhausted.",
                retryable=True,
            ),
        )

    @application.exception_handler(RefreshIdempotencyConflictError)
    async def refresh_conflict(
        request: Request, _: RefreshIdempotencyConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=envelope(
                request,
                "IDEMPOTENCY_KEY_REUSED",
                "The idempotency key is already bound to a different refresh request.",
            ),
        )

    @application.exception_handler(ValueError)
    async def validation_error(request: Request, _: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=envelope(request, "VALIDATION_FAILED", "The request is invalid."),
        )

    @application.exception_handler(TargetServiceError)
    async def target_service_error(request: Request, exc: TargetServiceError) -> JSONResponse:
        errors = {
            "NOT_FOUND": (404, "The requested resource was not found."),
            "ACCESS_DENIED": (403, "Access denied."),
            "IDEMPOTENCY_KEY_REUSED": (409, "The idempotency key belongs to a different command."),
            "IMMUTABLE_VERSION": (
                409,
                "Published target content is immutable; create a new draft.",
            ),
            "INVALID_STATE_TRANSITION": (409, "This target lifecycle transition is unavailable."),
            "REVISION_MISMATCH": (412, "The revision changed. Reload before submitting again."),
            "REVISION_REQUIRED": (428, "The current aggregate revision is required."),
            "VALIDATION_FAILED": (422, "The target request is invalid."),
            "TARGET_VALIDATION_FAILED": (
                422,
                "Validate the current target content before publishing.",
            ),
            "CURRENCY_MISMATCH": (422, "The target currency does not match the account."),
            "RESULT_TOO_LARGE": (413, "The target result exceeds its permitted size."),
            "TARGETS_UNAVAILABLE": (503, "The target service is unavailable."),
        }
        code = exc.code.value
        response_status, message = errors.get(code, (500, "The target command could not complete."))
        return JSONResponse(
            status_code=response_status,
            content=envelope(request, code, message, retryable=response_status == 503),
            headers={"Cache-Control": "private, no-store"},
        )

    @application.exception_handler(PlanningServiceError)
    async def planning_service_error(request: Request, exc: PlanningServiceError) -> JSONResponse:
        errors = {
            "NOT_FOUND": (404, "The requested planning resource was not found."),
            "ACCESS_DENIED": (403, "Access denied."),
            "IDEMPOTENCY_KEY_REUSED": (409, "The idempotency key belongs to a different command."),
            "IMMUTABLE_VERSION": (
                409,
                "Finalized plans are immutable; recalculate a new revision.",
            ),
            "INVALID_STATE_TRANSITION": (409, "This planning lifecycle transition is unavailable."),
            "REVISION_MISMATCH": (412, "The revision changed. Reload before submitting again."),
            "REVISION_REQUIRED": (428, "The current plan revision is required."),
            "VALIDATION_FAILED": (422, "The planning request is invalid."),
            "CURRENCY_MISMATCH": (422, "The contribution currency does not match its inputs."),
            "RESULT_TOO_LARGE": (422, "The planning result exceeds its permitted size."),
            "PLANNING_UNAVAILABLE": (503, "The planning service is unavailable."),
        }
        code = exc.code.value
        response_status, message = errors.get(
            code, (500, "The planning operation could not complete.")
        )
        return JSONResponse(
            status_code=response_status,
            content=envelope(request, code, message, retryable=response_status == 503),
            headers={"Cache-Control": "private, no-store"},
        )

    @application.exception_handler(SourceServiceError)
    async def source_service_error(request: Request, exc: SourceServiceError) -> JSONResponse:
        errors = {
            "NOT_FOUND": (404, "The requested reference resource was not found."),
            "ACCESS_DENIED": (403, "Access to this reference source is denied."),
            "VALIDATION_FAILED": (422, "The reference source request is invalid."),
            "CURRENCY_MISMATCH": (422, "The benchmark reporting currency does not match."),
            "IMMUTABLE_VERSION": (409, "Published benchmarks are immutable; create a new version."),
            "IDEMPOTENCY_KEY_REUSED": (409, "The idempotency key belongs to a different command."),
            "REVISION_REQUIRED": (428, "The current benchmark revision is required."),
            "REVISION_MISMATCH": (412, "The revision changed. Reload before submitting again."),
            "INVALID_STATE_TRANSITION": (
                409,
                "This benchmark lifecycle transition is unavailable.",
            ),
            "SOURCE_REVISION_CONFLICT": (
                409,
                "The source revision conflicts with retained evidence.",
            ),
            "RESULT_TOO_LARGE": (422, "The source result exceeds its permitted size."),
            "PROVIDER_UNAVAILABLE": (503, "The reference source service is unavailable."),
        }
        code = exc.code.value
        response_status, message = errors.get(
            code, (500, "The source operation could not complete.")
        )
        return JSONResponse(
            status_code=response_status,
            content=envelope(request, code, message, retryable=response_status == 503),
            headers={"Cache-Control": "private, no-store"},
        )

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, _: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=envelope(request, "VALIDATION_FAILED", "The request is invalid."),
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if any(tuple(error.get("loc", ())) == ("query", "cursor") for error in exc.errors()):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=envelope(request, "CURSOR_INVALID", "The pagination cursor is invalid."),
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=envelope(request, "VALIDATION_FAILED", "The request is invalid."),
        )

    @application.exception_handler(RefreshUnavailableError)
    async def refresh_unavailable(request: Request, _: RefreshUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=envelope(
                request,
                "REFRESH_UNAVAILABLE",
                "The refresh service is temporarily unavailable.",
                retryable=True,
            ),
        )


def _page[ViewT, ResponseT](
    page: Page[ViewT], converter: Callable[[ViewT], ResponseT]
) -> PageResponse[ResponseT]:
    return PageResponse[ResponseT](
        items=[converter(item) for item in page.items],
        next_cursor=page.next_cursor,
        limit=page.limit,
        total=page.total,
    )


async def _single_authorized_account_id(
    service: PortfolioService,
    principal: Principal,
) -> str:
    accounts = await service.list_accounts(principal)
    if not accounts:
        raise LookupError("account not found")
    if len(accounts) != 1:
        raise ValueError("an explicit account-scoped instrument route is required")
    return accounts[0].id


def _register_routes(application: FastAPI) -> None:
    @application.get("/health/live", response_model=HealthResponse, include_in_schema=False)
    async def liveness() -> HealthResponse:
        return HealthResponse(service="api", status="ok")

    @application.get("/health/ready", response_model=HealthResponse, include_in_schema=False)
    async def readiness(request: Request) -> HealthResponse | JSONResponse:
        context = _context(request)
        if not await context.readiness_probe():
            context.metrics.readiness.set(0)
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"service": "api", "status": "unavailable"},
            )
        context.metrics.readiness.set(1)
        return HealthResponse(service="api", status="ready")

    @application.get("/internal/metrics", include_in_schema=False)
    async def metrics(request: Request, principal: PrincipalDependency) -> StarletteResponse:
        context = _context(request)
        Authorizer().require_scope(principal, Scope.CONFIGURATION_READ, now=context.clock())
        return StarletteResponse(
            content=context.metrics.render(),
            headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
        )

    @application.post(
        "/api/v1/auth/local-session",
        response_model=LocalSessionResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["authentication"],
    )
    async def create_local_session(request: Request, response: Response) -> LocalSessionResponse:
        context = _context(request)
        request.state.authentication_method = AuthenticationMethod.LOCAL_SYNTHETIC
        if context.local_authenticator is None:
            await _record_security_audit(
                request,
                action=SecurityAuditAction.AUTHENTICATION_DENIED,
                outcome=SecurityAuditOutcome.DENIED,
            )
            raise LookupError("local authentication is unavailable")
        principal = await context.local_authenticator.authenticate("")
        request.state.principal = principal
        grant = await context.sessions.create(principal)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=grant.cookie_value,
            max_age=context.settings.session_ttl_seconds,
            expires=grant.expires_at,
            secure=context.settings.cookie_secure,
            httponly=context.settings.cookie_http_only,
            samesite=cast(Literal["lax", "strict", "none"], context.settings.cookie_same_site),
            path="/",
        )
        await _record_security_audit(
            request,
            action=SecurityAuditAction.LOCAL_SESSION_CREATED,
            outcome=SecurityAuditOutcome.SUCCEEDED,
            principal=principal,
        )
        return LocalSessionResponse(
            principal=_principal_response(principal),
            csrf_token=grant.csrf_token,
            expires_at=grant.expires_at,
        )

    @application.post(
        "/api/v1/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["authentication"],
    )
    async def logout(
        request: Request,
        response: Response,
        principal: PrincipalDependency,
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
        session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> None:
        context = _context(request)
        if session_cookie is None or csrf_token is None:
            raise AuthenticationError("invalid CSRF token")
        await context.sessions.validate_csrf(session_cookie, csrf_token)
        await context.sessions.revoke(session_cookie)
        await _record_security_audit(
            request,
            action=SecurityAuditAction.SESSION_REVOKED,
            outcome=SecurityAuditOutcome.SUCCEEDED,
            principal=principal,
        )
        response.delete_cookie(SESSION_COOKIE, path="/")

    @application.get("/api/v1/me", response_model=PrincipalResponse, tags=["authentication"])
    async def me(principal: PrincipalDependency) -> PrincipalResponse:
        return _principal_response(principal)

    @application.get(
        "/api/v1/broker-connections",
        response_model=list[BrokerConnectionResponse],
        tags=["connections"],
    )
    async def list_connections(
        request: Request, principal: PrincipalDependency
    ) -> list[BrokerConnectionResponse]:
        values = await _context(request).service.list_broker_connections(principal)
        return [BrokerConnectionResponse.from_view(value) for value in values]

    @application.get(
        "/api/v1/accounts",
        response_model=list[AccountResponse],
        tags=["accounts"],
    )
    async def list_accounts(
        request: Request, principal: PrincipalDependency
    ) -> list[AccountResponse]:
        accounts = await _context(request).service.list_accounts(principal)
        return [AccountResponse.from_view(account) for account in accounts]

    @application.get(
        "/api/v1/accounts/{account_id}",
        response_model=AccountResponse,
        tags=["accounts"],
    )
    async def get_account(
        account_id: str, request: Request, principal: PrincipalDependency
    ) -> AccountResponse:
        return AccountResponse.from_view(
            await _context(request).service.get_account(principal, account_id)
        )

    @application.post(
        "/api/v1/accounts/{account_id}/refresh",
        response_model=RefreshRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["synchronization"],
    )
    async def refresh_account(
        account_id: str,
        body: RefreshRequest,
        request: Request,
        principal: PrincipalDependency,
        idempotency_key: Annotated[
            str, Header(alias="X-Idempotency-Key", min_length=1, max_length=180)
        ],
        csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
        session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    ) -> RefreshRunResponse:
        context = _context(request)
        if getattr(request.state, "authentication_method", None) is AuthenticationMethod.SESSION:
            if session_cookie is None or csrf_token is None:
                raise AuthenticationError("invalid CSRF token")
            await context.sessions.validate_csrf(session_cookie, csrf_token)
        run = await context.service.refresh(
            principal,
            account_id,
            mode=RunMode(body.mode),
            capabilities=capabilities_for_scope(RefreshScope(body.scope)),
            idempotency_key=idempotency_key,
            correlation_id=request.state.correlation_id,
        )
        return RefreshRunResponse.from_view(run)

    @application.get(
        "/api/v1/refresh-runs/{run_id}",
        response_model=RefreshRunResponse,
        tags=["synchronization"],
    )
    async def get_refresh_run(
        run_id: str, request: Request, principal: PrincipalDependency
    ) -> RefreshRunResponse:
        run = await _context(request).service.get_refresh(principal, run_id)
        return RefreshRunResponse.from_view(run)

    @application.get(
        "/api/v1/accounts/{account_id}/summary",
        response_model=AccountSummaryResponse,
        tags=["portfolio"],
    )
    async def account_summary(
        account_id: str, request: Request, principal: PrincipalDependency
    ) -> AccountSummaryResponse:
        return AccountSummaryResponse.from_view(
            await _context(request).service.get_summary(principal, account_id)
        )

    @application.get(
        "/api/v1/accounts/{account_id}/positions",
        response_model=PageResponse[PositionResponse],
        tags=["portfolio"],
    )
    async def positions(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        sort: PositionSort = PositionSort.MARKET_VALUE_DESC,
        search: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    ) -> PageResponse[PositionResponse]:
        page = await _context(request).service.list_positions(
            principal,
            account_id,
            query=PositionQuery(cursor=cursor, limit=limit, sort=sort, search=search),
        )
        return _page(page, PositionResponse.from_view)

    @application.get(
        "/api/v1/accounts/{account_id}/positions/{position_id}",
        response_model=PositionResponse,
        tags=["portfolio"],
    )
    async def position(
        account_id: str,
        position_id: str,
        request: Request,
        principal: PrincipalDependency,
    ) -> PositionResponse:
        return PositionResponse.from_view(
            await _context(request).service.get_position(principal, account_id, position_id)
        )

    @application.get(
        "/api/v1/accounts/{account_id}/transactions",
        response_model=PageResponse[ActivityResponse],
        tags=["activity"],
    )
    async def transactions(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        start_date: date | None = None,
        end_date: date | None = None,
        activity_type: ActivityTypeFilter = ActivityTypeFilter.ALL,
    ) -> PageResponse[ActivityResponse]:
        page = await _context(request).service.list_activity(
            principal,
            account_id,
            query=ActivityQuery(
                cursor=cursor,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
                activity_type=activity_type,
            ),
        )
        return _page(page, ActivityResponse.from_view)

    @application.get(
        "/api/v1/accounts/{account_id}/dividends",
        response_model=PageResponse[DividendResponse],
        tags=["activity"],
    )
    async def dividends(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> PageResponse[DividendResponse]:
        page = await _context(request).service.list_dividends(
            principal,
            account_id,
            query=DividendQuery(
                cursor=cursor,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            ),
        )
        return _page(page, DividendResponse.from_view)

    @application.get(
        "/api/v1/accounts/{account_id}/orders",
        response_model=PageResponse[OrderResponse],
        tags=["activity"],
    )
    async def orders(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> PageResponse[OrderResponse]:
        page = await _context(request).service.list_orders(
            principal, account_id, query=PageQuery(cursor=cursor, limit=limit)
        )
        return _page(page, OrderResponse.from_view)

    @application.get(
        "/api/v1/accounts/{account_id}/snapshots",
        response_model=PageResponse[SnapshotResponse],
        tags=["snapshots"],
    )
    async def snapshots(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> PageResponse[SnapshotResponse]:
        page = await _context(request).service.list_snapshots(
            principal, account_id, query=PageQuery(cursor=cursor, limit=limit)
        )
        return _page(page, SnapshotResponse.from_view)

    @application.get(
        "/api/v1/accounts/{account_id}/snapshots/latest",
        response_model=SnapshotDetailResponse,
        tags=["snapshots"],
    )
    async def latest_snapshot(
        account_id: str, request: Request, principal: PrincipalDependency
    ) -> SnapshotDetailResponse:
        page = await _context(request).service.list_snapshots(
            principal, account_id, query=PageQuery(limit=1)
        )
        if not page.items:
            raise LookupError("snapshot not found")
        detail = await _context(request).service.get_snapshot_detail(
            principal, account_id, page.items[0].id
        )
        return SnapshotDetailResponse.from_detail(detail)

    @application.get(
        "/api/v1/accounts/{account_id}/snapshots/compare",
        response_model=SnapshotComparisonResponse,
        tags=["snapshots"],
    )
    async def compare_snapshots(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        start_id: Annotated[str, Query(min_length=1, max_length=255)],
        end_id: Annotated[str, Query(min_length=1, max_length=255)],
    ) -> SnapshotComparisonResponse:
        comparison = await _context(request).service.compare_snapshots(
            principal, account_id, start_id, end_id
        )
        return SnapshotComparisonResponse.from_view(comparison)

    @application.get(
        "/api/v1/accounts/{account_id}/snapshots/{snapshot_id}",
        response_model=SnapshotDetailResponse,
        tags=["snapshots"],
    )
    async def snapshot(
        account_id: str,
        snapshot_id: str,
        request: Request,
        principal: PrincipalDependency,
    ) -> SnapshotDetailResponse:
        return SnapshotDetailResponse.from_detail(
            await _context(request).service.get_snapshot_detail(principal, account_id, snapshot_id)
        )

    @application.get(
        "/api/v1/accounts/{account_id}/allocation",
        response_model=DirectAllocationResponse,
        tags=["portfolio"],
    )
    async def allocation(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        limit: Annotated[int, Query(ge=1, le=50)] = 50,
    ) -> DirectAllocationResponse:
        value = await _context(request).service.get_direct_allocation(
            principal,
            account_id,
            query=DirectAllocationQuery(top_n=limit),
        )
        return DirectAllocationResponse.from_view(value, limit=limit)

    @application.get(
        "/api/v1/accounts/{account_id}/performance/summary",
        response_model=PerformanceSummaryResponse,
        tags=["portfolio"],
    )
    async def performance_summary(
        account_id: str, request: Request, principal: PrincipalDependency
    ) -> PerformanceSummaryResponse:
        return PerformanceSummaryResponse.from_view(
            await _context(request).service.get_core_performance_summary(principal, account_id)
        )

    @application.get(
        "/api/v1/accounts/{account_id}/reconciliation",
        response_model=ReconciliationResponse,
        tags=["quality"],
    )
    async def reconciliation(
        account_id: str, request: Request, principal: PrincipalDependency
    ) -> ReconciliationResponse:
        value = await _context(request).service.get_reconciliation(principal, account_id)
        return ReconciliationResponse.from_view(value)

    @application.get(
        "/api/v1/accounts/{account_id}/reconciliation/discrepancies",
        response_model=PageResponse[ReconciliationIssueResponse],
        tags=["quality"],
    )
    async def discrepancies(
        account_id: str,
        request: Request,
        principal: PrincipalDependency,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> PageResponse[ReconciliationIssueResponse]:
        page = await _context(request).service.list_reconciliation_discrepancies(
            principal, account_id, query=PageQuery(cursor=cursor, limit=limit)
        )
        return _page(page, ReconciliationIssueResponse.from_view)

    @application.get(
        "/api/v1/accounts/{account_id}/data-quality",
        response_model=DataQualitySummaryResponse,
        tags=["quality"],
    )
    async def data_quality(
        account_id: str, request: Request, principal: PrincipalDependency
    ) -> DataQualitySummaryResponse:
        value = await _context(request).service.get_data_quality_summary(principal, account_id)
        return DataQualitySummaryResponse.from_view(value)

    @application.get(
        "/api/v1/instruments",
        response_model=PageResponse[InstrumentResponse],
        tags=["instruments"],
    )
    async def instruments(
        request: Request,
        principal: PrincipalDependency,
        query: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
        cursor: CursorParameter = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> PageResponse[InstrumentResponse]:
        page = await _context(request).service.search_instruments(
            principal,
            query=InstrumentQuery(cursor=cursor, limit=limit, search=query),
        )
        return _page(page, InstrumentResponse.from_view)

    @application.get(
        "/api/v1/instruments/{instrument_id}",
        response_model=InstrumentResponse,
        tags=["instruments"],
    )
    async def instrument(
        instrument_id: str, request: Request, principal: PrincipalDependency
    ) -> InstrumentResponse:
        return InstrumentResponse.from_view(
            await _context(request).service.get_instrument(principal, instrument_id)
        )


def _principal_response(principal: Principal) -> PrincipalResponse:
    return PrincipalResponse(
        principal_id=principal.principal_id,
        owner_id=principal.owner_id,
        scopes=sorted(scope.value for scope in principal.scopes),
    )


def create_runtime_app() -> FastAPI:
    """Compose the process app with local JSON telemetry and no implicit exporter."""

    canary = os.environ.get("PHASE1_SECRET_CANARY")
    configure_logging(service="trading212-api", secret_canaries=(canary,) if canary else ())
    configure_tracing(service="trading212-api")
    return create_app()


app = create_runtime_app()
