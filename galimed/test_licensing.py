"""Test suite for GALIMED license issuance and verification.

Standard library only: python3 -m unittest discover -v
"""
import unittest
from datetime import date

import ed25519
from licensing import License, LicenseError, issue_license, verify_license


class TestValidLicense(unittest.TestCase):
    def setUp(self):
        self.sk = ed25519.generate_secret_key()
        self.pk = ed25519.public_key(self.sk)

    def test_perpetual_license_verifies(self):
        key = issue_license(self.sk, recipient="CHU Test", formula="clinic")
        license_ = verify_license(key, public_key=self.pk, today=date(2099, 1, 1))
        self.assertEqual(license_.recipient, "CHU Test")
        self.assertEqual(license_.formula, "clinic")
        self.assertTrue(license_.is_perpetual)

    def test_license_valid_within_its_window(self):
        key = issue_license(
            self.sk,
            recipient="CHU Test",
            formula="enterprise",
            issued=date(2026, 1, 1),
            expires=date(2027, 1, 1),
        )
        license_ = verify_license(key, public_key=self.pk, today=date(2026, 6, 15))
        self.assertFalse(license_.is_perpetual)
        self.assertEqual(license_.expires, date(2027, 1, 1))

    def test_license_valid_exactly_on_expiry_date(self):
        # The expiry date itself is still covered — expiry is exclusive of
        # the day *after* it, not the day itself.
        key = issue_license(self.sk, recipient="x", formula="clinic", expires=date(2027, 1, 1))
        verify_license(key, public_key=self.pk, today=date(2027, 1, 1))  # must not raise

    def test_issuing_requires_non_empty_recipient_and_formula(self):
        with self.assertRaises(LicenseError):
            issue_license(self.sk, recipient="", formula="clinic")
        with self.assertRaises(LicenseError):
            issue_license(self.sk, recipient="x", formula="")

    def test_expires_before_issued_is_rejected_at_issuance(self):
        with self.assertRaises(LicenseError):
            issue_license(
                self.sk, recipient="x", formula="clinic",
                issued=date(2027, 1, 1), expires=date(2026, 1, 1),
            )


class TestRejection(unittest.TestCase):
    """The three cases the project explicitly requires: a tampered key, a
    key signed by a different private key, and an expired key. All three
    must raise LicenseError, never silently succeed."""

    def setUp(self):
        self.sk = ed25519.generate_secret_key()
        self.pk = ed25519.public_key(self.sk)
        self.valid_key = issue_license(
            self.sk, recipient="CHU Test", formula="clinic",
            issued=date(2026, 1, 1), expires=date(2027, 1, 1),
        )

    def test_tampered_key_is_rejected(self):
        # Flip the license's payload half of the key (change the recipient
        # field's characters) without re-signing — the signature no longer
        # matches the modified payload.
        payload_part, signature_part = self.valid_key.split(".")
        tampered = payload_part[:-1] + ("A" if payload_part[-1] != "A" else "B")
        tampered_key = f"{tampered}.{signature_part}"
        with self.assertRaises(LicenseError):
            verify_license(tampered_key, public_key=self.pk, today=date(2026, 6, 1))

    def test_key_signed_by_a_different_private_key_is_rejected(self):
        other_sk = ed25519.generate_secret_key()
        forged_key = issue_license(
            other_sk, recipient="CHU Test", formula="clinic",
            issued=date(2026, 1, 1), expires=date(2027, 1, 1),
        )
        # Verified against the *real* GALIMED public key, not the forger's.
        with self.assertRaises(LicenseError):
            verify_license(forged_key, public_key=self.pk, today=date(2026, 6, 1))

    def test_expired_key_is_rejected(self):
        with self.assertRaises(LicenseError):
            verify_license(self.valid_key, public_key=self.pk, today=date(2027, 1, 2))


class TestMalformedKeysFailClosed(unittest.TestCase):
    def setUp(self):
        self.sk = ed25519.generate_secret_key()
        self.pk = ed25519.public_key(self.sk)

    def test_random_garbage_string_is_rejected(self):
        with self.assertRaises(LicenseError):
            verify_license("not-a-license-key", public_key=self.pk)

    def test_missing_dot_separator_is_rejected(self):
        with self.assertRaises(LicenseError):
            verify_license("nodothere", public_key=self.pk)

    def test_extra_dot_separator_is_rejected(self):
        with self.assertRaises(LicenseError):
            verify_license("a.b.c", public_key=self.pk)

    def test_non_base64_segment_is_rejected(self):
        with self.assertRaises(LicenseError):
            verify_license("!!!not-base64!!!.also-not-base64", public_key=self.pk)

    def test_valid_signature_over_non_json_payload_is_rejected(self):
        # An attacker who can get *anything* signed (unlikely, but this
        # guards the parser) must not crash verify_license.
        garbage_payload = b"not json at all"
        sig = ed25519.sign(garbage_payload, self.sk)
        from licensing import _b64url_encode  # internal, but worth pinning

        key = f"{_b64url_encode(garbage_payload)}.{_b64url_encode(sig)}"
        with self.assertRaises(LicenseError):
            verify_license(key, public_key=self.pk)


class TestDefaultsToGalimedPublicKey(unittest.TestCase):
    def test_verify_license_default_public_key_rejects_foreign_signature(self):
        # Without passing public_key explicitly, verify_license checks
        # against the real embedded GALIMED_PUBLIC_KEY — a license signed
        # by any other key (e.g. a test key) must fail.
        foreign_sk = ed25519.generate_secret_key()
        key = issue_license(foreign_sk, recipient="x", formula="clinic")
        with self.assertRaises(LicenseError):
            verify_license(key)


if __name__ == "__main__":
    unittest.main()
