"""Test suite for NEWS2 trend detection.

Standard library only: python3 -m unittest discover -v
"""
import unittest
from datetime import datetime, timedelta

from news2 import Consciousness, SpO2Scale, Vitals, score_vitals
from trend import DEFAULT_RISE_THRESHOLD, DEFAULT_WINDOW, Observation, TrendError, assess_trend


def obs_at(hour, minute=0, day=1, **vitals_overrides):
    base = dict(
        respiratory_rate=16, spo2=98, on_oxygen=False, systolic_bp=120,
        pulse=70, consciousness=Consciousness.ALERT, temperature=36.8,
    )
    base.update(vitals_overrides)
    result = score_vitals(Vitals(**base))
    return Observation(datetime(2026, 1, day, hour, minute), result)


class TestInsufficientData(unittest.TestCase):
    def test_single_observation_is_not_deteriorating(self):
        trend = assess_trend([obs_at(8)])
        self.assertFalse(trend.is_deteriorating)
        self.assertIsNone(trend.baseline)
        self.assertEqual(trend.observations_in_window, 1)

    def test_two_observations_outside_the_window_of_each_other_is_insufficient(self):
        series = [obs_at(0), obs_at(23)]  # 23 hours apart, default window is 4h
        trend = assess_trend(series)
        self.assertFalse(trend.is_deteriorating)
        self.assertEqual(trend.observations_in_window, 1)  # only the latest itself

    def test_empty_series_raises(self):
        with self.assertRaises(TrendError):
            assess_trend([])


class TestRiseThresholdBoundary(unittest.TestCase):
    def test_rise_of_two_does_not_trigger(self):
        series = [obs_at(8, respiratory_rate=16), obs_at(10, respiratory_rate=22)]  # 0 -> 2
        trend = assess_trend(series)
        self.assertEqual(trend.rise, 2)
        self.assertFalse(trend.is_deteriorating)

    def test_rise_of_exactly_three_triggers(self):
        series = [obs_at(8, respiratory_rate=16), obs_at(10, respiratory_rate=25)]  # 0 -> 3
        trend = assess_trend(series)
        self.assertEqual(trend.rise, 3)
        self.assertTrue(trend.is_deteriorating)

    def test_custom_threshold_is_respected(self):
        series = [obs_at(8, respiratory_rate=16), obs_at(10, respiratory_rate=22)]  # rise of 2
        trend = assess_trend(series, rise_threshold=2)
        self.assertTrue(trend.is_deteriorating)


class TestWindowBoundary(unittest.TestCase):
    def test_rise_just_inside_the_window_counts(self):
        series = [
            obs_at(8, 0, respiratory_rate=16),
            obs_at(11, 59, respiratory_rate=25),  # 3h59 later, rise of 3
        ]
        trend = assess_trend(series, window=timedelta(hours=4))
        self.assertTrue(trend.is_deteriorating)
        self.assertEqual(trend.observations_in_window, 2)

    def test_rise_just_outside_the_window_is_excluded(self):
        series = [
            obs_at(8, 0, respiratory_rate=16),
            obs_at(12, 1, respiratory_rate=25),  # 4h01 later, outside a 4h window
        ]
        trend = assess_trend(series, window=timedelta(hours=4))
        # only the latest observation is within its own window -> insufficient data,
        # not "confirmed stable"
        self.assertEqual(trend.observations_in_window, 1)
        self.assertFalse(trend.is_deteriorating)

    def test_window_boundary_is_inclusive(self):
        series = [
            obs_at(8, 0, respiratory_rate=16),
            obs_at(12, 0, respiratory_rate=25),  # exactly 4h later
        ]
        trend = assess_trend(series, window=timedelta(hours=4))
        self.assertEqual(trend.observations_in_window, 2)
        self.assertTrue(trend.is_deteriorating)


class TestBaselineIsTheWindowMinimumNotJustThePreviousReading(unittest.TestCase):
    def test_gradual_climb_across_several_readings_triggers(self):
        # +1 every hour for three hours: no single consecutive step reaches
        # the threshold, but the cumulative rise within the window does.
        series = [
            obs_at(8, respiratory_rate=16),   # NEWS2 0
            obs_at(9, respiratory_rate=21),   # NEWS2 1
            obs_at(10, respiratory_rate=23),  # NEWS2 2
            obs_at(11, respiratory_rate=25),  # NEWS2 3
        ]
        trend = assess_trend(series)
        self.assertEqual(trend.baseline.result.total, 0)
        self.assertEqual(trend.rise, 3)
        self.assertTrue(trend.is_deteriorating)

    def test_dip_then_recovery_does_not_falsely_compare_to_an_old_high(self):
        # Baseline is the window's minimum, not its first entry — a patient
        # who was briefly worse earlier and has since improved should be
        # judged against how low they got, not how high they started.
        series = [
            obs_at(8, respiratory_rate=25),   # NEWS2 3 (high early reading)
            obs_at(9, respiratory_rate=16),   # NEWS2 0 (improved — new minimum)
            obs_at(10, temperature=38.5),     # NEWS2 1 (small rise from the dip)
        ]
        trend = assess_trend(series)
        self.assertEqual(trend.baseline.result.total, 0)
        self.assertEqual(trend.rise, 1)
        self.assertFalse(trend.is_deteriorating)


class TestOutOfOrderInput(unittest.TestCase):
    def test_observations_are_sorted_internally(self):
        series = [obs_at(11, respiratory_rate=25), obs_at(8, respiratory_rate=16)]  # reversed
        trend = assess_trend(series)
        self.assertEqual(trend.latest.timestamp, datetime(2026, 1, 1, 11))
        self.assertEqual(trend.rise, 3)
        self.assertTrue(trend.is_deteriorating)


class TestInputValidation(unittest.TestCase):
    def test_rejects_non_observation_items(self):
        with self.assertRaises(TrendError):
            assess_trend([{"timestamp": "now", "total": 3}])

    def test_observation_rejects_non_datetime_timestamp(self):
        with self.assertRaises(TrendError):
            Observation("2026-01-01T08:00:00", score_vitals(Vitals(
                respiratory_rate=16, spo2=98, on_oxygen=False, systolic_bp=120,
                pulse=70, consciousness=Consciousness.ALERT, temperature=36.8,
            )))

    def test_observation_rejects_non_news2result(self):
        with self.assertRaises(TrendError):
            Observation(datetime(2026, 1, 1, 8), {"total": 3})

    def test_non_positive_window_is_rejected(self):
        with self.assertRaises(TrendError):
            assess_trend([obs_at(8), obs_at(9)], window=timedelta(0))

    def test_rise_threshold_below_one_is_rejected(self):
        with self.assertRaises(TrendError):
            assess_trend([obs_at(8), obs_at(9)], rise_threshold=0)


class TestClinicalScenarios(unittest.TestCase):
    def test_progressive_sepsis_deterioration_over_four_hours(self):
        """A patient sliding into sepsis: each reading alone looks only
        moderately concerning, but the trajectory over four hours is not."""
        series = [
            obs_at(6, respiratory_rate=18, pulse=85, systolic_bp=115, temperature=37.5),
            obs_at(8, respiratory_rate=21, pulse=95, systolic_bp=108, temperature=38.2),
            obs_at(10, respiratory_rate=23, pulse=112, systolic_bp=98, temperature=38.9),
        ]
        trend = assess_trend(series)
        self.assertTrue(trend.is_deteriorating)
        self.assertIn("Escalate for reassessment", trend.reason)

    def test_stable_copd_patient_on_scale_two_does_not_trigger(self):
        """A COPD patient sitting steadily at their prescribed target range
        should not register a trend, even across several readings."""
        series = [
            obs_at(6, spo2=89, on_oxygen=True, spo2_scale=SpO2Scale.SCALE_2),
            obs_at(8, spo2=90, on_oxygen=True, spo2_scale=SpO2Scale.SCALE_2),
            obs_at(10, spo2=88, on_oxygen=True, spo2_scale=SpO2Scale.SCALE_2),
        ]
        trend = assess_trend(series)
        self.assertFalse(trend.is_deteriorating)

    def test_slow_deterioration_beyond_the_window_is_not_flagged_by_a_short_window(self):
        # A rise of 3 spread over 8 hours does not fall inside a 4-hour
        # window looking back from the latest reading — this rule is
        # explicitly about the *rate* of change, not any change ever.
        series = [
            obs_at(6, respiratory_rate=16),   # NEWS2 0
            obs_at(14, respiratory_rate=25),  # NEWS2 3, 8 hours later
        ]
        trend = assess_trend(series, window=timedelta(hours=4))
        self.assertFalse(trend.is_deteriorating)
        self.assertEqual(trend.observations_in_window, 1)


class TestDefaults(unittest.TestCase):
    def test_documented_defaults(self):
        self.assertEqual(DEFAULT_WINDOW, timedelta(hours=4))
        self.assertEqual(DEFAULT_RISE_THRESHOLD, 3)


if __name__ == "__main__":
    unittest.main()
