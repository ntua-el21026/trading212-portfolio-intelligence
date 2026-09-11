"""Closed canonical capture registry and owner/account-scoped rule reference checks."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import alerts as app
from trading212_application.activity_revisions import ActivityRevisionError
from trading212_application.historical import HistoricalServiceError
from trading212_application.planning import PlanningServiceError
from trading212_application.sources import SourceServiceError
from trading212_application.xray import XrayServiceError
from trading212_domain import alerts as d
from trading212_domain.alert_serialization import encode_alert_input
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.values import require_utc
from trading212_security.principals import AuthorizationError

from .alert_authorization import AlertAuthorization
from .alert_capture_common import AlertCaptureBound, AlertCaptureState, AlertCaptureUnavailable
from .alert_models import AlertRuleEventModel, NotificationDestinationModel
from .historical_models import HistoricalInputModel, HistoricalPolicyModel, HistoricalRunModel
from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    InstrumentModel,
    ListingModel,
    PortfolioSnapshotModel,
    SnapshotPositionModel,
)
from .source_models import (
    FxSnapshotModel,
    MarketDataProviderModel,
    PriceSnapshotModel,
    SourceCalendarModel,
)
from .source_service import PostgresSourceService
from .target_models import (
    TargetHoldingModel,
    TargetNodeModel,
    TargetVersionModel,
    VirtualPortfolioModel,
)
from .xray_catalog_models import (
    ClassificationSnapshotModel,
    ConstituentSnapshotModel,
    EconomicEntityModel,
    FundDefinitionModel,
    XrayPolicyVersionModel,
)


def _missing() -> None:
    raise app.AlertServiceError(app.AlertServiceErrorCode.NOT_FOUND)


def validate_alert_references(
    session: Session,
    authorization: AlertAuthorization,
    definition: d.AlertRuleDefinition,
    *,
    now: datetime,
) -> None:
    """Validate IDs on every write/admission without accepting caller-selected relations."""
    authorization.check(session, now=now)
    owner, account, predicate = (
        authorization.owner_id,
        authorization.account_id,
        definition.predicate,
    )
    if predicate.target_version_id is not None:
        version = session.scalar(
            select(TargetVersionModel)
            .join(
                VirtualPortfolioModel,
                VirtualPortfolioModel.id == TargetVersionModel.virtual_portfolio_id,
            )
            .where(
                TargetVersionModel.id == predicate.target_version_id,
                TargetVersionModel.owner_id == owner,
                VirtualPortfolioModel.owner_id == owner,
                VirtualPortfolioModel.broker_account_id == account,
                TargetVersionModel.published_at <= now,
            )
        )
        if version is None:
            _missing()
        if (
            predicate.group_node_id is not None
            and session.scalar(
                select(TargetNodeModel.id).where(
                    TargetNodeModel.id == predicate.group_node_id,
                    TargetNodeModel.owner_id == owner,
                    TargetNodeModel.target_version_id == predicate.target_version_id,
                    TargetNodeModel.kind == "group",
                )
            )
            is None
        ):
            _missing()
        if (
            predicate.holding_id is not None
            and session.scalar(
                select(TargetHoldingModel.id).where(
                    TargetHoldingModel.id == predicate.holding_id,
                    TargetHoldingModel.owner_id == owner,
                    TargetHoldingModel.target_version_id == predicate.target_version_id,
                )
            )
            is None
        ):
            _missing()
    if (
        predicate.entity_id is not None
        and session.scalar(
            select(EconomicEntityModel.id).where(
                EconomicEntityModel.id == predicate.entity_id, EconomicEntityModel.owner_id == owner
            )
        )
        is None
    ):
        _missing()
    for identifier in (predicate.left_fund_id, predicate.right_fund_id):
        if identifier is None:
            continue
        if (
            session.scalar(
                select(FundDefinitionModel.id)
                .where(
                    FundDefinitionModel.owner_id == owner,
                    FundDefinitionModel.instrument_id == identifier,
                )
                .limit(1)
            )
            is None
        ):
            _missing()
        held = (
            select(SnapshotPositionModel.id)
            .join(ListingModel, ListingModel.id == SnapshotPositionModel.listing_id)
            .join(
                PortfolioSnapshotModel,
                PortfolioSnapshotModel.id == SnapshotPositionModel.snapshot_id,
            )
            .where(
                PortfolioSnapshotModel.broker_account_id == account,
                ListingModel.instrument_id == identifier,
                PortfolioSnapshotModel.created_at <= now,
            )
            .limit(1)
        )
        if session.scalar(held) is None:
            _missing()
    if predicate.instrument_id is not None:
        listing = (
            select(ListingModel.id)
            .join(InstrumentModel, InstrumentModel.id == ListingModel.instrument_id)
            .join(
                BrokerConnectionModel,
                (BrokerConnectionModel.provider == ListingModel.provider)
                & (BrokerConnectionModel.environment == ListingModel.environment),
            )
            .join(BrokerAccountModel, BrokerAccountModel.connection_id == BrokerConnectionModel.id)
            .where(
                InstrumentModel.id == predicate.instrument_id,
                BrokerConnectionModel.owner_id == owner,
                BrokerAccountModel.id == account,
            )
            .limit(1)
        )
        if session.scalar(listing) is None:
            _missing()
    if (
        predicate.provider_id is not None
        and session.scalar(
            select(MarketDataProviderModel.id).where(
                MarketDataProviderModel.id == predicate.provider_id,
                MarketDataProviderModel.owner_id == owner,
            )
        )
        is None
    ):
        _missing()
    if (
        predicate.calendar_version_id is not None
        and session.scalar(
            select(SourceCalendarModel.id).where(
                SourceCalendarModel.id == predicate.calendar_version_id,
                SourceCalendarModel.owner_id == owner,
            )
        )
        is None
    ):
        _missing()
    if predicate.source_id is not None:
        family = predicate.source_family or predicate.domain
        if family is d.AlertSourceFamily.VALUATION:
            found = session.scalar(
                select(PortfolioSnapshotModel.id).where(
                    PortfolioSnapshotModel.id == predicate.source_id,
                    PortfolioSnapshotModel.broker_account_id == account,
                )
            )
        elif family is d.AlertSourceFamily.HISTORY:
            found = session.scalar(
                select(HistoricalRunModel.id)
                .join(HistoricalInputModel, HistoricalInputModel.id == HistoricalRunModel.input_id)
                .where(
                    HistoricalRunModel.id == predicate.source_id,
                    HistoricalRunModel.owner_id == owner,
                    HistoricalInputModel.owner_id == owner,
                    HistoricalInputModel.broker_account_id == account,
                )
            )
        else:
            assert family is not None
            model = {
                d.AlertSourceFamily.PRICE: PriceSnapshotModel,
                d.AlertSourceFamily.FX: FxSnapshotModel,
                d.AlertSourceFamily.CONSTITUENT: ConstituentSnapshotModel,
                d.AlertSourceFamily.CLASSIFICATION: ClassificationSnapshotModel,
            }[family]
            found = session.scalar(
                select(model.id).where(model.id == predicate.source_id, model.owner_id == owner)
            )
        if found is None:
            _missing()
    if definition.source_policy_version_id is not None:
        if predicate.family in {
            d.AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION,
            d.AlertFamily.ETF_OVERLAP,
        }:
            found = session.scalar(
                select(XrayPolicyVersionModel.id).where(
                    XrayPolicyVersionModel.id == definition.source_policy_version_id,
                    XrayPolicyVersionModel.owner_id == owner,
                )
            )
        else:
            found = session.scalar(
                select(HistoricalPolicyModel.id).where(
                    HistoricalPolicyModel.id == definition.source_policy_version_id,
                    HistoricalPolicyModel.owner_id == owner,
                    HistoricalPolicyModel.broker_account_id == account,
                    HistoricalPolicyModel.sealed.is_(True),
                )
            )
        if found is None:
            _missing()
    for identifier in definition.destination_ids:
        if (
            session.scalar(
                select(NotificationDestinationModel.id).where(
                    NotificationDestinationModel.id == identifier,
                    NotificationDestinationModel.owner_id == owner,
                    NotificationDestinationModel.account_id == account,
                )
            )
            is None
        ):
            _missing()


class CanonicalAlertCapture:
    def __init__(
        self,
        session: Session,
        authorization: AlertAuthorization,
        *,
        now: datetime,
        cursor_signing_key: bytes,
        sessions: sessionmaker[Session],
    ) -> None:
        self.session, self.authorization, self.now = session, authorization, require_utc(now)
        self.sessions, self.cursor_signing_key = sessions, cursor_signing_key

    def capture_evaluation(
        self,
        version: d.AlertRuleVersion,
        scheduled_for: datetime,
        execution_intent: d.AlertExecutionIntent,
    ) -> d.AlertEvaluationInput:
        cutoff = require_utc(scheduled_for)
        if cutoff > self.now or (version.owner_id, version.account_id) != (
            self.authorization.owner_id,
            self.authorization.account_id,
        ):
            raise app.AlertServiceError(app.AlertServiceErrorCode.VALIDATION_FAILED)
        validate_alert_references(
            self.session, self.authorization, version.definition, now=self.now
        )
        schedule = version.definition.schedule
        interval_seconds = (
            schedule.interval_seconds if isinstance(schedule, d.AlertIntervalSchedule) else 86400
        )
        seconds = version.definition.predicate.window_seconds or interval_seconds
        event = self.session.scalar(
            select(AlertRuleEventModel)
            .where(
                AlertRuleEventModel.rule_id == version.rule_id,
                AlertRuleEventModel.owner_id == version.owner_id,
                AlertRuleEventModel.kind.not_in(("created", "version_created")),
                AlertRuleEventModel.occurred_at <= cutoff,
            )
            .order_by(AlertRuleEventModel.occurred_at.desc(), AlertRuleEventModel.sequence.desc())
            .limit(1)
        )
        newly_known = version.definition.predicate.metric in {
            d.AlertMetric.POSITIVE_DIVIDEND,
            d.AlertMetric.REFRESH_FAILED,
            d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
            d.AlertMetric.UNCLASSIFIED_ACTIVITY,
            d.AlertMetric.REPORT_TERMINAL,
        }
        start = cutoff - timedelta(seconds=seconds)
        if newly_known and event is not None:
            start = max(start, event.occurred_at)
        window = d.AlertObservationWindow(
            start_at=start,
            end_at=cutoff,
            newly_known_revisions=newly_known,
            active_interval_id=None if event is None else event.id,
        )
        sources = PostgresSourceService(
            sessions=self.sessions,
            cursor_signing_key=self.cursor_signing_key,
            clock=lambda: self.now,
        )
        state = AlertCaptureState(
            self.session, self.authorization, version, cutoff, window, now=self.now, sources=sources
        )
        discard_evidence = False
        try:
            if event is None or event.version_id != version.id or event.lifecycle != "active":
                raise AlertCaptureUnavailable(d.AlertReason.RULE_PAUSED)
            payload = self._capture(state)
        except AlertCaptureBound:
            discard_evidence = True
            payload = state.unavailable(d.AlertReason.INPUT_BOUND_EXCEEDED)
        except AlertCaptureUnavailable as error:
            payload = state.unavailable(error.reason)
        except AuthorizationError:
            discard_evidence = True
            payload = state.unavailable(d.AlertReason.SOURCE_RESTRICTED)
        except (
            ActivityRevisionError,
            HistoricalServiceError,
            PlanningServiceError,
            SourceServiceError,
            XrayServiceError,
        ) as error:
            reason = {
                "NOT_FOUND": d.AlertReason.MISSING_INPUT,
                "ACCESS_DENIED": d.AlertReason.SOURCE_RESTRICTED,
                "CURRENCY_MISMATCH": d.AlertReason.CURRENCY_MISMATCH,
                "SOURCE_REVISION_CONFLICT": d.AlertReason.AMBIGUOUS_SOURCE,
                "RESULT_TOO_LARGE": d.AlertReason.INPUT_BOUND_EXCEEDED,
                "INPUT_BOUND_EXCEEDED": d.AlertReason.INPUT_BOUND_EXCEEDED,
                "PROVIDER_UNAVAILABLE": d.AlertReason.NO_OBSERVATIONS,
                "HISTORICAL_UNAVAILABLE": d.AlertReason.MISSING_INPUT,
                "PLANNING_UNAVAILABLE": d.AlertReason.MISSING_INPUT,
                "XRAY_UNAVAILABLE": d.AlertReason.MISSING_INPUT,
                "REVISION_UNAVAILABLE": d.AlertReason.MISSING_INPUT,
            }.get(error.code.value, d.AlertReason.COMPUTATION_FAILED)
            discard_evidence = reason in {
                d.AlertReason.SOURCE_RESTRICTED,
                d.AlertReason.INPUT_BOUND_EXCEEDED,
            }
            payload = state.unavailable(reason)
        except DomainError as error:
            if error.code is not ErrorCode.INPUT_BOUND_EXCEEDED:
                raise
            discard_evidence = True
            payload = state.unavailable(d.AlertReason.INPUT_BOUND_EXCEEDED)
        if discard_evidence:
            # Restricted content and incomplete over-bound prefixes cannot become evidence.
            unavailable_reason = (
                payload.observation.observed.reason
                if isinstance(payload, d.AlertThresholdInput)
                else payload.reason
            )
            assert unavailable_reason is not None
            state = AlertCaptureState(
                self.session,
                self.authorization,
                version,
                cutoff,
                window,
                now=self.now,
                sources=sources,
            )
            payload = state.unavailable(unavailable_reason)
        self.authorization.check(self.session, now=self.now)
        try:
            result = state.finish(payload, execution_intent)
            encode_alert_input(result)
            return result
        except DomainError as error:
            if error.code is not ErrorCode.INPUT_BOUND_EXCEEDED:
                raise
        # Individual row bounds cannot guarantee the encoded 2 MiB limit. Retain the
        # exact slot and reason, never a truncated selection advertised as complete.
        state = AlertCaptureState(
            self.session, self.authorization, version, cutoff, window, now=self.now, sources=sources
        )
        result = state.finish(
            state.unavailable(d.AlertReason.INPUT_BOUND_EXCEEDED), execution_intent
        )
        encode_alert_input(result)
        return result

    def _capture(self, state: AlertCaptureState) -> d.AlertThresholdInput | d.AlertEventBatchInput:
        from .alert_capture_coverage import capture_source_health
        from .alert_capture_events import capture_activity
        from .alert_capture_health import (
            capture_provider,
            capture_reconciliation,
            capture_refresh,
            capture_report_outcomes,
        )
        from .alert_capture_portfolio import capture_direct, capture_drift
        from .alert_capture_xray import capture_xray

        family = state.predicate.family
        if family in {
            d.AlertFamily.TARGET_DRIFT,
            d.AlertFamily.GROUP_DRIFT,
            d.AlertFamily.HOLDING_DRIFT,
        }:
            return capture_drift(
                state, sessions=self.sessions, cursor_signing_key=self.cursor_signing_key
            )
        if family in {d.AlertFamily.CONCENTRATION, d.AlertFamily.CASH_THRESHOLD}:
            return capture_direct(state)
        if family in {d.AlertFamily.EFFECTIVE_COMPANY_CONCENTRATION, d.AlertFamily.ETF_OVERLAP}:
            return capture_xray(
                state, sessions=self.sessions, cursor_signing_key=self.cursor_signing_key
            )
        if family in {d.AlertFamily.STALE_DATA, d.AlertFamily.MISSING_COVERAGE}:
            return capture_source_health(
                state, sessions=self.sessions, cursor_signing_key=self.cursor_signing_key
            )
        if family is d.AlertFamily.PROVIDER_FAILURE:
            return capture_provider(state)
        if family is d.AlertFamily.RECONCILIATION_FAILURE:
            return capture_reconciliation(state)
        if family is d.AlertFamily.FAILED_REFRESH:
            return capture_refresh(state)
        if family is d.AlertFamily.REPORT_OUTCOME:
            return capture_report_outcomes(state)
        if family in {d.AlertFamily.DIVIDEND_RECEIVED, d.AlertFamily.UNUSUAL_ACTIVITY}:
            return capture_activity(state)
        raise AssertionError("The fixed alert source registry is incomplete.")
