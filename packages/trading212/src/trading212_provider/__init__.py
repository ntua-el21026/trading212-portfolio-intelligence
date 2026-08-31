"""Strictly GET-only Trading 212 provider boundary."""

from .allowlist import CAPABILITIES, Capability
from .client import Trading212Client
from .configuration import BrokerEnvironment, Trading212Settings
from .credentials import CredentialProvider, StaticCredentialProvider, Trading212Credentials
from .errors import (
    CapabilityError,
    MethodNotAllowedError,
    ProviderError,
    ProviderErrorKind,
)
from .ingestion_adapter import Trading212IngestionAdapter

__version__ = "0.1.0"

__all__ = [
    "CAPABILITIES",
    "BrokerEnvironment",
    "Capability",
    "CapabilityError",
    "CredentialProvider",
    "MethodNotAllowedError",
    "ProviderError",
    "ProviderErrorKind",
    "StaticCredentialProvider",
    "Trading212Client",
    "Trading212Credentials",
    "Trading212IngestionAdapter",
    "Trading212Settings",
]
