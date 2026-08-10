"""Test suite for the NEWS2 implementation.

Boundary values are where clinical scoring code goes wrong: an off-by-one at a
threshold silently under-scores a deteriorating patient. Every band edge is
therefore tested on both sides.

Standard library only:  python3 -m unittest discover -v
"""
import unittest

from news2 import (
    Consciousness,
    News2Result,
    RiskLevel,
    SpO2Scale,
    Vitals,
    VitalsError,
    score_vitals,
)


def healthy(**overrides):
    """A vitals set that scores 0 on every parameter, with optional overrides."""
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


def points_for(param_name, **overrides):
    """Score one vitals set and return the points for a single parameter."""
    result = score_vitals(healthy(**overrides))
    for p in result.parameters:
        if p.name.startswith(param_name):
            return p.points
    raise AssertionError(f"parameter {param_name!r} not found in breakdown")


class TestBaseline(unittest.TestCase):
    def test_healthy_patient_scores_zero(self):
        result = score_vitals(healthy())
        self.assertEqual(result.total, 0)
        self.assertEqual(result.risk, RiskLevel.LOW)
        self.assertFalse(result.has_red_score)
        self.assertIn("Routine monitoring", result.recommendation)

    def test_breakdown_covers_all_seven_parameters(self):
        result = score_vitals(healthy())
        self.assertEqual(len(result.parameters), 7)

    def test_total_equals_sum_of_breakdown(self):
        result = score_vitals(
            healthy(respiratory_rate=22, pulse=115, temperature=38.5, on_oxygen=True)
        )
        self.assertEqual(result.total, sum(p.points for p in result.parameters))


class TestRespiratoryRateBands(unittest.TestCase):
    CASES = [
        (4, 3), (8, 3),        # <=8
        (9, 1), (11, 1),       # 9-11
        (12, 0), (20, 0),      # 12-20
        (21, 2), (24, 2),      # 21-24
        (25, 3), (40, 3),      # >=25
    ]

    def test_bands(self):
        for rr, expected in self.CASES:
            with self.subTest(respiratory_rate=rr):
                self.assertEqual(points_for("respiratory_rate", respiratory_rate=rr), expected)


class TestSpO2Scale1Bands(unittest.TestCase):
    CASES = [
        (85, 3), (91, 3),      # <=91
        (92, 2), (93, 2),      # 92-93
        (94, 1), (95, 1),      # 94-95
        (96, 0), (100, 0),     # >=96
    ]

    def test_bands(self):
        for spo2, expected in self.CASES:
            with self.subTest(spo2=spo2):
                self.assertEqual(points_for("spo2", spo2=spo2), expected)


class TestSpO2Scale2Bands(unittest.TestCase):
    """Scale 2 (target 88-92%), used for prescribed hypercapnic patients."""

    ON_AIR = [
        (80, 3), (83, 3),      # <=83
        (84, 2), (85, 2),      # 84-85
        (86, 1), (87, 1),      # 86-87
        (88, 0), (92, 0),      # target range
        (93, 0), (100, 0),     # above target but on air -> not a concern
    ]

    ON_OXYGEN = [
        (88, 0), (92, 0),      # in target range, still 0
        (93, 1), (94, 1),      # over-oxygenated
        (95, 2), (96, 2),
        (97, 3), (100, 3),
    ]

    def test_on_air(self):
        for spo2, expected in self.ON_AIR:
            with self.subTest(spo2=spo2, oxygen=False):
                self.assertEqual(
                    points_for("spo2", spo2=spo2, on_oxygen=False, spo2_scale=SpO2Scale.SCALE_2),
                    expected,
                )

    def test_on_oxygen(self):
        for spo2, expected in self.ON_OXYGEN:
            with self.subTest(spo2=spo2, oxygen=True):
                self.assertEqual(
                    points_for("spo2", spo2=spo2, on_oxygen=True, spo2_scale=SpO2Scale.SCALE_2),
                    expected,
                )

    def test_scale_choice_changes_the_score(self):
        """The same reading must score differently on the two scales."""
        s1 = points_for("spo2", spo2=90, spo2_scale=SpO2Scale.SCALE_1)
        s2 = points_for("spo2", spo2=90, spo2_scale=SpO2Scale.SCALE_2)
        self.assertEqual(s1, 3)   # dangerously low on scale 1
        self.assertEqual(s2, 0)   # inside the prescribed target on scale 2
        self.assertNotEqual(s1, s2)


class TestOxygenBands(unittest.TestCase):
    def test_air_scores_zero(self):
        self.assertEqual(points_for("air_or_oxygen", on_oxygen=False), 0)

    def test_supplemental_oxygen_scores_two(self):
        self.assertEqual(points_for("air_or_oxygen", on_oxygen=True), 2)


class TestSystolicBloodPressureBands(unittest.TestCase):
    CASES = [
        (60, 3), (90, 3),      # <=90
        (91, 2), (100, 2),     # 91-100
        (101, 1), (110, 1),    # 101-110
        (111, 0), (219, 0),    # 111-219
        (220, 3), (260, 3),    # >=220
    ]

    def test_bands(self):
        for sbp, expected in self.CASES:
            with self.subTest(systolic_bp=sbp):
                self.assertEqual(points_for("systolic_bp", systolic_bp=sbp), expected)


class TestPulseBands(unittest.TestCase):
    CASES = [
        (35, 3), (40, 3),      # <=40
        (41, 1), (50, 1),      # 41-50
        (51, 0), (90, 0),      # 51-90
        (91, 1), (110, 1),     # 91-110
        (111, 2), (130, 2),    # 111-130
        (131, 3), (180, 3),    # >=131
    ]

    def test_bands(self):
        for pulse, expected in self.CASES:
            with self.subTest(pulse=pulse):
                self.assertEqual(points_for("pulse", pulse=pulse), expected)


class TestConsciousnessBands(unittest.TestCase):
    def test_alert_scores_zero(self):
        self.assertEqual(points_for("consciousness", consciousness=Consciousness.ALERT), 0)

    def test_every_non_alert_state_scores_three(self):
        for state in Consciousness:
            if state is Consciousness.ALERT:
                continue
            with self.subTest(consciousness=state):
                self.assertEqual(points_for("consciousness", consciousness=state), 3)


class TestTemperatureBands(unittest.TestCase):
    CASES = [
        (33.0, 3), (35.0, 3),      # <=35.0
        (35.1, 1), (36.0, 1),      # 35.1-36.0
        (36.1, 0), (38.0, 0),      # 36.1-38.0
        (38.1, 1), (39.0, 1),      # 38.1-39.0
        (39.1, 2), (41.0, 2),      # >=39.1
    ]

    def test_bands(self):
        for temp, expected in self.CASES:
            with self.subTest(temperature=temp):
                self.assertEqual(points_for("temperature", temperature=temp), expected)


class TestRiskClassification(unittest.TestCase):
    def test_total_zero_is_low_risk(self):
        self.assertEqual(score_vitals(healthy()).risk, RiskLevel.LOW)

    def test_total_one_to_four_is_low_risk(self):
        # RR 9 -> 1, temp 35.5 -> 1, pulse 95 -> 1  => total 3, no red score
        result = score_vitals(healthy(respiratory_rate=9, temperature=35.5, pulse=95))
        self.assertEqual(result.total, 3)
        self.assertFalse(result.has_red_score)
        self.assertEqual(result.risk, RiskLevel.LOW)

    def test_single_parameter_three_escalates_despite_low_total(self):
        """The red-score rule: total 3 from one parameter is NOT low risk."""
        result = score_vitals(healthy(pulse=35))   # pulse <=40 -> 3, all else 0
        self.assertEqual(result.total, 3)
        self.assertTrue(result.has_red_score)
        self.assertEqual(result.risk, RiskLevel.LOW_MEDIUM)
        self.assertIn("single parameter", result.recommendation)

    def test_total_five_is_medium_risk(self):
        # RR 22 -> 2, pulse 115 -> 2, temp 38.5 -> 1  => 5, no single 3
        result = score_vitals(healthy(respiratory_rate=22, pulse=115, temperature=38.5))
        self.assertEqual(result.total, 5)
        self.assertFalse(result.has_red_score)
        self.assertEqual(result.risk, RiskLevel.MEDIUM)

    def test_total_seven_or_more_is_high_risk(self):
        result = score_vitals(
            healthy(respiratory_rate=26, spo2=91, on_oxygen=True, systolic_bp=88)
        )
        self.assertGreaterEqual(result.total, 7)
        self.assertEqual(result.risk, RiskLevel.HIGH)
        self.assertIn("Emergency", result.recommendation)

    def test_medium_risk_takes_precedence_over_red_score_rule(self):
        """A total of 5+ is medium even when a red score is also present."""
        result = score_vitals(healthy(respiratory_rate=6, pulse=115))  # 3 + 2 = 5
        self.assertEqual(result.total, 5)
        self.assertTrue(result.has_red_score)
        self.assertEqual(result.risk, RiskLevel.MEDIUM)


class TestClinicalScenarios(unittest.TestCase):
    def test_septic_patient_scores_high(self):
        """Tachypnoeic, hypotensive, tachycardic, febrile, confused."""
        result = score_vitals(
            Vitals(
                respiratory_rate=28,
                spo2=92,
                on_oxygen=True,
                systolic_bp=85,
                pulse=125,
                consciousness=Consciousness.CONFUSION,
                temperature=39.4,
            )
        )
        # 3 + 2 + 2 + 3 + 2 + 3 + 2
        self.assertEqual(result.total, 17)
        self.assertEqual(result.risk, RiskLevel.HIGH)

    def test_stable_copd_patient_on_scale_two(self):
        """Saturation of 89% is normal for this patient's prescribed target."""
        result = score_vitals(
            Vitals(
                respiratory_rate=18,
                spo2=89,
                on_oxygen=False,
                systolic_bp=130,
                pulse=78,
                consciousness=Consciousness.ALERT,
                temperature=36.9,
                spo2_scale=SpO2Scale.SCALE_2,
            )
        )
        self.assertEqual(result.total, 0)
        self.assertEqual(result.risk, RiskLevel.LOW)

    def test_same_copd_patient_misfiled_on_scale_one_looks_critical(self):
        """Guards the scale choice: using scale 1 by mistake inflates the score."""
        result = score_vitals(
            Vitals(
                respiratory_rate=18,
                spo2=89,
                on_oxygen=False,
                systolic_bp=130,
                pulse=78,
                consciousness=Consciousness.ALERT,
                temperature=36.9,
                spo2_scale=SpO2Scale.SCALE_1,
            )
        )
        self.assertEqual(result.total, 3)
        self.assertTrue(result.has_red_score)


class TestInputValidation(unittest.TestCase):
    def test_rejects_implausible_values(self):
        bad = [
            dict(respiratory_rate=200),
            dict(spo2=140),
            dict(spo2=10),
            dict(systolic_bp=1000),
            dict(pulse=5),
            dict(temperature=60.0),
            dict(temperature=10.0),
        ]
        for overrides in bad:
            with self.subTest(**overrides):
                with self.assertRaises(VitalsError):
                    healthy(**overrides)

    def test_rejects_missing_value(self):
        with self.assertRaises(VitalsError):
            healthy(respiratory_rate=None)

    def test_rejects_non_numeric(self):
        with self.assertRaises(VitalsError):
            healthy(pulse="fast")

    def test_rejects_bool_as_number(self):
        """True is an int in Python; it must not slip through as a pulse."""
        with self.assertRaises(VitalsError):
            healthy(pulse=True)

    def test_rejects_wrong_consciousness_type(self):
        with self.assertRaises(VitalsError):
            healthy(consciousness="alert")

    def test_rejects_non_bool_oxygen_flag(self):
        with self.assertRaises(VitalsError):
            healthy(on_oxygen="yes")

    def test_score_vitals_rejects_non_vitals(self):
        with self.assertRaises(VitalsError):
            score_vitals({"pulse": 70})

    def test_boundary_values_are_accepted(self):
        """The edges of the plausible ranges must not be rejected."""
        self.assertIsInstance(score_vitals(healthy(spo2=100)), News2Result)
        self.assertIsInstance(score_vitals(healthy(temperature=25.0)), News2Result)
        self.assertIsInstance(score_vitals(healthy(temperature=45.0)), News2Result)


class TestImmutability(unittest.TestCase):
    def test_vitals_are_frozen(self):
        v = healthy()
        with self.assertRaises(Exception):
            v.pulse = 200

    def test_result_is_frozen(self):
        result = score_vitals(healthy())
        with self.assertRaises(Exception):
            result.total = 99


if __name__ == "__main__":
    unittest.main(verbosity=2)
