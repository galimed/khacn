"""Test suite for the Ed25519 implementation.

Standard library only: python3 -m unittest discover -v
"""
import unittest

from ed25519 import (
    Ed25519Error,
    PUBLIC_KEY_SIZE,
    SECRET_KEY_SIZE,
    SIGNATURE_SIZE,
    generate_secret_key,
    public_key,
    sign,
    verify,
)


class TestKeyGeneration(unittest.TestCase):
    def test_generate_secret_key_has_correct_length(self):
        self.assertEqual(len(generate_secret_key()), SECRET_KEY_SIZE)

    def test_two_generated_keys_are_different(self):
        self.assertNotEqual(generate_secret_key(), generate_secret_key())

    def test_public_key_has_correct_length(self):
        pk = public_key(generate_secret_key())
        self.assertEqual(len(pk), PUBLIC_KEY_SIZE)

    def test_public_key_is_deterministic(self):
        sk = generate_secret_key()
        self.assertEqual(public_key(sk), public_key(sk))

    def test_different_secret_keys_give_different_public_keys(self):
        self.assertNotEqual(public_key(generate_secret_key()), public_key(generate_secret_key()))


class TestSignAndVerifyRoundtrip(unittest.TestCase):
    def setUp(self):
        self.sk = generate_secret_key()
        self.pk = public_key(self.sk)

    def test_valid_signature_verifies(self):
        sig = sign(b"hello, galimed", self.sk)
        self.assertTrue(verify(b"hello, galimed", sig, self.pk))

    def test_signature_has_correct_length(self):
        sig = sign(b"payload", self.sk)
        self.assertEqual(len(sig), SIGNATURE_SIZE)

    def test_empty_message_can_be_signed_and_verified(self):
        sig = sign(b"", self.sk)
        self.assertTrue(verify(b"", sig, self.pk))

    def test_signing_is_deterministic(self):
        # Ed25519 nonces are derived from the message and key, not random —
        # signing the same message twice must produce the same signature.
        self.assertEqual(sign(b"repeat me", self.sk), sign(b"repeat me", self.sk))


class TestTamperingIsRejected(unittest.TestCase):
    def setUp(self):
        self.sk = generate_secret_key()
        self.pk = public_key(self.sk)
        self.message = b"authorize 25 free scorings"
        self.sig = sign(self.message, self.sk)

    def test_altered_message_does_not_verify(self):
        self.assertFalse(verify(b"authorize 250 free scorings", self.sig, self.pk))

    def test_altered_signature_byte_does_not_verify(self):
        tampered = bytes([self.sig[0] ^ 0x01]) + self.sig[1:]
        self.assertFalse(verify(self.message, tampered, self.pk))

    def test_signature_from_a_different_key_does_not_verify(self):
        other_pk = public_key(generate_secret_key())
        self.assertFalse(verify(self.message, self.sig, other_pk))

    def test_signature_for_a_different_message_does_not_verify(self):
        other_sig = sign(b"a different message entirely", self.sk)
        self.assertFalse(verify(self.message, other_sig, self.pk))


class TestMalformedInputFailsClosed(unittest.TestCase):
    def setUp(self):
        self.sk = generate_secret_key()
        self.pk = public_key(self.sk)
        self.sig = sign(b"msg", self.sk)

    def test_wrong_length_signature_returns_false_not_raise(self):
        self.assertFalse(verify(b"msg", self.sig[:-1], self.pk))
        self.assertFalse(verify(b"msg", self.sig + b"\x00", self.pk))
        self.assertFalse(verify(b"msg", b"", self.pk))

    def test_wrong_length_public_key_returns_false_not_raise(self):
        self.assertFalse(verify(b"msg", self.sig, self.pk[:-1]))
        self.assertFalse(verify(b"msg", self.sig, self.pk + b"\x00"))
        self.assertFalse(verify(b"msg", self.sig, b""))

    def test_public_key_not_on_curve_returns_false(self):
        # All-0xff is not a valid point encoding for almost every choice of y.
        garbage_key = b"\xff" * PUBLIC_KEY_SIZE
        self.assertFalse(verify(b"msg", self.sig, garbage_key))

    def test_scalar_s_greater_or_equal_to_order_returns_false(self):
        # Forge a signature whose S component is way out of range.
        forged = self.sig[:32] + b"\xff" * 32
        self.assertFalse(verify(b"msg", forged, self.pk))

    def test_secret_key_wrong_length_raises_ed25519error(self):
        with self.assertRaises(Ed25519Error):
            public_key(b"\x00" * 16)
        with self.assertRaises(Ed25519Error):
            sign(b"msg", b"\x00" * 16)


class TestKnownAnswerVectors(unittest.TestCase):
    """RFC 8032 section 7.1, TEST 1 and TEST 2 — re-checked independently of
    the module's own self-test, so a change to self_test() can't silently
    stop catching a regression here."""

    def test_vector_1_empty_message(self):
        sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"[:64])
        pk_expected = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"[:64])
        sig_expected = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901"
            "555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertEqual(public_key(sk), pk_expected)
        self.assertEqual(sign(b"", sk), sig_expected)
        self.assertTrue(verify(b"", sig_expected, pk_expected))

    def test_vector_2_one_byte_message(self):
        sk = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"[:64])
        pk_expected = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"[:64])
        message = bytes.fromhex("72")
        sig_expected = bytes.fromhex(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69"
            "da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        )
        self.assertEqual(public_key(sk), pk_expected)
        self.assertEqual(sign(message, sk), sig_expected)
        self.assertTrue(verify(message, sig_expected, pk_expected))


if __name__ == "__main__":
    unittest.main()
