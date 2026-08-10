"""Ed25519 (RFC 8032) digital signatures, pure Python.

WHY THIS EXISTS
---------------
GALIMED license keys must be unforgeable by anyone who can only *verify*
them (a clinic's laptop, disconnected from the internet). That rules out
any symmetric scheme (HMAC, etc.): if the verifier holds the same secret
used to sign, the verifier can also forge. Ed25519 is asymmetric — the
private key that *issues* a license never leaves the vendor's server; the
public key embedded in this codebase can only check a signature, never
produce one. See licensing.py for how this is used.

No third-party dependencies: only hashlib (SHA-512) from the standard
library. The elliptic-curve arithmetic (Curve25519 in twisted Edwards
form) is implemented from scratch below, following RFC 8032.

SELF-TEST
---------
Per project policy, cryptographic code must prove itself against published
test vectors before anything is allowed to trust it. This module runs
`self_test()` at import time, against the first two official RFC 8032
section 7.1 test vectors (TEST 1: empty message, TEST 2: one-byte
message). If the self-test fails, importing this module raises
RuntimeError and nothing built on top of it can proceed.

Reference: S. Josefsson, I. Liusvaara. "Edwards-Curve Digital Signature
Algorithm (EdDSA)". RFC 8032, January 2017. https://www.rfc-editor.org/rfc/rfc8032
"""
from __future__ import annotations

import hashlib

__all__ = [
    "Ed25519Error",
    "generate_secret_key",
    "public_key",
    "sign",
    "verify",
    "self_test",
    "PUBLIC_KEY_SIZE",
    "SECRET_KEY_SIZE",
    "SIGNATURE_SIZE",
]


class Ed25519Error(ValueError):
    """Raised for malformed keys — never for a signature that merely fails to verify."""


# --- Curve25519 (twisted Edwards form), per RFC 8032 section 5.1 -----------

_P = 2**255 - 19  # field prime
_ORDER = 2**252 + 27742317777372353535851937790883648493  # order of the base-point subgroup
_D = (-121665 * pow(121666, _P - 2, _P)) % _P  # Edwards curve parameter d

SECRET_KEY_SIZE = 32
PUBLIC_KEY_SIZE = 32
SIGNATURE_SIZE = 64

_IDENTITY = (0, 1)


def _recover_x(y: int, sign_bit: int) -> int:
    """Given y and the desired parity of x, recover x on the curve, or raise."""
    x2 = ((y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = (x * pow(2, (_P - 1) // 4, _P)) % _P
    if (x * x - x2) % _P != 0:
        raise Ed25519Error("invalid point encoding: y has no square root for x")
    if x == 0 and sign_bit == 1:
        raise Ed25519Error("invalid point encoding: x=0 with sign bit set")
    if (x & 1) != sign_bit:
        x = _P - x
    return x


def _is_on_curve(point: tuple) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _P == 0


_BY = (4 * pow(5, _P - 2, _P)) % _P
_BX = _recover_x(_BY, 0)
_BASE_POINT = (_BX, _BY)
assert _is_on_curve(_BASE_POINT)


def _point_add(p1: tuple, p2: tuple) -> tuple:
    x1, y1 = p1
    x2, y2 = p2
    denom_x = (1 + _D * x1 * x2 * y1 * y2) % _P
    denom_y = (1 - _D * x1 * x2 * y1 * y2) % _P
    x3 = ((x1 * y2 + x2 * y1) * pow(denom_x, _P - 2, _P)) % _P
    y3 = ((y1 * y2 + x1 * x2) * pow(denom_y, _P - 2, _P)) % _P
    return (x3, y3)


def _scalar_mult(point: tuple, scalar: int) -> tuple:
    result = _IDENTITY
    addend = point
    while scalar > 0:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def _encode_point(point: tuple) -> bytes:
    x, y = point
    value = y | ((x & 1) << 255)
    return value.to_bytes(32, "little")


def _decode_point(data: bytes) -> tuple:
    if len(data) != 32:
        raise Ed25519Error(f"point encoding must be {32} bytes, got {len(data)}")
    value = int.from_bytes(data, "little")
    sign_bit = (value >> 255) & 1
    y = value & ((1 << 255) - 1)
    if y >= _P:
        raise Ed25519Error("invalid point encoding: y out of range")
    x = _recover_x(y, sign_bit)
    point = (x, y)
    if not _is_on_curve(point):
        raise Ed25519Error("decoded point is not on the curve")
    return point


def _encode_scalar(value: int) -> bytes:
    return (value % _ORDER).to_bytes(32, "little")


def _hash_to_scalar(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _ORDER


def _clamp(scalar_bytes: bytes) -> int:
    s = bytearray(scalar_bytes)
    s[0] &= 248
    s[31] &= 127
    s[31] |= 64
    return int.from_bytes(bytes(s), "little")


def _expand_secret(secret_key: bytes) -> tuple:
    """Return (clamped scalar a, nonce prefix, encoded public key A)."""
    if not isinstance(secret_key, (bytes, bytearray)) or len(secret_key) != SECRET_KEY_SIZE:
        raise Ed25519Error(f"secret key must be exactly {SECRET_KEY_SIZE} bytes")
    digest = hashlib.sha512(bytes(secret_key)).digest()
    a = _clamp(digest[:32])
    prefix = digest[32:]
    a_point = _scalar_mult(_BASE_POINT, a)
    return a, prefix, _encode_point(a_point)


# --- Public API --------------------------------------------------------


def generate_secret_key() -> bytes:
    """Generate a fresh random 32-byte secret key (seed).

    Uses os.urandom via the stdlib `secrets` module — a CSPRNG, appropriate
    for key material.
    """
    import secrets

    return secrets.token_bytes(SECRET_KEY_SIZE)


def public_key(secret_key: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret key."""
    _, _, a_encoded = _expand_secret(secret_key)
    return a_encoded


def sign(message: bytes, secret_key: bytes) -> bytes:
    """Sign `message` with `secret_key`, returning a 64-byte signature."""
    if not isinstance(message, (bytes, bytearray)):
        raise Ed25519Error("message must be bytes")
    a, prefix, a_encoded = _expand_secret(secret_key)
    message = bytes(message)
    r = _hash_to_scalar(prefix + message)
    r_point = _scalar_mult(_BASE_POINT, r)
    r_encoded = _encode_point(r_point)
    k = _hash_to_scalar(r_encoded + a_encoded + message)
    s = (r + k * a) % _ORDER
    return r_encoded + _encode_scalar(s)


def verify(message: bytes, signature: bytes, public_key_bytes: bytes) -> bool:
    """Return True iff `signature` is a valid Ed25519 signature of `message`
    under `public_key_bytes`.

    Never raises for a signature that merely fails to verify, or for a
    malformed signature/message/key of the wrong shape — all of those
    simply mean "not valid" and return False. This is deliberate: a
    licensing check must fail closed on garbage input, not crash.
    """
    if not isinstance(message, (bytes, bytearray)):
        return False
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != SIGNATURE_SIZE:
        return False
    if not isinstance(public_key_bytes, (bytes, bytearray)) or len(public_key_bytes) != PUBLIC_KEY_SIZE:
        return False
    message = bytes(message)
    r_encoded, s_encoded = bytes(signature[:32]), bytes(signature[32:])
    s = int.from_bytes(s_encoded, "little")
    if s >= _ORDER:
        return False
    try:
        r_point = _decode_point(r_encoded)
        a_point = _decode_point(bytes(public_key_bytes))
    except Ed25519Error:
        return False
    k = _hash_to_scalar(r_encoded + bytes(public_key_bytes) + message)
    lhs = _scalar_mult(_BASE_POINT, s)
    rhs = _point_add(r_point, _scalar_mult(a_point, k))
    return lhs == rhs


# --- Self-test against RFC 8032 section 7.1 published vectors ----------

_RFC8032_VECTORS = (
    # (secret key, public key, message, signature) — all hex, TEST 1 / TEST 2
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"[:64],
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"[:64],
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901"
        "555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"[:64],
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"[:64],
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69"
        "da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
)


def self_test() -> None:
    """Verify this implementation against published RFC 8032 test vectors.

    Raises RuntimeError if anything does not match exactly. Called
    automatically at import time (see bottom of this module) — importing
    ed25519 without a working implementation underneath is not allowed.
    """
    for index, (sk_hex, pk_hex, msg_hex, sig_hex) in enumerate(_RFC8032_VECTORS, start=1):
        sk = bytes.fromhex(sk_hex)
        pk_expected = bytes.fromhex(pk_hex)
        msg = bytes.fromhex(msg_hex)
        sig_expected = bytes.fromhex(sig_hex)

        pk_got = public_key(sk)
        if pk_got != pk_expected:
            raise RuntimeError(
                f"Ed25519 self-test FAILED (RFC 8032 TEST {index}): "
                f"public key derivation mismatch"
            )

        sig_got = sign(msg, sk)
        if sig_got != sig_expected:
            raise RuntimeError(
                f"Ed25519 self-test FAILED (RFC 8032 TEST {index}): "
                f"signature does not match published vector"
            )

        if not verify(msg, sig_expected, pk_expected):
            raise RuntimeError(
                f"Ed25519 self-test FAILED (RFC 8032 TEST {index}): "
                f"verify() rejected a valid published signature"
            )

    # A tampered message must not verify — sanity check beyond the raw vectors.
    sk = bytes.fromhex(_RFC8032_VECTORS[1][0])
    pk = bytes.fromhex(_RFC8032_VECTORS[1][1])
    sig = bytes.fromhex(_RFC8032_VECTORS[1][3])
    if verify(b"\x73", sig, pk):
        raise RuntimeError("Ed25519 self-test FAILED: verify() accepted a tampered message")


self_test()


if __name__ == "__main__":  # pragma: no cover - manual demo
    print("[ok] Ed25519 self-test passed (RFC 8032 TEST 1 and TEST 2 vectors)")
    demo_sk = generate_secret_key()
    demo_pk = public_key(demo_sk)
    demo_msg = b"GALIMED license demo"
    demo_sig = sign(demo_msg, demo_sk)
    print("generated keypair, signed a message, verify ->", verify(demo_msg, demo_sig, demo_pk))
