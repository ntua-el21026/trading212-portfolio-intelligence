"""Stateless SHA256 counter/polar sampler fixed by ADR-0019."""

from decimal import Decimal
from hashlib import sha256

from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.sources import source_integer

from ._premium_numeric import TWO, arithmetic

_DOMAIN = b"t212pi.projection.v1\0"


def normal_at(seed: int, path_index: int, month: int, asset_ordinal: int) -> Decimal:
    """One independent coordinate: zero-based path/asset, one-based simulated month."""
    source_integer(seed, "seed", 0, 2**32 - 1)
    source_integer(path_index, "path_index", 0, 4095)
    source_integer(month, "month", 1, 600)
    source_integer(asset_ordinal, "asset_ordinal", 0, 11)
    prefix = (
        _DOMAIN
        + seed.to_bytes(4, "big")
        + path_index.to_bytes(4, "big")
        + month.to_bytes(2, "big")
        + asset_ordinal.to_bytes(1, "big")
    )
    with arithmetic():
        width = 2**128
        denominator = Decimal(width)
        for attempt in range(32):
            digest = sha256(prefix + attempt.to_bytes(1, "big")).digest()
            first = int.from_bytes(digest[:16], "big")
            second = int.from_bytes(digest[16:], "big")
            # Algebraically exact midpoint centering avoids 39-digit cancellation.
            # These integers are PRNG coordinate encodings, never financial amounts.
            u = Decimal(2 * first + 1 - width) / denominator
            v = Decimal(2 * second + 1 - width) / denominator
            square = u * u + v * v
            if 0 < square < 1:
                return u * (-TWO * square.ln() / square).sqrt()
    raise DomainError(
        ErrorCode.DATA_UNAVAILABLE,
        "Projection sampler exhausted its fixed attempts.",
        "projection.sampler",
    )
