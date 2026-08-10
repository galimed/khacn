"""NEWS2 trend detection — deterioration over a series of observations.

WHY THIS EXISTS
----------------
A single NEWS2 score is a snapshot. A patient whose score climbs from 1 to 4
over a few hours is deteriorating in a way that matters clinically, even
though a total of 4 alone is only low-medium risk. news2.py deliberately
says nothing about time — it scores one observation set. This module adds
the missing dimension: given a chronological series of NEWS2 results for
the same patient, has their trajectory become concerning?

DESIGN CHOICES (this API and its thresholds are a GALIMED addition, not
part of the published RCP NEWS2 standard — documented here because the
project asked for that design to be explicit)
--------------------------------------------------------------------------
1. Trigger definition: compare the latest total against the LOWEST total
   seen within a trailing time window, not just against the immediately
   preceding reading. A steady climb (+1 every hour for four hours) is
   just as clinically significant as one sudden +3 jump, and comparing
   only consecutive pairs would miss the former. Comparing against the
   window's minimum catches both with one rule.

2. Defaults: a 4-hour window and a 3-point rise threshold, taken directly
   from the brief's own example ("a rise of 3 points in 4 hours matters
   clinically even if the total stays moderate"). Both are parameters,
   not constants, so a site can tune them to local escalation protocol —
   nothing here claims to be the one true threshold.

3. Observations are sorted by timestamp internally rather than trusted to
   arrive in order: clinical data is entered by humans, and out-of-order
   entry (a late-charted observation, a correction) is routine.

4. Fewer than two observations fall inside the window: the result says so
   explicitly (`is_deteriorating=False` with a reason naming the gap),
   rather than returning a bare False that reads as "confirmed stable."
   Absence of evidence is not evidence of absence.

5. Out of scope on purpose: this module never reports improvement or
   "recovering" trends, and it does not re-derive per-parameter red flags
   (news2.Result.has_red_score already covers that for a single reading).
   It answers exactly one question — is the trajectory rising fast enough,
   right now, to matter — and leaves everything else to news2.py.

CLINICAL SAFETY
----------------
Like NEWS2 itself, this is a triage aid, not a diagnosis. A trend that
does not cross the threshold does not mean a patient is safe: it means this
particular rule did not fire. It never overrides a clinician's judgement.

No third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from news2 import News2Result

__all__ = [
    "TrendError",
    "Observation",
    "TrendResult",
    "assess_trend",
    "DEFAULT_WINDOW",
    "DEFAULT_RISE_THRESHOLD",
]

DEFAULT_WINDOW = timedelta(hours=4)
DEFAULT_RISE_THRESHOLD = 3


class TrendError(ValueError):
    """Raised for an invalid observation series."""


@dataclass(frozen=True)
class Observation:
    """One NEWS2 result, timestamped."""

    timestamp: datetime
    result: News2Result

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise TrendError("Observation.timestamp must be a datetime")
        if not isinstance(self.result, News2Result):
            raise TrendError("Observation.result must be a news2.News2Result")


@dataclass(frozen=True)
class TrendResult:
    is_deteriorating: bool
    latest: Observation
    baseline: Optional[Observation]    # the lowest-total observation the rise was measured against
    rise: int                           # latest.total - baseline.total; 0 if there was no baseline
    observations_in_window: int
    window: timedelta
    rise_threshold: int
    reason: str


def assess_trend(
    observations: Sequence[Observation],
    *,
    window: timedelta = DEFAULT_WINDOW,
    rise_threshold: int = DEFAULT_RISE_THRESHOLD,
) -> TrendResult:
    """Assess deterioration as of the most recent observation in the series.

    Looks back `window` from the latest timestamp, finds the lowest NEWS2
    total in that span, and flags deterioration if the latest total has
    risen by at least `rise_threshold` above it.
    """
    if not observations:
        raise TrendError("assess_trend requires at least one observation")
    for obs in observations:
        if not isinstance(obs, Observation):
            raise TrendError("every item must be a trend.Observation")
    if window <= timedelta(0):
        raise TrendError("window must be a positive timedelta")
    if rise_threshold < 1:
        raise TrendError("rise_threshold must be at least 1")

    ordered = sorted(observations, key=lambda o: o.timestamp)
    latest = ordered[-1]
    window_start = latest.timestamp - window
    in_window = [o for o in ordered if window_start <= o.timestamp <= latest.timestamp]

    if len(in_window) < 2:
        return TrendResult(
            is_deteriorating=False,
            latest=latest,
            baseline=None,
            rise=0,
            observations_in_window=len(in_window),
            window=window,
            rise_threshold=rise_threshold,
            reason=(
                f"Only {len(in_window)} observation(s) in the last {window}; at least 2 "
                f"are needed to assess a trend. Not enough data — this is not a "
                f"confirmation of stability."
            ),
        )

    baseline = min(in_window, key=lambda o: o.result.total)
    rise = latest.result.total - baseline.result.total
    is_deteriorating = rise >= rise_threshold

    if is_deteriorating:
        reason = (
            f"NEWS2 rose by {rise} point(s) (from {baseline.result.total} to "
            f"{latest.result.total}) between {baseline.timestamp.isoformat()} and "
            f"{latest.timestamp.isoformat()}, within the {window} monitoring window — "
            f"clinically significant even if the absolute total is not yet high. "
            f"Escalate for reassessment."
        )
    else:
        reason = (
            f"No rise of {rise_threshold}+ point(s) within the last {window} "
            f"(largest rise found: {rise} point(s), from {baseline.result.total} to "
            f"{latest.result.total})."
        )

    return TrendResult(
        is_deteriorating=is_deteriorating,
        latest=latest,
        baseline=baseline,
        rise=rise,
        observations_in_window=len(in_window),
        window=window,
        rise_threshold=rise_threshold,
        reason=reason,
    )


if __name__ == "__main__":  # pragma: no cover - manual demo
    import news2

    def obs(hour: int, total_target_rr: int) -> Observation:
        vitals = news2.Vitals(
            respiratory_rate=total_target_rr, spo2=97, on_oxygen=False,
            systolic_bp=118, pulse=80, consciousness=news2.Consciousness.ALERT,
            temperature=36.9,
        )
        return Observation(datetime(2026, 1, 1, hour, 0), news2.score_vitals(vitals))

    series = [obs(8, 16), obs(10, 20), obs(12, 22)]  # RR climbing: NEWS2 0 -> 1 -> 2
    trend = assess_trend(series)
    print("is_deteriorating:", trend.is_deteriorating)
    print(trend.reason)
