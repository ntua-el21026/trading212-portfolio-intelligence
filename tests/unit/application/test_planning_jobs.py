from datetime import UTC, datetime
from uuid import uuid4

import pytest
from trading212_application.planning_jobs import PlanDispatchClaim, PlanJobClaim, PlanTaskMessage


def message() -> PlanTaskMessage:
    return PlanTaskMessage(str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4()), "a" * 64)


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", 0, -1, 9])
def test_publication_attempt_requires_bounded_integer(bad: object) -> None:
    with pytest.raises(ValueError):
        PlanDispatchClaim(message(), str(uuid4()), datetime.now(UTC), bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [True, 1.0, "1", 0, 5])
def test_consumer_attempt_requires_bounded_integer(bad: object) -> None:
    with pytest.raises(ValueError):
        PlanJobClaim(message(), str(uuid4()), datetime.now(UTC), bad)  # type: ignore[arg-type]


def test_message_is_closed_schema_and_never_reflects_unknown_input() -> None:
    value = message()
    assert PlanTaskMessage.from_wire(value.to_wire()) == value
    canary = "SYNTHETIC_PLAN_MESSAGE_CANARY"
    for data in (
        {**value.to_wire(), "extra": canary},
        {**value.to_wire(), "job_id": canary},
        {**value.to_wire(), "input_digest": canary},
    ):
        with pytest.raises(ValueError) as error:
            PlanTaskMessage.from_wire(data)
        assert canary not in str(error.value)
        assert error.value.__cause__ is None and error.value.__context__ is None
