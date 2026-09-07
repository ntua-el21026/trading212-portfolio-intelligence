"""Worker page collection cannot hand ingestion a truncated or repeated page chain."""

from dataclasses import dataclass

import pytest
from trading212_application.source_providers import (
    SourceCapability,
    SourceFailure,
    SourceProviderError,
)
from trading212_worker.source_seed import collect_source_pages

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Page:
    rows: int
    continuation: str | None


async def collect(pages: list[Page | SourceFailure]) -> tuple[Page, ...]:
    async def fetch(_: str | None) -> Page | SourceFailure:
        return pages.pop(0)

    return await collect_source_pages(
        fetch,
        page_type=Page,
        row_count=lambda page: page.rows,
        next_cursor=lambda page: page.continuation,
    )


async def test_complete_chain_and_terminal_empty_result_are_distinct() -> None:
    pages = await collect([Page(1, "page-two"), Page(0, None)])
    assert pages == (Page(1, "page-two"), Page(0, None))


async def test_failed_later_page_never_returns_earlier_valid_prefix() -> None:
    failure = SourceFailure(
        code=SourceProviderError.LICENSE_DENIED,
        capability=SourceCapability.PRICE_HISTORY,
        provider_key="synthetic-replay",
    )
    with pytest.raises(
        RuntimeError, match=r"^synthetic reference retrieval failed: license_denied$"
    ):
        await collect([Page(1, "page-two"), failure])


@pytest.mark.parametrize(
    "pages,message",
    [
        ([Page(1, "repeat"), Page(1, "repeat")], "repeated a page cursor"),
        ([Page(1001, None)], "exceeded its row bound"),
        ([Page(1000, str(index)) for index in range(100)], "exceeded its page bound"),
    ],
)
async def test_page_row_and_loop_bounds_fail_closed(pages: list[Page], message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        await collect(list(pages))
