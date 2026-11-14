"""Record actual creation times for new disposable scenario-report source parents."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.orm import Mapper, object_session
from trading212_domain import build_synthetic_identity
from trading212_persistence.xray_catalog_models import (
    ClassificationSnapshotModel,
    ConstituentSnapshotModel,
    EntityEvidenceVersionModel,
    FundDefinitionModel,
    FundSourceMappingModel,
)
from trading212_worker.xray_fixture import XRAY_AT, XRAY_LICENSE_ID, XRAY_PROVIDER_ID

type SourceParent = (
    EntityEvidenceVersionModel
    | ClassificationSnapshotModel
    | ConstituentSnapshotModel
    | FundDefinitionModel
    | FundSourceMappingModel
)

_EXPECTED: dict[type[SourceParent], int] = {
    EntityEvidenceVersionModel: 1,
    ClassificationSnapshotModel: 5,
    ConstituentSnapshotModel: 2,
    FundDefinitionModel: 2,
    FundSourceMappingModel: 2,
}


@contextmanager
def fixture_source_creation_times(database_url: str, *, enabled: bool) -> Iterator[None]:
    """Keep historical financial/knowledge dates; timestamp only the first physical INSERT."""
    if not enabled:
        yield
        return
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg" or not re.fullmatch(
        r"t212pi_web_e2e_[0-9a-f]{32}", url.database or ""
    ):
        raise RuntimeError("Report source creation clocks require a disposable browser database.")
    owner = build_synthetic_identity().owner.id
    provider, license_id = UUID(XRAY_PROVIDER_ID), UUID(XRAY_LICENSE_ID)
    counts = dict.fromkeys(_EXPECTED, 0)
    created: list[datetime] = []

    def before_insert(
        mapper: Mapper[SourceParent], connection: Connection, parent: SourceParent
    ) -> None:
        del mapper
        if (parent.owner_id, parent.provider_id, parent.license_version_id) != (
            owner,
            provider,
            license_id,
        ):
            return
        session = object_session(parent)
        if connection.engine.url != url or session is None or parent not in session.new:
            raise RuntimeError("Report fixture source is outside its new disposable INSERT.")
        if parent.created_at != XRAY_AT or parent.first_observed_at != XRAY_AT:
            raise RuntimeError("Report fixture source does not match its frozen observation.")
        at = datetime.now(UTC)
        if not parent.first_observed_at <= at < parent.expires_at:
            raise RuntimeError("Report fixture source is outside its original physical lifetime.")
        # This row has never been persisted. Only its physical creation clock changes;
        # financial dates, knowledge cutoff, expiry, payloads and digests remain original.
        parent.created_at = at
        counts[type(parent)] += 1
        created.append(at)

    registered: list[type[SourceParent]] = []
    try:
        for model in _EXPECTED:
            event.listen(model, "before_insert", before_insert)
            registered.append(model)
        yield
        if counts != _EXPECTED:
            raise RuntimeError("New report fixture source parent inventory differs.")
        print(
            json.dumps(
                {
                    "fixture": "scenario-report-source-first-insert",
                    "parent_counts": {
                        model.__tablename__: count for model, count in counts.items()
                    },
                    "created_at_min": min(created).isoformat(),
                    "created_at_max": max(created).isoformat(),
                    "first_observed_at": XRAY_AT.isoformat(),
                    "changed_field": "created_at",
                }
            ),
            file=sys.stderr,
        )
    finally:
        for model in reversed(registered):
            event.remove(model, "before_insert", before_insert)
