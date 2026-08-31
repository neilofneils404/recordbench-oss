"""Short-lived signed URLs for browser delivery of transient artifacts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable


class InvalidDeliveryToken(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeliveryGrant:
    job_id: str
    owner_key: str
    artifact: str
    purge_after_delivery: bool
    expires_at: int


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise InvalidDeliveryToken("Invalid delivery token") from exc


class DeliveryTokenSigner:
    """Issue scoped HMAC grants without placing API credentials in a URL."""

    def __init__(
        self,
        secret: bytes | str | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if secret is None:
            secret = secrets.token_bytes(32)
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if len(secret) < 16:
            raise ValueError("delivery signing secret must be at least 16 bytes")
        self._secret = secret
        self._clock = clock

    def issue(
        self,
        *,
        job_id: str,
        owner_key: str,
        artifact: str,
        purge_after_delivery: bool = False,
        lifetime_seconds: int = 10 * 60,
    ) -> tuple[str, int]:
        if not 30 <= lifetime_seconds <= 60 * 60:
            raise ValueError("delivery token lifetime must be between 30 and 3600 seconds")
        expires_at = int(self._clock()) + lifetime_seconds
        payload = {
            "v": 1,
            "j": job_id,
            "o": owner_key,
            "a": artifact,
            "p": bool(purge_after_delivery),
            "e": expires_at,
            "n": secrets.token_urlsafe(9),
        }
        encoded = _encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _encode(hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}", expires_at

    def verify(self, token: str) -> DeliveryGrant:
        encoded, separator, supplied_signature = token.partition(".")
        if separator != "." or not encoded or not supplied_signature:
            raise InvalidDeliveryToken("Invalid delivery token")
        expected_signature = _encode(
            hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidDeliveryToken("Invalid delivery token")
        try:
            payload: Any = json.loads(_decode(encoded))
            if not isinstance(payload, dict) or payload.get("v") != 1:
                raise ValueError
            expires_at = int(payload["e"])
            if expires_at < int(self._clock()):
                raise InvalidDeliveryToken("Delivery token has expired")
            job_id = str(payload["j"])
            owner_key = str(payload["o"])
            artifact = str(payload["a"])
            if not job_id or not owner_key or not artifact:
                raise ValueError
            return DeliveryGrant(
                job_id=job_id,
                owner_key=owner_key,
                artifact=artifact,
                purge_after_delivery=bool(payload.get("p")),
                expires_at=expires_at,
            )
        except InvalidDeliveryToken:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InvalidDeliveryToken("Invalid delivery token") from exc

