"""
Password hashing and verification using bcrypt directly.

bcrypt is intentionally slow (work-factor 12) which makes offline
brute-force attacks computationally expensive even if the database
is compromised.

Uses the `bcrypt` package directly (not passlib) for Python 3.13+
compatibility.
"""
from __future__ import annotations

import bcrypt

_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*. Safe to store in MongoDB."""
    hashed: bytes = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Return True if *plain* matches *hashed*.
    bcrypt.checkpw runs in constant time to prevent timing attacks.
    """
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
