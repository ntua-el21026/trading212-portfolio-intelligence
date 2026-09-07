"""Provider parser bounds reject ambiguous JSON without retaining raw errors."""

import pytest
from trading212_reference_data.bounded_json import DecodeFailure, decode_replay_json

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "payload",
    [b'{"value":1.2}', b'{"value":NaN}', b'{"a":1,"a":2}', b"[]", b"\xff", b"{"],
)
def test_reference_json_rejects_ambiguous_or_nonobject_data(payload: bytes) -> None:
    assert decode_replay_json(payload) is DecodeFailure.INVALID_SCHEMA


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":"' + b"a" * 4097 + b'"}',
        b'{"a":' * 18 + b"null" + b"}" * 18,
        b" " * (8 * 1024 * 1024 + 1),
    ],
)
def test_reference_json_enforces_independent_resource_bounds(payload: bytes) -> None:
    assert decode_replay_json(payload) is DecodeFailure.PAYLOAD_TOO_LARGE


def test_reference_json_preserves_exact_string_numbers_and_integer_revision() -> None:
    assert decode_replay_json(b'{"value":"1.000000000000000001","revision":2}') == {
        "value": "1.000000000000000001",
        "revision": 2,
    }
