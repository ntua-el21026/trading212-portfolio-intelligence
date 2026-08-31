"""Authentication, authorization, secret, and redaction boundaries."""

from .principals import AuthorizationError, Authorizer, Principal, Scope
from .redaction import RedactingLogFilter, Redactor
from .secrets import EnvironmentSecretProvider, SecretProvider, SecretValue
from .sessions import InMemorySessionStore, SessionManager
from .settings import RuntimeEnvironment, SecuritySettings
from .tokens import JwtAuthenticator, LocalSyntheticAuthenticator

__version__ = "0.1.0"

__all__ = [
    "AuthorizationError",
    "Authorizer",
    "EnvironmentSecretProvider",
    "InMemorySessionStore",
    "JwtAuthenticator",
    "LocalSyntheticAuthenticator",
    "Principal",
    "RedactingLogFilter",
    "Redactor",
    "RuntimeEnvironment",
    "Scope",
    "SecretProvider",
    "SecretValue",
    "SecuritySettings",
    "SessionManager",
]
