"""Read report body text without confusing page framing with canonical values."""

from collections.abc import Sequence


def report_body_text(pages: Sequence[str]) -> str:
    assert pages, "Missing PDF pages."
    bodies = []
    for number, page in enumerate(pages, 1):
        lines = page.splitlines()
        assert len(lines) >= 3, "Missing report page framing."
        assert lines[0] == "PORTFOLIO INTELLIGENCE", "Unexpected report page header."
        assert lines[-2:] == [
            "Private financial information | Canonical values, no execution",
            str(number),
        ], "Unexpected report page footer or page number."
        # Only the verified outer lines are framing. Identical text inside a
        # canonical record must remain available to the parity assertions.
        bodies.append("\n".join(lines[1:-2]))
    return "\n".join(bodies)
