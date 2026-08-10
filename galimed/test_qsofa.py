"""Test suite for the qSOFA implementation.

Standard library only: python3 -m unittest discover -v
"""
import unittest

from news2 import Consciousness, Vitals, VitalsError
from qsofa import score_qsofa


def vitals(**overrides):
    """A baseline observation set scoring 0 on qSOFA, with overrides."""
    base = dict(
        respiratory_rate=16,
        spo2=98,
        on_oxygen=False,
        systolic_bp=120,
        pulse=70,
        consciousness=Consciousness.ALERT,
        temperature=36.8,
    )
    base.update(overrides)
    return Vitals(**base)


class TestRespiratoryRateThreshold(unittest.TestCase):
    def test_21_scores_zero(self):
        result = score_qsofa(vitals(respiratory_rate=21))
        self.assertEqual(result.total, 0)

    def test_22_scores_one(self):
        result = score_qsofa(vitals(respiratory_rate=22))
        self.assertEqual(result.total, 1)


class TestSystolicBpThreshold(unittest.TestCase):
    def test_101_scores_zero(self):
        result = score_qsofa(vitals(systolic_bp=101))
        self.assertEqual(result.total, 0)

    def test_100_scores_one(self):
        result = score_qsofa(vitals(systolic_bp=100))
        self.assertEqual(result.total, 1)


class TestConsciousnessThreshold(unittest.TestCase):
    def test_alert_scores_zero(self):
        result = score_qsofa(vitals(consciousness=Consciousness.ALERT))
        self.assertEqual(result.total, 0)

    def test_every_non_alert_state_scores_one(self):
        for state in (Consciousness.CONFUSION, Consciousness.VOICE, Consciousness.PAIN, Consciousness.UNRESPONSIVE):
            with self.subTest(state=state):
                result = score_qsofa(vitals(consciousness=state))
                self.assertEqual(result.total, 1)


class TestHighRiskClassification(unittest.TestCase):
    def test_total_zero_is_not_high_risk(self):
        self.assertFalse(score_qsofa(vitals()).high_risk)

    def test_total_one_is_not_high_risk(self):
        result = score_qsofa(vitals(respiratory_rate=24))
        self.assertEqual(result.total, 1)
        self.assertFalse(result.high_risk)

    def test_total_two_is_high_risk(self):
        result = score_qsofa(vitals(respiratory_rate=24, systolic_bp=90))
        self.assertEqual(result.total, 2)
        self.assertTrue(result.high_risk)

    def test_total_three_is_high_risk(self):
        result = score_qsofa(vitals(respiratory_rate=24, systolic_bp=90, consciousness=Consciousness.CONFUSION))
        self.assertEqual(result.total, 3)
        self.assertTrue(result.high_risk)

    def test_low_risk_recommendation_warns_it_does_not_rule_out_sepsis(self):
        result = score_qsofa(vitals())
        self.assertIn("does NOT rule out sepsis", result.recommendation)

    def test_high_risk_recommendation_calls_for_escalation(self):
        result = score_qsofa(vitals(respiratory_rate=24, systolic_bp=90))
        self.assertIn("Urgent clinical escalation", result.recommendation)


class TestClinicalScenarios(unittest.TestCase):
    def test_septic_patient_is_high_risk(self):
        """Tachypnoeic, hypotensive, confused — textbook qSOFA-positive sepsis."""
        septic = vitals(
            respiratory_rate=26,
            systolic_bp=85,
            consciousness=Consciousness.CONFUSION,
            temperature=39.2,
            pulse=118,
        )
        result = score_qsofa(septic)
        self.assertEqual(result.total, 3)
        self.assertTrue(result.high_risk)

    def test_stable_copd_patient_is_not_high_risk(self):
        """Low SpO2 on a COPD patient is a NEWS2 concern, but qSOFA doesn't
        look at SpO2 at all — an alert, normotensive COPD patient with a
        normal respiratory rate should not score on qSOFA."""
        stable_copd = vitals(
            respiratory_rate=18,
            spo2=89,
            on_oxygen=True,
            systolic_bp=130,
            consciousness=Consciousness.ALERT,
        )
        result = score_qsofa(stable_copd)
        self.assertEqual(result.total, 0)
        self.assertFalse(result.high_risk)

    def test_progressive_deterioration_crosses_the_high_risk_line(self):
        """Same patient, vitals worsening: qSOFA should flip from low to
        high risk exactly when the second criterion is met."""
        early = vitals(respiratory_rate=23, systolic_bp=115, consciousness=Consciousness.ALERT)
        later = vitals(respiratory_rate=23, systolic_bp=95, consciousness=Consciousness.ALERT)
        self.assertFalse(score_qsofa(early).high_risk)
        self.assertTrue(score_qsofa(later).high_risk)


class TestInputValidation(unittest.TestCase):
    def test_rejects_non_vitals_input(self):
        with self.assertRaises(VitalsError):
            score_qsofa({"respiratory_rate": 24})

    def test_reuses_news2_vitals_error_type(self):
        # score_qsofa must raise the same VitalsError news2 uses, not a
        # locally redefined exception type.
        with self.assertRaises(VitalsError):
            score_qsofa(None)


class TestBreakdown(unittest.TestCase):
    def test_breakdown_covers_all_three_parameters(self):
        result = score_qsofa(vitals())
        self.assertEqual(len(result.parameters), 3)
        names = {p.name for p in result.parameters}
        self.assertEqual(names, {"respiratory_rate", "systolic_bp", "consciousness"})

    def test_total_equals_sum_of_breakdown(self):
        result = score_qsofa(vitals(respiratory_rate=24, systolic_bp=90, consciousness=Consciousness.VOICE))
        self.assertEqual(result.total, sum(p.points for p in result.parameters))


if __name__ == "__main__":
    unittest.main()
