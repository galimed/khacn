"""Test suite for the commercial gate.

Standard library only: python3 -m unittest discover -v
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import ed25519
import news2
from gate import Gate, GatedResult, UsageLimitExceededError
from licensing import issue_license


def score_healthy_patient():
    vitals = news2.Vitals(
        respiratory_rate=16, spo2=98, on_oxygen=False, systolic_bp=120,
        pulse=70, consciousness=news2.Consciousness.ALERT, temperature=36.8,
    )
    return news2.score_vitals(vitals)


def score_that_always_fails():
    raise news2.VitalsError("simulated bad input")


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.usage_path = Path(self._tmpdir.name) / "usage.json"
        self.sk = ed25519.generate_secret_key()
        self.pk = ed25519.public_key(self.sk)

    def tearDown(self):
        self._tmpdir.cleanup()

    def make_gate(self, license_key=None, today=None) -> Gate:
        return Gate(license_key=license_key, usage_path=self.usage_path, public_key=self.pk, today=today)


class TestUnlicensedFreeTier(GateTestCase):
    def test_first_scoring_is_watermarked_and_not_licensed(self):
        gate = self.make_gate()
        result = gate.score(score_healthy_patient)
        self.assertIsInstance(result, GatedResult)
        self.assertFalse(result.licensed)
        self.assertIsNotNone(result.watermark)
        self.assertIn("galimedai.org", result.watermark)

    def test_remaining_free_scorings_counts_down(self):
        gate = self.make_gate()
        self.assertEqual(gate.remaining_free_scorings, 25)
        gate.score(score_healthy_patient)
        self.assertEqual(gate.remaining_free_scorings, 24)
        gate.score(score_healthy_patient)
        self.assertEqual(gate.remaining_free_scorings, 23)

    def test_exactly_25_free_scorings_are_allowed(self):
        gate = self.make_gate()
        for _ in range(25):
            gate.score(score_healthy_patient)
        self.assertEqual(gate.remaining_free_scorings, 0)

    def test_26th_scoring_raises_usage_limit_exceeded(self):
        gate = self.make_gate()
        for _ in range(25):
            gate.score(score_healthy_patient)
        with self.assertRaises(UsageLimitExceededError):
            gate.score(score_healthy_patient)

    def test_usage_limit_error_mentions_galimedai(self):
        gate = self.make_gate()
        for _ in range(25):
            gate.score(score_healthy_patient)
        with self.assertRaises(UsageLimitExceededError) as ctx:
            gate.score(score_healthy_patient)
        self.assertIn("galimedai.org", str(ctx.exception))

    def test_usage_persists_across_gate_instances_sharing_a_path(self):
        gate1 = self.make_gate()
        gate1.score(score_healthy_patient)
        gate1.score(score_healthy_patient)
        gate2 = self.make_gate()
        self.assertEqual(gate2.remaining_free_scorings, 23)

    def test_failed_scoring_does_not_consume_the_free_tier(self):
        gate = self.make_gate()
        with self.assertRaises(news2.VitalsError):
            gate.score(score_that_always_fails)
        self.assertEqual(gate.remaining_free_scorings, 25)

    def test_result_value_is_the_unwrapped_scoring_output(self):
        gate = self.make_gate()
        result = gate.score(score_healthy_patient)
        self.assertIsInstance(result.value, news2.News2Result)
        self.assertEqual(result.value.total, 0)


class TestLicensedUnlimited(GateTestCase):
    def _valid_license_key(self):
        return issue_license(
            self.sk, recipient="CHU Test", formula="clinic",
            issued=date(2026, 1, 1), expires=date(2027, 1, 1),
        )

    def test_licensed_gate_reports_licensed(self):
        gate = self.make_gate(license_key=self._valid_license_key(), today=date(2026, 6, 1))
        self.assertTrue(gate.licensed)
        self.assertIsNone(gate.remaining_free_scorings)

    def test_licensed_result_has_no_watermark(self):
        gate = self.make_gate(license_key=self._valid_license_key(), today=date(2026, 6, 1))
        result = gate.score(score_healthy_patient)
        self.assertTrue(result.licensed)
        self.assertIsNone(result.watermark)
        self.assertIsNone(result.remaining_free_scorings)

    def test_licensed_gate_exceeds_25_scorings_without_error(self):
        gate = self.make_gate(license_key=self._valid_license_key(), today=date(2026, 6, 1))
        for _ in range(30):
            result = gate.score(score_healthy_patient)
        self.assertTrue(result.licensed)

    def test_expired_license_raises_at_construction(self):
        from licensing import LicenseError

        expired_key = issue_license(
            self.sk, recipient="CHU Test", formula="clinic",
            issued=date(2020, 1, 1), expires=date(2021, 1, 1),
        )
        with self.assertRaises(LicenseError):
            self.make_gate(license_key=expired_key, today=date(2026, 6, 1))

    def test_license_signed_by_wrong_key_raises_at_construction(self):
        from licensing import LicenseError

        other_sk = ed25519.generate_secret_key()
        forged_key = issue_license(other_sk, recipient="x", formula="clinic")
        with self.assertRaises(LicenseError):
            self.make_gate(license_key=forged_key)


if __name__ == "__main__":
    unittest.main()
