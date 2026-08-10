"""GALIMED license keys — Ed25519-signed, offline-verifiable.

WHY THIS EXISTS
---------------
gate.py needs to tell a paid clinic from an evaluation user without ever
phoning home: hospital networks are often air-gapped, and a licensing check
that requires internet access is a licensing check that breaks in production.
So a license key must be self-contained and verifiable with nothing but the
public key embedded below.

That is exactly what an Ed25519 signature gives us (see ed25519.py for why
asymmetric, not HMAC, is the right primitive here): GALIMED signs a license
with a private key that never leaves the vendor's side; this module ships
only the public key, which can check a signature but never produce one.

WHAT A LICENSE KEY IS
----------------------
A license key is a compact string: base64url(payload JSON) + "." +
base64url(Ed25519 signature over that JSON). The payload carries who the
license is for, what it entitles them to, and its validity window:

    {"v": 1, "recipient": "...", "formula": "clinic",
     "issued": "2026-01-15", "expires": "2027-01-15"}

`expires` may be null for a perpetual license. Verification is a pure
function of (license_key, public_key, today) — no network, no state.

No third-party dependencies.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import ed25519

__all__ = [
    "LicenseError",
    "License",
    "GALIMED_PUBLIC_KEY",
    "issue_license",
    "verify_license",
]

_PAYLOAD_VERSION = 1

# The GALIMED vendor's Ed25519 public key. Only this module's counterpart
# private key (held offline by the vendor, never in this repository) can
# produce a signature this key accepts — see COMMERCIAL.md for how a real
# license is issued.
GALIMED_PUBLIC_KEY = bytes.fromhex(
    "b1479503e7cc507af5c409b761584c2f906b132d2fddae7a6149f6054c38b519"[:64]
)


class LicenseError(ValueError):
    """Raised for any license key that must not be trusted: bad signature,
    signature from the wrong key, malformed payload, or expired validity."""


@dataclass(frozen=True)
class License:
    """A verified license. If you hold one of these, `verify_license` has
    already checked the signature and the expiry — trust it."""

    recipient: str
    formula: str
    issued: date
    expires: Optional[date]

    @property
    def is_perpetual(self) -> bool:
        return self.expires is None


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _canonical_payload_bytes(payload: dict) -> bytes:
    """Deterministic serialization: same payload always signs to the same
    bytes, so verification can recompute it exactly for the signature check."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def issue_license(
    private_key: bytes,
    recipient: str,
    formula: str,
    issued: Optional[date] = None,
    expires: Optional[date] = None,
) -> str:
    """Issue a signed license key. Server-side only: requires the private key.

    `recipient` identifies who the license is for (e.g. an institution name
    or contract reference). `formula` is the commercial tier (see
    COMMERCIAL.md), an opaque string as far as this module is concerned.
    `expires=None` issues a perpetual license.
    """
    if not recipient or not recipient.strip():
        raise LicenseError("recipient must not be empty")
    if not formula or not formula.strip():
        raise LicenseError("formula must not be empty")
    if issued is None:
        issued = datetime.now(timezone.utc).date()
    if expires is not None and expires < issued:
        raise LicenseError("expires date must not be before issued date")

    payload = {
        "v": _PAYLOAD_VERSION,
        "recipient": recipient,
        "formula": formula,
        "issued": issued.isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    payload_bytes = _canonical_payload_bytes(payload)
    signature = ed25519.sign(payload_bytes, private_key)
    return f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def verify_license(
    license_key: str,
    public_key: bytes = GALIMED_PUBLIC_KEY,
    today: Optional[date] = None,
) -> License:
    """Verify a license key entirely offline. Raises LicenseError if the
    signature does not check out, the key is malformed, or it has expired.

    `today` defaults to the real current date; tests pass it explicitly to
    check expiry without depending on the clock.
    """
    if not isinstance(license_key, str) or license_key.count(".") != 1:
        raise LicenseError("malformed license key")

    payload_part, signature_part = license_key.split(".", 1)
    try:
        payload_bytes = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
    except Exception as exc:  # noqa: BLE001 - any decode failure means "not a license key"
        raise LicenseError(f"malformed license key: {exc}") from exc

    if not ed25519.verify(payload_bytes, signature, public_key):
        raise LicenseError("license signature is invalid — key is forged, corrupted, or was signed by a different private key")

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise LicenseError(f"malformed license payload: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("v") != _PAYLOAD_VERSION:
        raise LicenseError(f"unsupported license payload version: {payload.get('v') if isinstance(payload, dict) else payload!r}")

    try:
        recipient = payload["recipient"]
        formula = payload["formula"]
        issued = date.fromisoformat(payload["issued"])
        expires = date.fromisoformat(payload["expires"]) if payload["expires"] else None
    except (KeyError, TypeError, ValueError) as exc:
        raise LicenseError(f"malformed license payload: {exc}") from exc

    if today is None:
        today = datetime.now(timezone.utc).date()
    if expires is not None and today > expires:
        raise LicenseError(f"license expired on {expires.isoformat()}")

    return License(recipient=recipient, formula=formula, issued=issued, expires=expires)


if __name__ == "__main__":  # pragma: no cover - manual demo
    demo_sk = ed25519.generate_secret_key()
    demo_pk = ed25519.public_key(demo_sk)
    key = issue_license(demo_sk, recipient="Demo Clinic", formula="clinic", expires=date(2099, 1, 1))
    print("license key:", key)
    print("verified:", verify_license(key, public_key=demo_pk))
