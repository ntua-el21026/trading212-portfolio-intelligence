"""Ephemeral asymmetric test signing; never serialize private keys or retain tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa


@dataclass(frozen=True, slots=True, repr=False)
class JwtTestSigner:
    algorithm: str
    _private_key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey
    public_key: bytes

    def __repr__(self) -> str:
        return "JwtTestSigner(redacted=True)"

    @classmethod
    def generate(cls, algorithm: str) -> JwtTestSigner:
        key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey
        if algorithm == "RS256":
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        elif algorithm == "ES256":
            key = ec.generate_private_key(ec.SECP256R1())
        elif algorithm == "EdDSA":
            key = ed25519.Ed25519PrivateKey.generate()
        else:
            raise ValueError("unsupported test signing algorithm")
        public_key = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return cls(algorithm, key, public_key)

    def sign(self, claims: dict[str, Any], headers: dict[str, Any] | None = None) -> str:
        return jwt.encode(claims, self._private_key, algorithm=self.algorithm, headers=headers)

    def sign_raw_claims(self, claims: dict[str, Any]) -> str:
        """Sign malformed claim types without the convenience encoder's claim validation."""
        return jwt.api_jws.encode(
            json.dumps(claims, separators=(",", ":")).encode(),
            self._private_key,
            algorithm=self.algorithm,
        )
