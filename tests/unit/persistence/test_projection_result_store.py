"""Fences, current authority, exact retained partitions and bounded resumed chunks."""

from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from trading212_analytics.projection import calculate_projection_chunk
from trading212_application.projection import ProjectionErrorCode as Code
from trading212_domain.errors import DomainError
from trading212_domain.projection_serialization import (
    decode_projection_chunk,
    projection_canonical_bytes,
)
from trading212_domain.serialization import canonical_json
from trading212_persistence import projection_result_store as module
from trading212_persistence.projection_definition_store import ProjectionStorageError
from trading212_persistence.projection_result_rows import ProjectionChunkRows
from trading212_persistence.projection_result_store import StoredProjectionChunk, _Fence
from trading212_security.principals import AuthorizationError

from tests.unit.persistence.projection_result_store_factories import (
    AT,
    JOB,
    LEASE,
    chunk_header,
    records,
    store,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def case() -> Any:
    return records()


@pytest.mark.parametrize(
    "change", ["lease", "attempt", "state", "deadline", "lease_expiry", "actor", "reservation"]
)
def test_invalid_fence_precedes_retained_input_decode(case: Any, change: str) -> None:
    captured, _value, auth, _original_root, run, _original_job = case
    service, session = store()
    # Use fresh SQLAlchemy metadata for each independent mutation.
    _, _, _, root, _, job = records()
    if change == "lease":
        job.lease_token = UUID(int=99999)
    elif change == "attempt":
        job.consumer_attempts = 1
    elif change == "state":
        job.state = "succeeded"
    elif change == "deadline":
        job.deadline_at = AT
    elif change == "lease_expiry":
        job.lease_expires_at = AT
    elif change == "actor":
        root.actor_principal_id = UUID(int=99999)
    else:
        root.reserved_bytes = 1
    session.scalar.side_effect = [root, run, None, job]
    with (
        patch.object(service, "authority", return_value=auth),
        patch("trading212_persistence.projection_result_store.projection_owner_lock"),
        patch.object(service, "read_retained_input") as read,
        pytest.raises(ProjectionStorageError) as rejected,
    ):
        service._load_root(
            session,
            auth,
            root,
            captured,
            fence=_Fence(job_id=JOB, lease_token=LEASE, consumer_attempt=2),
        )
    assert rejected.value.code is Code.INVALID_STATE_TRANSITION
    read.assert_not_called()


def test_wrong_capture_digest_and_pending_retention_precede_input_or_result_bytes(
    case: Any,
) -> None:
    captured, _value, auth, _root, run, _job = case
    service, session = store()
    _, _, _, root, _, _ = records()
    root.input_digest = "0" * 64
    session.scalar.side_effect = [root, run]
    with (
        patch.object(service, "authority", return_value=auth),
        patch("trading212_persistence.projection_result_store.projection_owner_lock"),
        patch.object(service, "read_retained_input") as read,
        pytest.raises(ProjectionStorageError) as caught,
    ):
        service._load_root(session, auth, root, captured, fence=None)
    assert caught.value.code is Code.PROJECTION_UNAVAILABLE
    read.assert_not_called()
    root.input_digest = captured.input_digest
    session.scalar.side_effect = [root, run, UUID(int=888)]
    with (
        patch.object(service, "authority", return_value=auth),
        patch("trading212_persistence.projection_result_store.projection_owner_lock"),
        patch.object(service, "read_retained_input") as read,
        pytest.raises(ProjectionStorageError) as caught,
    ):
        service._load_root(session, auth, root, captured, fence=None)
    assert caught.value.code is Code.RUN_EXPIRED
    read.assert_not_called()


def test_revoked_current_grant_precedes_parent_and_all_private_queries(case: Any) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    with (
        patch.object(service, "authority", side_effect=AuthorizationError("private-canary")),
        pytest.raises(AuthorizationError),
    ):
        service._load_root(session, auth, root, captured, fence=None)
    session.scalar.assert_not_called()
    session.execute.assert_not_called()


def test_original_retained_source_clock_is_used_for_final_authorization(case: Any) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    session.scalar.return_value = None
    with (
        patch.object(type(auth), "check"),
        patch.object(
            service.sources, "authorize_sources", return_value=((), captured.expires_at)
        ) as authorize,
    ):
        assert service._source_boundary(session, auth, root, captured) == captured.expires_at
    authorize.assert_called_once_with(
        session,
        auth,
        captured.plan.assumption_version.content.calibration_pins,
        snapshot_id=None,
        retained_at=root.created_at,
    )
    with (
        patch.object(type(auth), "check"),
        patch.object(
            service.sources,
            "authorize_sources",
            return_value=((), root.expires_at - timedelta(seconds=1)),
        ),
        pytest.raises(ProjectionStorageError) as rejected,
    ):
        service._source_boundary(session, auth, root, captured)
    assert rejected.value.code is Code.RUN_EXPIRED


@pytest.mark.parametrize("size", [-1, 33554433, None, True])
def test_actual_physical_bytes_fail_closed(case: Any, size: Any) -> None:
    _captured, _value, _auth, root, _run, _job = case
    service, session = store()
    session.scalar.return_value = size
    with pytest.raises(ProjectionStorageError) as caught:
        service._result_bytes(session, root)
    assert caught.value.code is Code.INPUT_BOUND_EXCEEDED


def test_full_reservation_is_not_double_charged_and_zero_charge_cannot_retain_bytes() -> None:
    service, session = store()
    _, _, _, root, _, _ = records()
    session.scalar.return_value = 1000
    assert root.retained_bytes == 0 and service._result_bytes(session, root) == 1000
    root.retained_bytes = 1
    with pytest.raises(ProjectionStorageError):
        service._result_bytes(session, root)
    root.reserved_bytes = 0
    with pytest.raises(ProjectionStorageError):
        service._result_bytes(session, root)


def test_exact_old_chunk_replay_preserves_old_identity_and_attempt_metadata(case: Any) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    header = chunk_header(captured)
    chunk = decode_projection_chunk(header.canonical_chunk)
    saved = StoredProjectionChunk(
        id=header.id,
        run_id=root.id,
        content_digest=header.content_digest,
        created_at=header.created_at,
        chunk=chunk,
    )
    session.scalars.return_value = [header]
    original = (
        header.id,
        header.lease_token,
        header.consumer_attempt,
        header.created_at,
        header.canonical_chunk,
    )
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_chunk", return_value=saved),
        patch.object(service, "_result_bytes", return_value=2000),
        patch.object(service, "_source_boundary"),
        patch.object(service, "_batch_boundary"),
    ):
        returned = service.publish_chunk(
            session, auth, root, captured, chunk, job_id=JOB, lease_token=LEASE, consumer_attempt=2
        )
    assert returned is saved
    assert (
        header.id,
        header.lease_token,
        header.consumer_attempt,
        header.created_at,
        header.canonical_chunk,
    ) == original
    session.add.assert_not_called()
    session.flush.assert_not_called()


def test_overlapping_changed_chunk_range_conflicts_before_any_retained_chunk_bytes(
    case: Any,
) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    header = chunk_header(captured)
    session.scalars.return_value = [header]
    changed = calculate_projection_chunk(captured.plan.inputs, 1, 2)
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_chunk") as read,
        pytest.raises(ProjectionStorageError) as caught,
    ):
        service.publish_chunk(
            session,
            auth,
            root,
            captured,
            changed,
            job_id=JOB,
            lease_token=LEASE,
            consumer_attempt=2,
        )
    assert caught.value.code is Code.CONFLICT
    read.assert_not_called()
    session.add.assert_not_called()


def test_chunk_read_checks_current_boundary_and_full_normalized_rows_without_sampling(
    case: Any,
) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    header = chunk_header(captured)
    session.scalar.return_value = header.canonical_chunk
    boundary = MagicMock()
    with (
        patch(
            "trading212_analytics.projection.calculate_projection",
            side_effect=AssertionError("sampler"),
        ),
        patch("trading212_persistence.projection_result_store.reconcile_chunk_rows") as reconcile,
    ):
        stored = service._chunk(session, auth, root, captured, header, boundary=boundary)
    boundary.assert_called_once()
    assert projection_canonical_bytes(stored.chunk) == header.canonical_chunk
    args, kwargs = reconcile.call_args
    assert args[1] == ProjectionChunkRows(run_id=root.id, chunk_id=header.id, value=stored.chunk)
    assert kwargs["publish"] is False and kwargs["created_at"] == header.created_at
    with (
        patch(
            "trading212_persistence.projection_result_store.reconcile_chunk_rows",
            side_effect=ProjectionStorageError(Code.PROJECTION_UNAVAILABLE),
        ),
        pytest.raises(ProjectionStorageError),
    ):
        service._chunk(session, auth, root, captured, header, boundary=boundary)


def test_complete_partition_rejects_gap_and_saved_paths_different_from_result(case: Any) -> None:
    captured, calculation, auth, root, _run, _job = case
    service, session = store()
    header = chunk_header(captured, start=1)
    stream = MagicMock()
    stream.__iter__.return_value = iter((header,))
    session.scalars.return_value = stream
    with patch.object(service, "_chunk") as chunk, pytest.raises(ProjectionStorageError):
        service._complete_chunks(
            session,
            auth,
            root,
            captured,
            calculation,
            job_id=JOB,
            attempt=2,
            created_at=AT,
            boundary=lambda: None,
        )
    chunk.assert_not_called()
    stream.close.assert_called_once()
    header = chunk_header(captured)
    incorrect = calculate_projection_chunk(
        replace(captured.plan.inputs, seed=captured.plan.inputs.seed + 1), 0, 2
    )
    bad = StoredProjectionChunk(
        id=header.id,
        run_id=root.id,
        created_at=AT,
        content_digest=header.content_digest,
        chunk=incorrect,
    )
    stream.__iter__.return_value = iter((header,))
    with (
        patch.object(service, "_chunk", return_value=bad),
        pytest.raises(ProjectionStorageError),
    ):
        service._complete_chunks(
            session,
            auth,
            root,
            captured,
            calculation,
            job_id=JOB,
            attempt=2,
            created_at=AT,
            boundary=lambda: None,
        )


def test_chunk_page_applies_aggregate_bytes_and_continues_without_empty_progress(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured, _value, auth, root, _run, job = case
    service, session = store()
    headers = (chunk_header(captured), chunk_header(captured, start=2, identifier=801))
    values = tuple(
        StoredProjectionChunk(
            id=h.id,
            run_id=root.id,
            created_at=AT,
            content_digest=h.content_digest,
            chunk=decode_projection_chunk(h.canonical_chunk),
        )
        for h in headers
    )
    session.scalars.return_value = headers
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_job", return_value=job),
        patch.object(service, "_chunk", side_effect=values),
        patch.object(service, "_source_boundary"),
        patch.object(service, "_batch_boundary"),
    ):
        monkeypatch.setattr(module, "PROJECTION_MAX_BYTES", len(canonical_json(values[0]).encode()))
        assert service.read_chunks(session, auth, root, captured) == (values[0],)
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_job", return_value=job),
        patch.object(service, "_chunk") as read,
    ):
        monkeypatch.setattr(module, "PROJECTION_MAX_BYTES", 1)
        with pytest.raises(ProjectionStorageError) as caught:
            service.read_chunks(session, auth, root, captured)
    assert caught.value.code is Code.INPUT_BOUND_EXCEEDED
    read.assert_not_called()


def test_final_source_restriction_prevents_return_of_decoded_chunk_page(case: Any) -> None:
    captured, _value, auth, root, _run, job = case
    service, session = store()
    header = chunk_header(captured)
    session.scalars.return_value = [header]
    stored = StoredProjectionChunk(
        id=header.id,
        run_id=root.id,
        content_digest=header.content_digest,
        created_at=AT,
        chunk=decode_projection_chunk(header.canonical_chunk),
    )
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_job", return_value=job),
        patch.object(service, "_chunk", return_value=stored),
        patch.object(
            service, "_source_boundary", side_effect=ProjectionStorageError(Code.SOURCE_UNAVAILABLE)
        ),
        pytest.raises(ProjectionStorageError) as caught,
    ):
        service.read_chunks(session, auth, root, captured)
    assert caught.value.code is Code.SOURCE_UNAVAILABLE


@pytest.mark.parametrize(
    "after,limit", [(None, 0), (None, 33), (("unknown", 0), 1), (("baseline", True), 1)]
)
def test_invalid_chunk_page_keys_fail_before_authorization_or_byte_reads(
    case: Any, after: Any, limit: int
) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    with (
        patch.object(service, "_load_root") as read,
        pytest.raises((ProjectionStorageError, DomainError)),
    ):
        service.read_chunks(session, auth, root, captured, after=after, limit=limit)
    read.assert_not_called()


def result_header(case: Any) -> Any:
    from trading212_persistence.projection_models import ProjectionResultModel
    from trading212_persistence.projection_retained_codec import pack_projection_result

    captured, value, auth, root, _run, _job = case
    packed = pack_projection_result(value)
    return ProjectionResultModel(
        id=UUID(int=901),
        run_id=root.id,
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        created_at=AT,
        job_id=JOB,
        lease_token=LEASE,
        consumer_attempt=2,
        input_digest=captured.plan.numerical_input_digest,
        content_digest=packed.content_digest,
        byte_length=packed.byte_length,
        canonical_result=packed.canonical_result,
        quality="estimated",
        sampler="sha256_counter_polar_v1",
        sealed=True,
    )


def test_saved_result_preserves_actual_identity_clock_and_complete_calculation(case: Any) -> None:
    captured, value, auth, root, _run, _job = case
    service, session = store()
    header = result_header(case)
    session.scalar.return_value = header.canonical_result
    boundary = MagicMock()
    with (
        patch.object(service, "_complete_chunks") as chunks,
        patch("trading212_persistence.projection_result_store.reconcile_result_rows") as rows,
        patch(
            "trading212_analytics.projection.calculate_projection",
            side_effect=AssertionError("resample"),
        ),
    ):
        result = service._read_result_record(
            session, auth, root, captured, header, boundary=boundary
        )
    assert (result.id, result.run_id, result.content_digest, result.created_at) == (
        header.id,
        root.id,
        header.content_digest,
        AT,
    )
    assert projection_canonical_bytes(result.calculation) == projection_canonical_bytes(value)
    boundary.assert_called_once()
    chunks.assert_called_once()
    assert rows.call_args.kwargs["publish"] is False
    assert rows.call_args.kwargs["created_at"] == AT


def test_unsealed_or_wrong_numeric_result_header_precedes_private_bytes(case: Any) -> None:
    captured, _value, auth, root, _run, _job = case
    for change in ("sealed", "input_digest"):
        service, session = store()
        header = result_header(case)
        setattr(header, change, False if change == "sealed" else "0" * 64)
        with pytest.raises(ProjectionStorageError):
            service._read_result_record(
                session, auth, root, captured, header, boundary=lambda: None
            )
        session.scalar.assert_not_called()


def test_result_requires_succeeded_job_before_saved_result_decoder(case: Any) -> None:
    captured, _value, auth, root, _run, job = case
    service, session = store()
    session.scalar.return_value = result_header(case)
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_job", return_value=job),
        patch.object(service, "_read_result_record") as decode,
        pytest.raises(ProjectionStorageError),
    ):
        service.read_result(session, auth, root, captured)
    assert job.state == "running"
    decode.assert_not_called()


def test_result_publication_cannot_seal_without_complete_saved_chunks(case: Any) -> None:
    captured, value, auth, root, _run, _job = case
    service, session = store()
    session.scalar.return_value = None
    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(
            service,
            "_complete_chunks",
            side_effect=ProjectionStorageError(Code.PROJECTION_UNAVAILABLE),
        ),
        pytest.raises(ProjectionStorageError),
    ):
        service.publish_result(
            session,
            auth,
            root,
            captured,
            value,
            job_id=JOB,
            lease_token=LEASE,
            consumer_attempt=2,
        )
    session.add.assert_not_called()


def test_result_publication_seals_only_after_normalized_parity_and_final_authority(
    case: Any,
) -> None:
    captured, value, auth, root, _run, _job = case
    service, session = store()
    session.scalar.return_value = None
    added: list[Any] = []
    events: list[str] = []
    session.add.side_effect = added.append

    def normalized(*args: Any, **kwargs: Any) -> None:
        assert len(added) == 1 and added[0].sealed is False
        assert kwargs["publish"] is True
        events.append("normalized")

    def final(*args: Any, **kwargs: Any) -> Any:
        events.append("sources")
        return captured.expires_at

    with (
        patch.object(service, "_load_root", return_value=(auth, root, captured.expires_at)),
        patch.object(service, "_complete_chunks"),
        patch(
            "trading212_persistence.projection_result_store.reconcile_result_rows",
            side_effect=normalized,
        ),
        patch.object(service, "_source_boundary", side_effect=final),
        patch.object(service, "_batch_boundary"),
        patch.object(service, "_result_bytes", return_value=10000),
    ):
        result = service.publish_result(
            session, auth, root, captured, value, job_id=JOB, lease_token=LEASE, consumer_attempt=2
        )
    assert events == ["normalized", "sources", "sources"]
    assert added[0].sealed is True and result.id == added[0].id
    assert added[0].lease_token == LEASE and added[0].consumer_attempt == 2
    assert root.reserved_bytes == 33554432 and root.retained_bytes == 0
    session.commit.assert_not_called()


def test_complete_saved_variants_cover_every_absolute_path_in_bounded_metadata_stream(
    case: Any,
) -> None:
    from trading212_domain.projection_result import ProjectionChunk

    captured, calculation, auth, root, _run, _job = case
    service, session = store()
    headers = tuple(
        chunk_header(captured, count=7, variant=variant.variant, identifier=810 + index)
        for index, variant in enumerate(calculation.variants)
    )
    values = tuple(
        StoredProjectionChunk(
            id=header.id,
            run_id=root.id,
            created_at=AT,
            content_digest=header.content_digest,
            chunk=ProjectionChunk(
                input_digest=calculation.input_digest, variant=variant.variant, paths=variant.paths
            ),
        )
        for header, variant in zip(headers, calculation.variants, strict=True)
    )
    stream = MagicMock()
    stream.__iter__.return_value = iter(headers)
    session.scalars.return_value = stream
    with patch.object(service, "_chunk", side_effect=values) as chunks:
        service._complete_chunks(
            session,
            auth,
            root,
            captured,
            calculation,
            job_id=JOB,
            attempt=2,
            created_at=AT,
            boundary=lambda: None,
        )
    assert chunks.call_count == 3
    assert session.scalars.call_args.args[0].get_execution_options()["yield_per"] == 256
    stream.close.assert_called_once()


def test_expired_batch_boundary_precedes_chunk_bytea(case: Any) -> None:
    captured, _value, auth, root, _run, _job = case
    service, session = store()
    header = chunk_header(captured)
    with pytest.raises(ProjectionStorageError):
        service._chunk(
            session,
            auth,
            root,
            captured,
            header,
            boundary=MagicMock(side_effect=ProjectionStorageError(Code.RUN_EXPIRED)),
        )
    session.scalar.assert_not_called()
