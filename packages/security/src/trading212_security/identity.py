"""Bounded external JWT identities; validation never transforms or dereferences them."""

from __future__ import annotations

import re
import unicodedata
from ipaddress import IPv6Address

# RFC 3986 appendix A. Percent escapes are syntax, never decoded identity data.
_ATOM = r"(?:[A-Za-z0-9._~!$&'()*+,;=-]|%[0-9A-Fa-f]{2})"
_PCHAR = rf"(?:{_ATOM}|[:@])"
_AUTHORITY = rf"(?:{_ATOM}|:)*@"
_HOST = rf"(?:\[(?P<literal>[^\]]+)\]|{_ATOM}*)"
_URI = re.compile(
    rf"[A-Za-z][A-Za-z0-9+.-]*:"
    rf"(?://(?:{_AUTHORITY})?{_HOST}(?::[0-9]*)?(?:/{_PCHAR}*)*"
    rf"|/(?:{_PCHAR}+(?:/{_PCHAR}*)*)?"
    rf"|{_PCHAR}+(?:/{_PCHAR}*)*|)"
    rf"(?:\?(?:{_PCHAR}|[/?])*)?(?:#(?:{_PCHAR}|[/?])*)?"
)
_IP_FUTURE = re.compile(r"[vV][0-9A-Fa-f]+\.[A-Za-z0-9._~!$&'()*+,;=:-]+")
_REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def is_string_or_uri(value: object) -> bool:
    """Validate the application's nonempty 255-character StringOrURI profile."""
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        return False
    if any(unicodedata.category(char) in _REJECTED_CATEGORIES for char in value):
        return False
    if ":" not in value:
        return True
    match = _URI.fullmatch(value)
    if match is None:
        return False
    literal = match.group("literal")
    if literal is None or _IP_FUTURE.fullmatch(literal):
        return True
    # RFC 3986 IP-literals exclude zone identifiers, even if ipaddress accepts them.
    if "%" in literal:
        return False
    try:
        IPv6Address(literal)
    except ValueError:
        return False
    return True
