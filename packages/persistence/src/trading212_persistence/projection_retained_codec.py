"""Exact bounded retained bytes matching projection migration0022 columns.

These are private typed records, not transport schemas or authorization evidence.
The caller must authorize current metadata before fetching/decompressing bytes. All
retained paths/points are restored; validation never calls the path sampler.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import DecimalException
from hashlib import sha256

from trading212_application.projection_capture import ProjectionCapturePlan
from trading212_domain.errors import DomainError
from trading212_domain.projection import PROJECTION_MAX_BYTES, ProjectionInput, ProjectionVariant
from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk
from trading212_domain.projection_serialization import (
    decode_projection_chunk,
    decode_projection_input,
    decode_projection_result,
    projection_canonical_bytes,
    projection_input_digest,
)
from trading212_domain.projection_validation import validate_projection_path_basis

from .projection_capture_codec import (
    ProjectionCaptureBinding,
    ProjectionCodecError,
    ProjectionCodecErrorCode,
    bounded_projection_bytes,
    decode_projection_capture,
    encode_projection_capture,
    invalid_projection_storage,
    projection_storage_digest,
)

_INPUT_PREFIX = b"t212pi.projection.input.v1\0"


def _length(payload: bytes, declared: int) -> None:
    bounded_projection_bytes(payload)
    if type(declared) is not int or declared != len(payload):
        invalid_projection_storage()


def _checksum(payload: bytes, declared: str) -> None:
    projection_storage_digest(declared)
    if sha256(payload).hexdigest() != declared:
        invalid_projection_storage()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionInputBytes:
    canonical_capture: bytes
    canonical_input: bytes
    capture_bytes: int
    input_bytes: int

    def __post_init__(self) -> None:
        _length(self.canonical_capture, self.capture_bytes)
        _length(self.canonical_input, self.input_bytes)
        if self.capture_bytes + self.input_bytes > PROJECTION_MAX_BYTES:
            raise ProjectionCodecError(ProjectionCodecErrorCode.INPUT_BOUND_EXCEEDED)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionChunkBytes:
    canonical_chunk: bytes
    byte_length: int
    content_digest: str
    input_digest: str
    variant: ProjectionVariant
    first_path: int
    path_count: int

    def __post_init__(self) -> None:
        _length(self.canonical_chunk, self.byte_length)
        _checksum(self.canonical_chunk, self.content_digest)
        projection_storage_digest(self.input_digest)
        if (
            type(self.variant) is not str
            or self.variant not in ("baseline", "contribution_delta", "mean_log_delta")
            or type(self.first_path) is not int
            or type(self.path_count) is not int
            or not 0 <= self.first_path <= 4095
            or not 1 <= self.path_count <= 32
            or self.first_path + self.path_count > 4096
        ):
            invalid_projection_storage()


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectionResultBytes:
    canonical_result: bytes
    byte_length: int
    content_digest: str
    input_digest: str

    def __post_init__(self) -> None:
        _length(self.canonical_result, self.byte_length)
        _checksum(self.canonical_result, self.content_digest)
        projection_storage_digest(self.input_digest)


def pack_projection_input(value: ProjectionCapturePlan) -> ProjectionInputBytes:
    captured = encode_projection_capture(value)
    numerical = projection_canonical_bytes(value.inputs)
    return ProjectionInputBytes(
        canonical_capture=captured,
        canonical_input=numerical,
        capture_bytes=len(captured),
        input_bytes=len(numerical),
    )


def unpack_projection_input(
    value: ProjectionInputBytes, *, expected: ProjectionCaptureBinding
) -> ProjectionCapturePlan:
    if type(value) is not ProjectionInputBytes or type(expected) is not ProjectionCaptureBinding:
        invalid_projection_storage()
    # Revalidate declarations even if an in-process caller forged a frozen instance.
    value.__post_init__()
    if sha256(_INPUT_PREFIX + value.canonical_input).hexdigest() != expected.numerical_input_digest:
        invalid_projection_storage()
    restored = decode_projection_capture(value.canonical_capture, expected=expected)
    try:
        numerical = decode_projection_input(value.canonical_input)
        if (
            numerical != restored.inputs
            or projection_canonical_bytes(restored.inputs) != value.canonical_input
        ):
            invalid_projection_storage()
    except (DomainError, ValueError, TypeError, OverflowError, RecursionError, DecimalException):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None
    return restored


def unpack_projection_chunk(
    value: ProjectionChunkBytes, *, expected_inputs: ProjectionInput
) -> ProjectionChunk:
    if type(value) is not ProjectionChunkBytes or type(expected_inputs) is not ProjectionInput:
        invalid_projection_storage()
    value.__post_init__()
    try:
        if (
            value.input_digest != projection_input_digest(expected_inputs)
            or value.variant not in expected_inputs.variants
            or value.first_path + value.path_count > expected_inputs.paths
        ):
            invalid_projection_storage()
        restored = decode_projection_chunk(value.canonical_chunk)
        if (
            restored.input_digest != value.input_digest
            or restored.variant != value.variant
            or tuple(path.index for path in restored.paths)
            != tuple(range(value.first_path, value.first_path + value.path_count))
        ):
            invalid_projection_storage()
        asset_keys = tuple(asset.key for asset in expected_inputs.assumptions.assets)
        for path in restored.paths:
            if (
                path.reporting_currency != expected_inputs.assumptions.reporting_currency
                or tuple(point.month for point in path.points) != expected_inputs.retained_months
                or any(
                    tuple(asset.key for asset in point.assets) != asset_keys
                    for point in path.points
                )
                or path.points[0].nominal != expected_inputs.initial.value.amount
            ):
                invalid_projection_storage()
            validate_projection_path_basis(expected_inputs, path, value.variant)
        return restored
    except (DomainError, ValueError, TypeError, OverflowError, RecursionError, DecimalException):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None


def pack_projection_chunk(
    value: ProjectionChunk, *, expected_inputs: ProjectionInput
) -> ProjectionChunkBytes:
    if type(value) is not ProjectionChunk or type(expected_inputs) is not ProjectionInput:
        invalid_projection_storage()
    try:
        payload = projection_canonical_bytes(value)
        packed = ProjectionChunkBytes(
            canonical_chunk=payload,
            byte_length=len(payload),
            content_digest=sha256(payload).hexdigest(),
            input_digest=value.input_digest,
            variant=value.variant,
            first_path=value.paths[0].index,
            path_count=len(value.paths),
        )
        unpack_projection_chunk(packed, expected_inputs=expected_inputs)
        return packed
    except (
        DomainError,
        ValueError,
        TypeError,
        IndexError,
        OverflowError,
        RecursionError,
        DecimalException,
    ):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None


def unpack_projection_result(
    value: ProjectionResultBytes, *, expected_inputs: ProjectionInput
) -> ProjectionCalculation:
    if type(value) is not ProjectionResultBytes or type(expected_inputs) is not ProjectionInput:
        invalid_projection_storage()
    value.__post_init__()
    try:
        if value.input_digest != projection_input_digest(expected_inputs):
            invalid_projection_storage()
        restored = decode_projection_result(value.canonical_result)
        if restored.input_digest != value.input_digest or restored.inputs != expected_inputs:
            invalid_projection_storage()
        # The existing closed result constructor checks every requested variant/path,
        # full retained point and summary against those exact inputs and saved vectors.
        return restored
    except (DomainError, ValueError, TypeError, OverflowError, RecursionError, DecimalException):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None


def pack_projection_result(value: ProjectionCalculation) -> ProjectionResultBytes:
    if type(value) is not ProjectionCalculation:
        invalid_projection_storage()
    try:
        payload = projection_canonical_bytes(value)
        packed = ProjectionResultBytes(
            canonical_result=payload,
            byte_length=len(payload),
            content_digest=sha256(payload).hexdigest(),
            input_digest=value.input_digest,
        )
        unpack_projection_result(packed, expected_inputs=value.inputs)
        return packed
    except (DomainError, ValueError, TypeError, OverflowError, RecursionError, DecimalException):
        raise ProjectionCodecError(ProjectionCodecErrorCode.PROJECTION_UNAVAILABLE) from None
