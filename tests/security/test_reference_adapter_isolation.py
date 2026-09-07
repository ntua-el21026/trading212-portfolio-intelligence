"""The new adapter package grants no new broker or arbitrary HTTP authority."""

from pathlib import Path

import pytest

from scripts import check_architecture as architecture
from scripts import check_trading212_boundary as broker_boundary

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "consumer", ["domain", "analytics", "application", "persistence", "api-contracts"]
)
def test_canonical_layers_cannot_import_reference_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer: str
) -> None:
    path = tmp_path / "packages" / consumer / "source.py"
    path.parent.mkdir(parents=True)
    path.write_text("import trading212_reference_data\n")
    monkeypatch.setattr(architecture, "ROOT", tmp_path)
    assert architecture.validate_architecture() == [
        f"packages/{consumer}/source.py imports forbidden dependency trading212_reference_data"
    ]


def test_reference_namespace_is_not_a_broad_transport_exception(tmp_path: Path) -> None:
    path = broker_boundary.ROOT / "packages/reference-data/src/trading212_reference_data/remote.py"
    import ast

    findings = broker_boundary._transport_import_findings(path, ast.parse("import httpx\n"))
    assert len(findings) == 1 and "only the sealed provider client" in findings[0]
