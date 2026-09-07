"""Calculation-local hashing preserves exact source identities and releases payloads."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest
from trading212_analytics import source_policy as module
from trading212_domain.sources import PriceSnapshot, source_snapshot_digest

from .source_factories import AT, calendar, policy, price


def test_repeated_selection_hashes_each_immutable_snapshot_once_and_preserves_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = price("100")

    def select() -> object:
        return module.select_price(
            (snapshot,),
            series_id=snapshot.series.id,
            at=AT,
            source_cutoff_at=AT,
            policy=policy(),
            calendar=calendar(),
        )

    expected = select()
    calls = 0

    def counted(value: PriceSnapshot) -> str:
        nonlocal calls
        calls += 1
        return source_snapshot_digest(value)

    monkeypatch.setattr(module, "source_snapshot_digest", counted)
    with module._source_digest_scope():
        assert select() == expected
        with module._source_digest_scope():
            assert select() == expected
        assert select() == expected
        assert calls == 1
    assert module._DIGEST_SCOPE.get() is None
    assert select() == expected
    assert calls == 2


def test_equal_ids_do_not_alias_different_exact_source_content() -> None:
    original, other = price("100"), price("101")
    assert original.id == other.id
    with module._source_digest_scope():
        assert module._snapshot_digest(original) == source_snapshot_digest(original)
        assert module._snapshot_digest(other) == source_snapshot_digest(other)
        assert module._snapshot_digest(original) != module._snapshot_digest(other)


def test_digest_scope_releases_licensed_payloads_on_failure_and_is_bounded() -> None:
    with pytest.raises(RuntimeError, match="failed"), module._source_digest_scope():
        for index in range(260):
            snapshot = price(str(index + 1))
            assert module._snapshot_digest(snapshot) == source_snapshot_digest(snapshot)
        cache = module._DIGEST_SCOPE.get()
        assert cache is not None and len(cache) == 256
        raise RuntimeError("failed")
    assert module._DIGEST_SCOPE.get() is None


def test_independent_threads_do_not_share_retained_source_objects() -> None:
    def select(value: str) -> str:
        assert module._DIGEST_SCOPE.get() is None
        snapshot = price(value)
        with module._source_digest_scope():
            result = module._snapshot_digest(snapshot)
            assert copy_context().get(module._DIGEST_SCOPE) is not None
        assert module._DIGEST_SCOPE.get() is None
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(select, ("100", "101")))
    assert results == (source_snapshot_digest(price("100")), source_snapshot_digest(price("101")))
