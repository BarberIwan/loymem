from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

_hasher = PasswordHasher()
# Used when the e-mail is unknown, so a failed login costs the same time.
_DUMMY_HASH = _hasher.hash("geen-account")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_secret(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def digest(value: str) -> str:
    """Keyed hash for secrets we must look up but never store in plain form."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def new_reward_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def issue_session(staff_id: uuid.UUID, business_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(staff_id),
        "bid": str(business_id),
        "iat": now,
        "exp": now + timedelta(hours=s.session_hours),
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def read_session(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return uuid.UUID(data["sub"]), uuid.UUID(data["bid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def normalise_email(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    return v or None


def normalise_phone(value: str | None) -> str | None:
    """Dutch-first: 06 12345678, +31 6 12345678 and 0031612345678 are one number."""
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit() or c == "+")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "+31" + digits[1:]
    digits = "+" + digits.lstrip("+") if digits else digits
    return digits if 8 <= len(digits) <= 16 else None
