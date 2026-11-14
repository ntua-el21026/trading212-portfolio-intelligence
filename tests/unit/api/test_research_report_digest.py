"""Research acknowledgment hashes retain their original six-digit UTC encoding."""

from hashlib import sha256

from trading212_api_contracts.premium_reports_v3 import _research_review_digest
from trading212_api_contracts.research import ResearchReviewAcknowledgment


def test_review_digest_uses_research_framing_and_original_fractional_precision() -> None:
    def identity(index: int) -> str:
        return f"00000000-0000-0000-0000-{index:012d}"

    review = ResearchReviewAcknowledgment.model_validate(
        {
            "acknowledgment_id": identity(1),
            "owner_id": identity(2),
            "account_id": identity(3),
            "event_id": identity(4),
            "revision_id": identity(5),
            "revision_digest": "a" * 64,
            "actor_id": identity(6),
            "reviewed_at": "2026-11-14T12:00:00.120000Z",
        }
    )
    expected = (
        '{"account_id":"00000000-0000-0000-0000-000000000003",'
        '"acknowledgment_id":"00000000-0000-0000-0000-000000000001",'
        '"actor_id":"00000000-0000-0000-0000-000000000006",'
        '"event_id":"00000000-0000-0000-0000-000000000004",'
        '"owner_id":"00000000-0000-0000-0000-000000000002",'
        '"reviewed_at":"2026-11-14T12:00:00.120000Z",'
        '"revision_digest":"' + "a" * 64 + '",'
        '"revision_id":"00000000-0000-0000-0000-000000000005"}'
    ).encode()
    assert (
        _research_review_digest(review)
        == sha256(b"t212pi.research.record.v1\0" + expected).hexdigest()
    )
