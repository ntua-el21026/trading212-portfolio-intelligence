"""Synthetic authorized public views built from an actual typed alert calculation."""

from datetime import timedelta

from trading212_analytics.alerts import evaluate_alert
from trading212_application import alerts as app
from trading212_application.alert_projection import alert_content
from trading212_domain import alerts as domain
from trading212_domain.alert_serialization import alert_record_digest

from tests.unit.analytics.alert_factories import AT, capture, uid

NOW = AT
ACCOUNT, RULE, EVENT = str(uid(2)), str(uid(1)), str(uid(30))


def evaluation() -> app.AlertEvaluationView:
    saved = capture()
    result = evaluate_alert(saved)
    return app.AlertEvaluationView(
        id=uid(31),
        job_id=uid(32),
        rule_id=saved.version.rule_id,
        rule_version_id=saved.version.id,
        account_id=saved.version.account_id,
        input_digest=result.input_digest,
        result_digest=alert_record_digest(result),
        rule_content_digest=saved.version.content_digest,
        definition=saved.version.definition,
        source_references=saved.source_references,
        canonical_bindings=saved.canonical_bindings,
        licenses=saved.licenses,
        scheduled_for=AT,
        evaluated_at=AT,
        outcome=result.outcome,
        execution_intent=result.execution_intent,
        result=result,
        reproducibility=app.AlertReproducibility.RETAINED,
        expires_at=AT + timedelta(days=90),
    )


def rule() -> app.AlertRuleDetail:
    return app.AlertRuleDetail(
        id=uid(1),
        account_id=uid(2),
        revision=1,
        lifecycle=domain.AlertLifecycle.DRAFT,
        created_at=AT,
        updated_at=AT,
        latest_version=capture().version,
        active_version=None,
        next_scheduled_for=None,
        latest_evaluation=None,
        version_page=app.AlertRuleVersionPage(
            items=(capture().version,), total=1, limit=25, next_cursor=None
        ),
        evaluation_page=app.AlertEvaluationPage(items=(), total=0, limit=25, next_cursor=None),
    )


def event() -> app.AlertEventDetail:
    return app.AlertEventDetail(
        id=uid(30),
        account_id=uid(2),
        rule_id=uid(1),
        rule_version_id=capture().version.id,
        evaluation_id=uid(31),
        revision=1,
        deduplication_digest="b" * 64,
        severity=domain.AlertSeverity.WARNING,
        episode_state=app.AlertEventState.OPEN,
        occurred_at=AT,
        recorded_at=AT,
        updated_at=AT,
        evaluation=evaluation(),
        delivery=app.AlertDeliverySummary(
            in_app_notification_id=uid(40),
            created_at=AT,
            notification_state=domain.AlertNotificationState.ELIGIBLE,
        ),
    )


def body() -> dict[str, object]:
    return {"account_id": ACCOUNT, "definition": alert_content(capture().version.definition)}


def summary_page() -> app.AlertSummaryPage:
    return app.AlertSummaryPage(
        account_id=uid(2),
        source_cutoff_at=AT,
        counts=app.AlertSummaryCounts(
            total_count=1, open_count=1, resolved_count=0, acknowledged_count=0
        ),
        page=app.AlertEventPage(items=(event(),), total=1, limit=25, next_cursor=None),
    )
