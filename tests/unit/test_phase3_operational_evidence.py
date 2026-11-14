"""The restore comparator preserves actual constraint differences."""

import pytest

from tests.integration.phase3_operational_fixture import canonical_text_arrays

pytestmark = pytest.mark.unit


def test_restore_text_array_cast_forms_have_one_exact_literal_identity() -> None:
    original = "state::text = ANY (ARRAY['a'::character varying, 'b,c'::character varying]::text[])"
    restored = (
        "state::text = ANY (ARRAY['a'::character varying::text, 'b,c'::character varying::text])"
    )
    assert canonical_text_arrays(original) == canonical_text_arrays(restored)
    assert canonical_text_arrays(original) != canonical_text_arrays(restored.replace("'a'", "'z'"))
    assert canonical_text_arrays(original) != canonical_text_arrays(restored.replace("ANY", "ALL"))


def test_restore_comparator_leaves_other_casts_and_dynamic_arrays_exact() -> None:
    for expression in (
        "ARRAY[1::numeric,2::numeric]::text[]",
        "ARRAY[column_name::character varying]::text[]",
        "ARRAY['a'::character varying]",
        "amount::numeric(80,18) > 0",
        "('a'::character varying)::text",
    ):
        assert canonical_text_arrays(expression) == expression


def test_partial_index_literal_cast_forms_preserve_every_boolean_predicate() -> None:
    original = (
        "(copy_pending AND ((kind)::text = ANY "
        "((ARRAY['risk'::character varying, 'scenario'::character varying])::text[])))"
    )
    restored = (
        "(copy_pending AND ((kind)::text = ANY "
        "(ARRAY[('risk'::character varying)::text, ('scenario'::character varying)::text])))"
    )
    assert canonical_text_arrays(original) == canonical_text_arrays(restored)
    assert canonical_text_arrays(original) != canonical_text_arrays(
        restored.replace("copy_pending", "NOT copy_pending")
    )
    assert canonical_text_arrays(original) != canonical_text_arrays(
        restored.replace("'scenario'", "'projection'")
    )
