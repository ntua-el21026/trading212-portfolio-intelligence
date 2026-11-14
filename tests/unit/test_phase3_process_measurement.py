"""Linux resident-counter races retain observed zero versus unavailable readings."""

from pathlib import Path

import pytest

from tests.integration.phase3_projection_budget_worker import _Process, _rss

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("status", "statm", "expected"),
    [
        ("Name:\tworker\nVmRSS:\t32 kB\n", "99 10 0 0 0 0 0\n", 32768),
        ("Name:\tworker\nState:\tR (running)\n", "99 12 0 0 0 0 0\n", 49152),
        ("Name:\tworker\nState:\tR (running)\n", "0 0 0 0 0 0 0\n", 0),
        ("Name:\tworker\n", None, None),
        ("Name:\tworker\n", "99 -1 0 0 0 0 0\n", None),
    ],
    ids=("status-counter", "resident-pages", "observed-zero", "unavailable", "invalid-counter"),
)
def test_rss_counter_has_an_independent_resident_page_fallback(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    statm: str | None,
    expected: int | None,
) -> None:
    def read(path: Path, **_options: object) -> str:
        if path.name == "status":
            return status
        if path.name == "statm" and statm is not None:
            return statm
        raise FileNotFoundError("Synthetic absent process counter")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr("os.sysconf", lambda _name: 4096)
    process = _Process(pid=123, parent=100, group=123, session=123, started=1, state="R")
    assert _rss(process) == expected
